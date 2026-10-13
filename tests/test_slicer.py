import json
import time
from pathlib import Path

import pytest

from creality_mcp.catalog import Catalog
from creality_mcp.gcode import parse_gcode
from creality_mcp.settings import Settings
from creality_mcp.slicer import (
    SliceError,
    SliceRequest,
    _used_from_gcode,
    log_tail,
    new_job_dir,
    run_slice,
)

FIXTURES = Path(__file__).parent / "fixtures"
PROFILES = FIXTURES / "profiles"


@pytest.fixture(scope="module")
def catalog():
    return Catalog.load(PROFILES)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        app=FIXTURES / "fake_slicer.py",
        profiles=PROFILES,
        output=tmp_path / "jobs",
        timeout_s=2,
        default_printer="A1 0.4 nozzle",
    )


@pytest.fixture
def cube(tmp_path):
    path = tmp_path / "cube.stl"
    path.write_text("solid cube\nendsolid cube\n")
    return path


def req(*models, **kw):
    return SliceRequest(models=[str(m) for m in models], printer_vendor="VendA", **kw)


def argv_of(result):
    return json.loads((Path(result.job_dir) / "argv.json").read_text())


def test_ok_defaults(settings, catalog, cube, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "ok")
    result = run_slice(req(cube), settings, catalog)
    assert len(result.plates) == 1
    assert result.plates[0].print_time_s == 750
    assert result.plates[0].warning is None
    assert result.used == {
        "printer": "A1 0.4 nozzle",
        "process": "0.20mm A @A1",
        "filaments": ["PLA @A1"],
        "overrides": {},
    }
    assert result.missing_stats == []
    argv = argv_of(result)
    machine = PROFILES / "VendA" / "machine" / "A1 0.4 nozzle.json"
    process = PROFILES / "VendA" / "process" / "0.20mm A @A1.json"
    assert argv[argv.index("--load-settings") + 1] == f"{machine};{process}"
    assert argv[:6] == ["--cli", "--slice", "0", "--need-gcode-file", "--outputdir", result.job_dir]
    assert argv[-1] == str(cube)


def test_path_with_space_and_non_ascii(settings, catalog, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "ok")
    model = tmp_path / "cube (ñ) 1.stl"
    model.write_text("solid\n")
    assert argv_of(run_slice(req(model), settings, catalog))[-1] == str(model)


def test_relative_path_made_absolute(settings, catalog, cube, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "ok")
    monkeypatch.chdir(tmp_path)
    assert argv_of(run_slice(req("cube.stl"), settings, catalog))[-1] == str(cube)


def test_overrides_reach_argv(settings, catalog, cube, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "ok")
    result = run_slice(req(cube, overrides={"layer_height": 0.28}), settings, catalog)
    assert "--layer-height=0.28" in argv_of(result)
    assert result.used["overrides"] == {"layer_height": 0.28}


def test_unknown_override(settings, catalog, cube, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "ok")
    with pytest.raises(SliceError, match="layer_height"):
        run_slice(req(cube, overrides={"layer_hieght": 0.28}), settings, catalog)


def test_return_code_error(settings, catalog, cube, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "rc17")
    with pytest.raises(SliceError, match="return_code -17"):
        run_slice(req(cube), settings, catalog)


def test_no_result(settings, catalog, cube, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "noresult")
    with pytest.raises(SliceError) as err:
        run_slice(req(cube), settings, catalog)
    assert "exit 254" in str(err.value)
    assert "boom" in str(err.value)
    assert "[trace]" not in str(err.value)


def test_timeout_kills_slicer(settings, catalog, cube, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "sleep")
    start = time.monotonic()
    with pytest.raises(SliceError, match="timed out"):
        run_slice(req(cube), settings, catalog)
    assert time.monotonic() - start < 4
    [job] = settings.output.iterdir()
    for name in ("pid", "child_pid"):
        assert not _running(int((job / name).read_text()))


def _running(pid: int) -> bool:
    """False once the process is gone or a zombie (killed; its new parent reaps it later)."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return state != "Z"


def test_3mf_refuses_presets(settings, catalog, tmp_path):
    model = tmp_path / "box.3mf"
    model.write_bytes(b"PK")
    with pytest.raises(SliceError, match="3MF"):
        run_slice(req(model, printer="A1 0.4 nozzle"), settings, catalog)


def test_3mf_uses_used_from_gcode(settings, catalog, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "ok")
    model = tmp_path / "box.3mf"
    model.write_bytes(b"PK")
    result = run_slice(
        SliceRequest(models=[str(model)], overrides={"layer_height": 0.28}), settings, catalog
    )
    assert result.used == {
        "printer": "Creality K2 Plus 0.4 nozzle",
        "process": "0.20mm Standard @Creality K2 Plus 0.4 nozzle",
        "filaments": ["Hyper PLA @Creality K2 Plus 0.4 nozzle"],
        "overrides": {"layer_height": 0.28},
    }
    argv = argv_of(result)
    assert "--load-settings" not in argv
    assert "--layer-height=0.28" in argv


def test_mixed_and_missing_models(settings, catalog, cube, tmp_path):
    three = tmp_path / "box.3mf"
    three.write_bytes(b"PK")
    with pytest.raises(SliceError):
        run_slice(req(cube, three), settings, catalog)
    missing = tmp_path / "gone.stl"
    with pytest.raises(SliceError, match=str(missing)):
        run_slice(req(missing), settings, catalog)
    bad = tmp_path / "model.step"
    bad.write_text("x")
    with pytest.raises(SliceError):
        run_slice(req(bad), settings, catalog)


def test_process_compatibility(settings, catalog, cube, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "ok")
    result = run_slice(req(cube, process="any printer"), settings, catalog)
    assert result.used["process"] == "any printer"
    with pytest.raises(SliceError, match="list_presets"):
        run_slice(req(cube, process="cond only"), settings, catalog)


def test_filament_ids_checked(settings, catalog, cube):
    with pytest.raises(SliceError):
        run_slice(req(cube, filament_ids=[1, 2]), settings, catalog)
    with pytest.raises(SliceError):
        run_slice(req(cube, cube, filament_ids=[1, 2]), settings, catalog)


def test_new_job_dir_prunes_only_job_folders(tmp_path):
    for i in range(5):
        (tmp_path / f"2026010{i}T000000Z-abcde{i}").mkdir()
    (tmp_path / "keep-me").mkdir()
    job = new_job_dir(tmp_path, max_jobs=3)
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["20260103T000000Z-abcde3", "20260104T000000Z-abcde4", job.name, "keep-me"]


def test_log_tail_skips_noise(tmp_path):
    lines = [f"line {i}" for i in range(30)] + ["[debug] x", "[trace] y"]
    (tmp_path / "slicer.log").write_text("\n".join(lines) + "\n")
    tail = log_tail(tmp_path, n=3)
    assert tail == "line 27\nline 28\nline 29"


def test_plates_in_numeric_order_with_warnings(settings, catalog, cube, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "warn")
    plates = run_slice(req(cube), settings, catalog).plates
    assert [(p.plate, p.warning) for p in plates] == [(2, None), (10, "overhang")]


def test_success_without_gcode(settings, catalog, cube, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "nogcode")
    with pytest.raises(SliceError, match="no G-code"):
        run_slice(req(cube), settings, catalog)


def test_nul_in_inputs(settings, catalog, cube):
    with pytest.raises(SliceError):
        run_slice(req(cube, overrides={"layer_height": "0.2\x00"}), settings, catalog)
    with pytest.raises(SliceError, match="NUL"):
        run_slice(req(f"{cube}\x00"), settings, catalog)


def test_new_job_dir_leaves_symlinks(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    out = tmp_path / "jobs"
    out.mkdir()
    (out / "20260101T000000Z-abcdef").symlink_to(target)
    new_job_dir(out, max_jobs=1)
    assert (out / "20260101T000000Z-abcdef").is_symlink()
    assert target.is_dir()


def test_job_dir_error_is_slice_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(SliceError, match="job folder"):
        new_job_dir(blocker / "jobs", max_jobs=3)


def test_used_from_gcode_without_ids():
    stats = parse_gcode(FIXTURES / "gcode" / "creality_k2.gcode")
    stats.settings = {}
    assert _used_from_gcode(stats) == {
        "printer": "unknown",
        "process": "unknown",
        "filaments": ["unknown"],
    }
