"""One slice job: check the request, run the CrealityPrint CLI in a job folder, read back
result.json and the plate G-code.

Success is result.json `return_code == 0`; the exit code is not the signal.
"""

import json
import os
import re
import secrets
import shutil
import signal
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from creality_mcp.catalog import Catalog, CatalogError, Preset
from creality_mcp.gcode import PlateStats, parse_gcode
from creality_mcp.overrides import OverrideError, build_override_flags
from creality_mcp.settings import Settings

MODEL_SUFFIXES = {".stl", ".obj", ".3mf"}
JOB_NAME = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{6}$")
PLATE_NAME = re.compile(r"^plate_(\d+)\.gcode$")


class SliceError(Exception):
    """A failure whose message is safe to show Claude."""


@dataclass
class SliceRequest:
    models: list[str]
    printer: str | None = None
    printer_vendor: str | None = None
    process: str | None = None
    filaments: list[str] | None = None
    filament_ids: list[int] | None = None
    overrides: dict | None = None


@dataclass
class SliceResult:
    job_dir: str
    plates: list[PlateStats]
    used: dict
    missing_stats: list[str] = field(default_factory=list)


@dataclass
class _Presets:
    machine: Preset
    process: Preset
    filaments: list[Preset]


def run_slice(req: SliceRequest, settings: Settings, catalog: Catalog) -> SliceResult:
    models = _check_models(req)
    is_3mf = models[0].suffix.lower() == ".3mf"
    overrides = req.overrides or {}
    try:
        if is_3mf:
            presets = None
            known = catalog.process_keys()
        else:
            presets = _select_presets(req, settings, catalog, len(models))
            known = set(catalog.resolve(presets.process))
        flags = build_override_flags(overrides, known)
    except (CatalogError, OverrideError) as exc:
        raise SliceError(str(exc)) from exc

    job = new_job_dir(settings.output, settings.max_jobs)
    argv = build_argv(settings.app, job, presets, req.filament_ids, flags, models)
    exit_code = _execute(argv, job, settings.timeout_s)
    result = read_result(job, exit_code)
    plates = _read_plates(job, result)
    if presets is None:
        used = _used_from_gcode(plates[0])
    else:
        used = {
            "printer": presets.machine.name,
            "process": presets.process.name,
            "filaments": [f.name for f in presets.filaments],
        }
    return SliceResult(
        job_dir=str(job),
        plates=plates,
        used={**used, "overrides": dict(overrides)},
        missing_stats=sorted({m for p in plates for m in p.missing}),
    )


def _check_models(req: SliceRequest) -> list[Path]:
    if not req.models:
        raise SliceError("no model given")
    models = [Path(m).expanduser().resolve() for m in req.models]
    for path in models:
        if not path.is_file():
            raise SliceError(f"model not found: {path}")
        if path.suffix.lower() not in MODEL_SUFFIXES:
            raise SliceError(f"unsupported model type {path.suffix!r}: use .stl, .obj or .3mf")
    n_3mf = sum(p.suffix.lower() == ".3mf" for p in models)
    if n_3mf and n_3mf != len(models):
        raise SliceError("do not mix 3MF with STL/OBJ models in one slice")
    if n_3mf > 1:
        raise SliceError("slice one 3MF at a time")
    if n_3mf and (req.printer or req.process or req.filaments):
        raise SliceError(
            "3MF uses its stored printer and presets in V1; the server allows only overrides"
        )
    return models


def _select_presets(
    req: SliceRequest, settings: Settings, catalog: Catalog, n_models: int
) -> _Presets:
    machine = catalog.find("machine", req.printer or settings.default_printer, req.printer_vendor)
    default_process, default_filaments = catalog.defaults(machine)
    process_name = req.process or default_process
    if not process_name:
        raise SliceError(f"printer '{machine.name}' names no default process; pass process")
    filament_names = req.filaments or default_filaments
    if not filament_names:
        raise SliceError(f"printer '{machine.name}' names no default filament; pass filaments")
    process = _compatible(catalog, machine, "process", process_name)
    filaments = [_compatible(catalog, machine, "filament", n) for n in filament_names]
    if req.filament_ids is not None:
        if len(req.filament_ids) != n_models:
            raise SliceError(
                f"filament_ids needs one number for each model ({n_models}), "
                f"got {len(req.filament_ids)}"
            )
        bad = [i for i in req.filament_ids if not 1 <= i <= len(filaments)]
        if bad:
            raise SliceError(f"filament_ids must be between 1 and {len(filaments)}; got {bad}")
    return _Presets(machine, process, filaments)


def _compatible(catalog: Catalog, machine: Preset, kind: str, name: str) -> Preset:
    for preset in catalog.compatible(machine, kind):
        if preset.name == name:
            return preset
    raise SliceError(
        f"{kind} preset '{name}' is not compatible with printer '{machine.name}'; "
        f"call list_presets to see the compatible ones"
    )


def new_job_dir(output: Path, max_jobs: int) -> Path:
    """A new job folder; first deletes the oldest job folders beyond `max_jobs - 1`. Only
    folders whose names match the job pattern are ever deleted."""
    output.mkdir(parents=True, exist_ok=True)
    jobs = sorted(p for p in output.iterdir() if p.is_dir() and JOB_NAME.match(p.name))
    for old in jobs[: max(0, len(jobs) - (max_jobs - 1))]:
        shutil.rmtree(old)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    job = output / f"{stamp}-{secrets.token_hex(3)}"
    job.mkdir()
    return job


def build_argv(
    app: Path,
    job: Path,
    presets: _Presets | None,
    filament_ids: list[int] | None,
    flags: list[str],
    models: list[Path],
) -> list[str]:
    argv = [str(app), "--cli", "--slice", "0", "--need-gcode-file", "--outputdir", str(job)]
    if presets is not None:
        argv += [
            "--load-settings",
            f"{presets.machine.path};{presets.process.path}",
            "--load-filaments",
            ";".join(str(f.path) for f in presets.filaments),
        ]
        if filament_ids:
            argv += ["--load-filament-ids", ",".join(str(i) for i in filament_ids)]
    return argv + flags + [str(m) for m in models]


def _execute(argv: list[str], job: Path, timeout_s: int) -> int:
    with (job / "slicer.log").open("wb") as log:
        proc = subprocess.Popen(  # noqa: S603 - argv list, no shell; paths checked first
            argv, cwd=job, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            # AppRun ends in exec, so the process group holds the slicer.
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            raise SliceError(f"slicer timed out after {timeout_s} s") from None
    return proc.returncode


def read_result(job: Path, exit_code: int) -> dict:
    path = job / "result.json"
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise SliceError(
            f"slicer failed with no result (exit {exit_code}):\n{log_tail(job)}"
        ) from None
    rc = result.get("return_code")
    if rc != 0:
        raise SliceError(f"{result.get('error_string')} (return_code {rc}):\n{log_tail(job)}")
    return result


def log_tail(job: Path, n: int = 20) -> str:
    try:
        lines = (job / "slicer.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    kept = [line for line in lines if "[trace]" not in line and "[debug]" not in line]
    return "\n".join(kept[-n:])


def _read_plates(job: Path, result: dict) -> list[PlateStats]:
    warnings = {
        p.get("id"): p.get("warning_message") or None
        for p in result.get("sliced_plates") or []
        if isinstance(p, dict)
    }
    numbered = sorted(
        (int(m[1]), path) for path in job.iterdir() if (m := PLATE_NAME.match(path.name))
    )
    if not numbered:
        raise SliceError(f"slicer reported success but wrote no G-code:\n{log_tail(job)}")
    plates = []
    for number, path in numbered:
        stats = parse_gcode(path, plate=number)
        stats.warning = warnings.get(number)
        plates.append(stats)
    return plates


def _used_from_gcode(plate: PlateStats) -> dict:
    s = plate.settings
    filaments = [f.strip().strip('"') for f in s.get("filament_settings_id", "").split(";")]
    return {
        "printer": s.get("printer_settings_id"),
        "process": s.get("print_settings_id"),
        "filaments": [f for f in filaments if f],
    }
