---
status: review
---

# creality-mcp V1 Implementation Plan

> **For agentic workers:** execute task by task, with `subagent-driven-development` or inline — whichever the operator chose at handoff. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local stdio MCP server that lets Claude list CrealityPrint presets, slice
STL/OBJ/3MF files headlessly with the official AppImage, and read back print stats.

**Architecture:** Five small modules under `creality_mcp/`: `settings` (env config),
`catalog` (read-only preset index), `overrides` (key check + flag build), `gcode` (summary
parser), `slicer` (job folder, subprocess, `result.json`). `server` registers five tools on
an `MCPServer` and runs it over stdio. The slicer gets raw system preset files and
`--key=value` override flags; the catalog never writes presets.

**Tech Stack:** Python 3.13, `uv`, `mcp==2.0.0`, `pydantic>=2.12`, `pydantic-settings`,
`pytest==9.1.1`, `pytest-asyncio==1.4.0`, `ruff`.

**Spec:** `docs/plans/2026-10-09-creality-mcp-v1-spec.md` (this plan cites facts 1–13 as
"fact N" below).

## Global Constraints

- Python `>=3.13,<3.14`; `mcp==2.0.0`; same pins as `~/repos/home-ops/pyproject.toml`.
- Ruff: `line-length = 100`, `target-version = "py313"`, rules `E F I UP B SIM RUF S`;
  tests ignore `S101 S105 S106 S603 S607`.
- Never run the AppImage without `--cli`. Success = `result.json` `return_code == 0`.
- Overrides: `--<key with _→->=<value>`, one argv element; bool → `1`/`0`.
- The slicer gets the raw leaf preset file path. Never write a flattened preset.
- Nothing prints to stdout except the MCP transport. Logging goes to stderr.
- The tools sort every list they return by name.
- No `Co-Authored-By` trailers in commits.
- Tested app version: `CrealityPrint-V7.3.0.6151-x86_64-Release.AppImage`, extracted at
  `~/Applications/CrealityPrint/squashfs-root/`.

## Review Focus

1. **Model path with spaces or non-ASCII characters** (`~/Downloads/Benchy (1).stl`): must
   slice. Test in Task 5 (fake slicer receives the path as one argv element) and Task 7
   (real slice of a copied cube named `cube (ñ) 1.stl`).
2. **A relative model path or `~`**: the slicer runs with `cwd=<job>`, so a relative path
   would break. The server expands `~` and resolves to an absolute path before the run.
   Test in Task 5.
3. **Two vendors share a selectable printer name**: `list_presets`/`slice_model` must ask
   for `vendor`, not pick one silently. Test in Task 2.
4. **Override value with `;` or a newline**: refused before the run (it would split one
   value). Test in Task 4.
5. **Slicer killed by timeout or segfault (no `result.json`)**: a clean tool error with the
   log tail, and no orphan process. Test in Task 5 with a fake slicer that sleeps.

## Risks & Rollback

- **AppImage behaviour drifts in a later release.** Integration tests (Task 7) pin the
  observed behaviour; README pins the version. Rollback: keep the tested AppImage.
- **mcp 2.0 API differs from home-ops usage.** Task 6 copies the home-ops patterns
  (`@server.tool(...)`, `Client(server)`); Task 7's stdio smoke proves the real transport.
- **Each task is one commit on `main`** (new repo, no users yet). Rollback of a task:
  `git revert <sha>`. Rollback of the install: `claude mcp remove creality`.
- The server writes only under `CREALITYPRINT_OUTPUT`; job cleanup deletes only folders
  inside it whose names match the job pattern.

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | deps, entry point `creality-mcp = "creality_mcp.server:main"`, ruff, pytest config |
| `creality_mcp/__init__.py` | empty |
| `creality_mcp/settings.py` | `Settings` (pydantic-settings), `check_install()` |
| `creality_mcp/catalog.py` | `Preset`, `Catalog` (scan, lookup, resolve, compatible) |
| `creality_mcp/overrides.py` | `build_override_flags()` |
| `creality_mcp/gcode.py` | `PlateStats`, `parse_gcode()` |
| `creality_mcp/slicer.py` | `SliceRequest`, `SliceError`, `run_slice()`, job folders |
| `creality_mcp/server.py` | `build_server()`, five tools, `main()` |
| `tests/fixtures/profiles/` | small fake vendor tree |
| `tests/fixtures/gcode/` | trimmed real G-code headers + config blocks |
| `tests/fixtures/fake_slicer.py` | stand-in for `AppRun` in unit tests |
| `tests/test_*.py` | one test file for each module, plus `test_integration.py` |
| `README.md` | install, AppImage download, `claude mcp add` |

---

### Task 1: Project scaffold and settings

**Files:**
- Create: `pyproject.toml`, `creality_mcp/__init__.py`, `creality_mcp/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces:
  - `class Settings(BaseSettings)` with fields (env prefix `CREALITYPRINT_`):
    `app: Path`, `profiles: Path | None = None`, `output: Path`, `default_printer: str =
    "Creality K2 Plus 0.4 nozzle"`, `timeout_s: int = 600`, `max_jobs: int = 50`.
    Defaults: `app = ~/Applications/CrealityPrint/squashfs-root/AppRun`,
    `output = ~/.cache/creality-mcp/jobs`. Property `profiles_dir: Path` = `profiles` or
    `app.parent / "resources" / "profiles"`. All paths `expanduser()`'d by a validator.
  - `def check_install(s: Settings) -> str | None`: `None` when `s.app` is a file and
    executable and `s.profiles_dir` is a directory; else a message naming the variable,
    e.g. `"CrealityPrint binary not found at /x/AppRun; set CREALITYPRINT_APP"`.

- [ ] **Step 1: pyproject.** Copy the shape of `~/repos/home-ops/pyproject.toml`: name
  `creality-mcp`, deps `pydantic>=2.12`, `pydantic-settings`, `mcp==2.0.0`; dev group
  `pytest==9.1.1`, `pytest-asyncio==1.4.0`, `ruff`; hatchling with
  `packages = ["creality_mcp"]`; `[project.scripts] creality-mcp =
  "creality_mcp.server:main"`; pytest `testpaths=["tests"]`, `asyncio_mode="auto"`,
  `markers = ["slicer: needs the real CrealityPrint AppImage"]`; ruff per Global
  Constraints. Run `uv sync`. Expected: `.venv` created, exit 0.
- [ ] **Step 2: failing tests** in `tests/test_settings.py`:
  - `CREALITYPRINT_APP=/tmp/x/AppRun` (monkeypatch env) → `Settings().profiles_dir ==
    Path("/tmp/x/resources/profiles")`.
  - `CREALITYPRINT_OUTPUT=~/jobs` → `Settings().output == Path.home() / "jobs"`.
  - `check_install` with `app` = a non-existent path → message contains
    `CREALITYPRINT_APP`.
  - `check_install` with an executable file in `tmp_path` and a `resources/profiles` dir
    beside it → `None`.
  - `check_install` with the binary present and no profiles dir → message contains
    `CREALITYPRINT_PROFILES`.
- [ ] **Step 3:** `uv run python -m pytest tests/test_settings.py -q` → FAIL (import error).
- [ ] **Step 4:** implement `settings.py`.
- [ ] **Step 5:** tests PASS; `uv run ruff check .` clean.
- [ ] **Step 6: commit** `feat: project scaffold and settings`.

### Task 2: Preset catalog

**Files:**
- Create: `creality_mcp/catalog.py`, `tests/fixtures/profiles/**`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass(frozen=True) class Preset: vendor: str; kind: str; name: str; path: Path;
    data: dict` (`kind` in `{"machine","process","filament"}`). `name` is `data["name"]`,
    falling back to the file stem only when the key is absent: 87 real presets have a
    name that differs from the file name (`Bambu Support For PA/PET @BBL A1`).
  - `class CatalogError(Exception)`.
  - `class Catalog`:
    - `Catalog.load(profiles_dir: Path) -> Catalog`: scan `<profiles_dir>/<Vendor>/
      {machine,process,filament}/**/*.json` recursively, sorted paths. Skip a file that is
      not valid JSON or whose `type` is not one of the three kinds (log to stderr).
    - `selectable(kind) -> list[Preset]`: `data.get("instantiation") == "true"`, sorted
      by `(name, vendor)`. A name repeated inside one vendor keeps the first path; the
      catalog logs the repeat once.
    - `find(kind, name, vendor: str | None = None) -> Preset`: selectable preset by name.
      Not found → `CatalogError("no <kind> preset named '<name>'")` plus up to 5 close
      names (`difflib.get_close_matches(name, names, n=5, cutoff=0.6)`). Found in two or
      more vendors and `vendor is None` → `CatalogError` that lists the vendors.
    - `resolve(preset: Preset) -> dict`: walk `inherits`; look each parent up over ALL
      presets (not only selectable), first in the vendor of the node that it resolves (so
      RatRig → BBL `fdm_process_bbl_0.20` → its parents come from BBL), then in the other
      vendors in sorted order. Merge root first, leaf last; drop `inherits`. Missing parent
      → `CatalogError` naming it. Cycle → `CatalogError`. Cache results by
      `(vendor, kind, name)`.
    - `defaults(machine: Preset) -> tuple[str | None, list[str]]`: from
      `resolve(machine)`: `default_print_profile` and `default_filament_profile`, each
      normalised from `str` or `list` (a `str` becomes `[s]`; a process list takes its
      first item). Real data: K2 Plus gives `['Hyper PLA @Creality K2 Plus 0.4 nozzle']`
      (a list); the X1C leaf has no defaults of its own and inherits them.
    - `compatible(printer: Preset, kind: str) -> list[Preset]`: selectable presets of
      `printer.vendor` and `kind`, judged on **resolved** data (about 110 real process
      leaves inherit `compatible_printers` from a parent): `printer.name in
      resolved["compatible_printers"]`, plus presets whose resolved list is empty/missing
      AND whose resolved `compatible_printers_condition` is empty/missing. Sorted; the
      machine's default (from `defaults()`) first when present.
    - `stats() -> dict`: counts for the start log: presets per kind, `condition_only`
      (dropped), `unrestricted`.

- [ ] **Step 1: fixtures.** Build `tests/fixtures/profiles/` with two vendors:
  - `VendA/machine/fdm_machine_common.json` (`type: machine`, `instantiation: "false"`,
    `nozzle_diameter: ["0.4"]`, `bed_temp: "60"`);
    `VendA/machine/A1 0.4 nozzle.json` (`inherits: fdm_machine_common`,
    `instantiation: "true"`, `printer_model: "A1"`, `default_print_profile:
    "0.20mm A @A1"`, `default_filament_profile: "PLA @A1"`);
    `VendA/machine/template gcode.json` (no `type` key → skipped).
  - `VendA/process/fdm_process_common.json` (`layer_height: "0.2"`, `wall_loops: "2"`);
    `VendA/process/0.20mm A @A1.json` (`inherits: fdm_process_common`,
    `compatible_printers: ["A1 0.4 nozzle"]`, `wall_loops: "3"`);
    `VendA/process/0.12mm A @A1.json` (same printer list, `layer_height: "0.12"`);
    `VendA/process/cond only.json` (`compatible_printers: []`,
    `compatible_printers_condition: "nozzle_diameter[0]==0.4"`);
    `VendA/process/any printer.json` (no list, no condition).
  - `VendA/filament/sub/PLA @A1.json` (in a subfolder; `compatible_printers:
    ["A1 0.4 nozzle"]`, `inherits: fdm_filament_pla`) and
    `VendA/filament/fdm_filament_pla.json` (`nozzle_temperature: ["210"]`).
  - `VendB/process/fdm_process_common.json` with `layer_height: "0.3"` (same base name,
    different value); `VendB/machine/A1 0.4 nozzle.json` (same selectable name as VendA);
    `VendB/process/cross @B.json` with `inherits: "0.20mm A @A1"` (parent only in VendA).
  - `VendA/process/0.16mm A @A1.json` with `inherits: "0.20mm A @A1"` and NO
    `compatible_printers` of its own (it inherits the list).
  - `VendA/process/extra/0.12mm A @A1.json`: a second file with the same `name` as
    `0.12mm A @A1` and `layer_height: "0.99"` (repeat inside one vendor; sorted path order
    keeps `VendA/process/0.12mm A @A1.json`).
  - A1's `default_filament_profile` is a list `["PLA @A1"]`; its
    `default_print_profile` is the string `"0.20mm A @A1"`.
  - Every fixture file has `"type"` and `"name"`. Selectable ones have
    `"instantiation": "true"`; base ones (`fdm_*`) have `"instantiation": "false"`, or the
    scan skips them and `resolve()` fails.
- [ ] **Step 2: failing tests** (`tests/test_catalog.py`, `cat = Catalog.load(FIXTURES)`):
  - `[p.name for p in cat.selectable("process")]` == `["0.12mm A @A1", "0.16mm A @A1",
    "0.20mm A @A1", "any printer", "cond only", "cross @B"]`, and the `0.12mm A @A1` entry
    resolves to `layer_height == "0.12"` (not the repeat's `0.99`).
  - `cat.find("machine", "A1 0.4 nozzle")` raises `CatalogError` whose message contains
    `VendA` and `VendB`; with `vendor="VendA"` returns the VendA preset.
  - `cat.find("process", "0.20mm A @A")` raises with `0.20mm A @A1` in the message.
  - `cat.resolve(cat.find("process", "0.20mm A @A1"))` → `layer_height == "0.2"` (VendA
    parent, not VendB's `0.3`), `wall_loops == "3"`, no `inherits` key.
  - `cat.resolve(cat.find("process", "cross @B"))` → `wall_loops == "3"` and
    `layer_height == "0.2"` (cross-vendor parent; its own parent resolves in VendA).
  - `cat.defaults(a1) == ("0.20mm A @A1", ["PLA @A1"])`.
  - `[p.name for p in cat.compatible(a1, "process")]` with `a1 = cat.find("machine",
    "A1 0.4 nozzle", "VendA")` == `["0.20mm A @A1", "0.12mm A @A1", "0.16mm A @A1",
    "any printer"]` (default first; `0.16mm` via its inherited list; `cond only` dropped).
  - `cat.compatible(a1, "filament")[0].name == "PLA @A1"` (found in the subfolder).
  - `cat.stats()["condition_only"] == 1`.
  - Template file is not in any list.
- [ ] **Step 3:** run → FAIL. **Step 4:** implement. **Step 5:** run → PASS; ruff clean.
- [ ] **Step 6: real-data check** (no test file; record the output in the commit body):
  `uv run python -c "from creality_mcp.catalog import Catalog; from pathlib import Path;
  c=Catalog.load(Path('~/Applications/CrealityPrint/squashfs-root/resources/profiles').expanduser());
  m=c.find('machine','Creality K2 Plus 0.4 nozzle');
  print(len(c.compatible(m,'process')), len(c.compatible(m,'filament')),
  c.compatible(m,'process')[0].name, c.stats())"`. Expected: `10 101 0.20mm Standard
  @Creality K2 Plus 0.4 nozzle` (spec §Preset catalog); stats show `condition_only` 7 and `unrestricted` 1.
  If the counts differ, stop and report the numbers; do not tune the rule to match.
- [ ] **Step 7: commit** `feat: preset catalog`.

### Task 3: G-code summary parser

**Files:**
- Create: `creality_mcp/gcode.py`, `tests/fixtures/gcode/{creality_k2.gcode,bbl_x1c.gcode,two_filament.gcode}`
- Test: `tests/test_gcode.py`

**Interfaces:**
- Produces:
  - `@dataclass class PlateStats: plate: int; gcode_path: str; print_time_s: int | None;
    print_time_text: str | None; filament_g: list[float] | None; filament_mm:
    list[float] | None; layers: int | None; settings: dict[str, str]; missing:
    list[str]; warning: str | None = None` (`missing` holds the names of `None` stat
    fields). `filament_g` comes from `; filament used [g] = 17.24, 21.53` (one value per
    filament), NOT from `total filament used [g]` (one total). `filament_mm` from
    `; filament used [mm] = ...`. `settings` keeps `printer_model`,
    `printer_settings_id`, `print_settings_id`, `filament_settings_id`, `layer_height`
    from the config block.
  - `def parse_gcode(path: Path, plate: int = 1) -> PlateStats`.
  - `def parse_duration(text: str) -> int | None`: `"1d 2h 3m 4s"` → seconds; any subset
    of units; `"22m 25s"` → `1345`; garbage → `None`.

- [ ] **Step 1: fixtures from real slices.** Slice into `/tmp` with the AppImage. The
  commands are in spec facts 2 and 6. The slices: (a) K2 Plus cube; (b) BBL X1C cube (`BBL/machine/Bambu Lab
  X1 Carbon 0.4 nozzle.json`, its `default_print_profile`, its
  `default_filament_profile`); (c) two cubes, two K2 Plus filaments,
  `--load-filament-ids "1,2"`. For each, keep only the comment lines: `grep '^;'
  plate_1.gcode > tests/fixtures/gcode/<name>.gcode`. Check each fixture is under 200 KB.
- [ ] **Step 2: failing tests:**
  - `creality_k2.gcode`: `print_time_text` is the string after `= ` on the
    `estimated printing time (normal mode)` line; `print_time_s == parse_duration(it)`;
    `filament_g` is a 1-item list > 0; `layers` > 0; `settings["printer_model"] ==
    "Creality K2 Plus"`; `missing == []`.
  - `bbl_x1c.gcode`: `print_time_s` is not `None` (from `total estimated time`);
    `filament_g` may be `None` and then `"filament_g" in missing`.
  - `two_filament.gcode`: `len(filament_mm) == 2`, `len(filament_g) == 2`, all > 0.
  - `parse_duration("1h 2m 3s") == 3723`; `parse_duration("45s") == 45`;
    `parse_duration("n/a") is None`.
  - An empty file → all stats `None`, no exception.
  - Write the exact expected numbers from the fixtures into the asserts (read them from
    the fixture once, then hard-code them).
- [ ] **Step 3:** FAIL. **Step 4:** implement: read line by line; header regexes
  `^; (?P<k>[^=:]+?)\s*[=:]\s*(?P<v>.*)$`; the BBL line `; model printing time: X;
  total estimated time: Y` needs its own regex (two pairs on one line); list values split
  on `,`. **Step 5:** PASS; ruff clean.
- [ ] **Step 6: commit** `feat: G-code summary parser`.

### Task 4: Override flags

**Files:**
- Create: `creality_mcp/overrides.py`
- Test: `tests/test_overrides.py`

**Interfaces:**
- Consumes: `Catalog.resolve()` output (a `dict` of known keys) from Task 2.
- Produces:
  - `class OverrideError(ValueError)`.
  - `def build_override_flags(overrides: dict[str, str | int | float | bool],
    known_keys: set[str]) -> list[str]`: for each key in sorted order:
    unknown → `OverrideError("unknown setting 'layer_hieght'; close: layer_height")`;
    value `bool` → `"1"`/`"0"`; else `str(value)`; a value containing `;`, `\n` or `\r`
    → `OverrideError`; returns `[f"--{key.replace('_','-')}={value}", ...]`.

- [ ] **Step 1: failing tests:**
  - `build_override_flags({"layer_height": 0.28}, {"layer_height"}) ==
    ["--layer-height=0.28"]`.
  - `{"enable_support": True}` → `["--enable-support=1"]`; `False` → `=0`.
  - `{"sparse_infill_density": "40%"}` → `["--sparse-infill-density=40%"]`.
  - Two keys → sorted order.
  - `{"layer_hieght": 0.2}` with known `{"layer_height"}` → `OverrideError` whose message
    contains `layer_height`.
  - `{"layer_height": "0.2;0.3"}` and `"0.2\n"` → `OverrideError`.
  - `{}` → `[]`.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS; ruff clean.
- [ ] **Step 5: commit** `feat: override flags`.

### Task 5: Slicer runner

**Files:**
- Create: `creality_mcp/slicer.py`, `tests/fixtures/fake_slicer.py`
- Test: `tests/test_slicer.py`

**Interfaces:**
- Consumes: `Settings` (Task 1), `Catalog`, `Preset`, `CatalogError` (Task 2),
  `parse_gcode`, `PlateStats` (Task 3), `build_override_flags`, `OverrideError` (Task 4).
- Produces:
  - `class SliceError(Exception)` (message is safe to show Claude).
  - `@dataclass class SliceRequest: models: list[str]; printer: str | None = None;
    printer_vendor: str | None = None; process: str | None = None; filaments: list[str]
    | None = None; filament_ids: list[int] | None = None; overrides: dict | None = None`.
  - `@dataclass class SliceResult: job_dir: str; plates: list[PlateStats]; used: dict;
    missing_stats: list[str]`.
  - `def run_slice(req: SliceRequest, settings: Settings, catalog: Catalog) ->
    SliceResult`. Raises `SliceError` for every failure (wraps `CatalogError` and
    `OverrideError`).
  - Helpers (tested directly): `new_job_dir(output: Path, max_jobs: int) -> Path` (name
    `YYYYmmddTHHMMSSZ-<6 hex>`; deletes the oldest folders matching that pattern beyond
    `max_jobs - 1` before creating); `build_argv(...) -> list[str]`;
    `read_result(job: Path, exit_code: int) -> dict`; `log_tail(job: Path, n: int = 20)
    -> str` (skips lines containing `[trace]` or `[debug]`).

Behaviour (spec §Slice job, steps 1–7):
1. Models: `Path(m).expanduser().resolve()`; must exist; suffix (lower) in
   `.stl .obj .3mf`; all 3MF or none; at most one 3MF. Else `SliceError`.
2. 3MF with `printer`, `process` or `filaments` set → `SliceError("3MF uses its stored
   printer and presets in V1; the server allows only overrides")`.
3. STL/OBJ: `printer = catalog.find("machine", req.printer or settings.default_printer,
   req.printer_vendor)`; process from `req.process` or the machine's
   default process from `catalog.defaults(printer)`; filaments from `req.filaments` or
   the default filament list from `catalog.defaults(printer)`; each must be in `catalog.compatible(printer, kind)` by
   name, else `SliceError` that says to call `list_presets`. `filament_ids` given →
   `len == len(models)` and each in `1..len(filaments)`.
4. Known override keys: STL/OBJ → `catalog.resolve(process).keys()`; 3MF → union of
   `resolve()` keys over all selectable process presets (compute once, cache on the
   catalog instance).
5. argv: `[app, "--cli", "--slice", "0", "--need-gcode-file", "--outputdir", job]` +
   STL/OBJ: `["--load-settings", f"{machine.path};{process.path}", "--load-filaments",
   ";".join(f.path)]` + (`["--load-filament-ids", ",".join(ids)]` if ids) + override
   flags + model paths.
6. `proc = subprocess.Popen(argv, cwd=job, stdout=log, stderr=subprocess.STDOUT,
   start_new_session=True)  # noqa: S603 - argv list, no shell; paths checked in step 1`,
   then `proc.communicate(timeout=settings.timeout_s)`. On `TimeoutExpired`:
   `os.killpg(proc.pid, signal.SIGKILL)`, then `proc.wait()` (reap it: a zombie still
   passes `os.kill(pid, 0)`), then `SliceError("slicer timed out after N s")`. `AppRun`
   ends in `exec`, so the process group holds the slicer.
7. `read_result`: no `result.json` → `SliceError(f"slicer failed with no result (exit
   {code}):\n{log_tail}")`; `return_code != 0` → `SliceError(f"{error_string}
   (return_code {rc}):\n{log_tail}")`.
8. Plates: every `job/plate_*.gcode` sorted by number → `parse_gcode(path, plate=N)`.
   Warnings: set `PlateStats.warning` from the `sliced_plates` entry whose `id == N`
   (empty string → `None`). `missing_stats` = sorted union of every plate's `missing`.
   `used` has the same keys for both inputs: `{printer: str, process: str, filaments:
   list[str], overrides: dict}`. STL/OBJ → the preset names. 3MF → from plate 1's
   `settings`: `printer = printer_settings_id`, `process = print_settings_id`,
   `filaments = filament_settings_id` split on `;` with the `"` quotes stripped (real
   value: `"A";"B";"C"`).

`tests/fixtures/fake_slicer.py` (made executable; first line `#!/usr/bin/env python3`):
reads `FAKE_MODE` from env and `--outputdir` from argv. Modes: `ok` → writes
`result.json` (`return_code 0`, one plate) and copies `tests/fixtures/gcode/creality_k2.gcode`
to `plate_1.gcode`, and writes `argv.json` (its `sys.argv[1:]`); `rc17` → `result.json`
with `return_code -17`, `error_string "The selected printer is not compatible"`;
`noresult` → prints `[error] boom` and exits 254; `sleep` → sleeps 30 s.

- [ ] **Step 1: failing tests** (`settings` fixture: `app` = fake slicer,
  `profiles` = Task 2 fixture tree, `output = tmp_path/"jobs"`, `timeout_s = 2`,
  `default_printer = "A1 0.4 nozzle"`; `printer_vendor="VendA"` in requests):
  - `ok`: `run_slice(SliceRequest(models=[str(cube)]))` returns 1 plate, `used["process"]
    == "0.20mm A @A1"`, `used["filaments"] == ["PLA @A1"]`; `argv.json` holds
    `--load-settings` with both absolute fixture paths joined by `;`.
  - Review Focus 1: model at `tmp_path/"cube (ñ) 1.stl"` → appears in `argv.json` as one
    element, unchanged.
  - Review Focus 2: `models=["cube.stl"]` with `monkeypatch.chdir(tmp_path)` → the argv
    element is absolute.
  - Overrides `{"layer_height": 0.28}` → argv contains `--layer-height=0.28`.
  - `rc17` → `SliceError` with `return_code -17` in the message.
  - Review Focus 5: `noresult` → `SliceError` containing `exit 254` and `boom`; `sleep`
    → `SliceError` containing `timed out` within ~3 s. The fake writes its pid to
    `<outputdir>/pid` before it sleeps; after the error, `os.kill(pid, 0)` raises
    `ProcessLookupError` (no orphan).
  - 3MF + `printer="A1 0.4 nozzle"` → `SliceError` containing `3MF`.
  - STL + 3MF mixed → `SliceError`. Missing model → `SliceError` with the path.
  - Process `"any printer"` accepted; process `"cond only"` → `SliceError` containing
    `list_presets`.
  - `filament_ids=[1, 2]` with one filament → `SliceError`.
  - `new_job_dir` with `max_jobs=3` after creating 5 job-pattern folders and one folder
    named `keep-me` → 2 job folders + the new one remain; `keep-me` remains.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS; ruff clean.
- [ ] **Step 5: commit** `feat: slicer runner`.

### Task 6: MCP server and tools

**Files:**
- Create: `creality_mcp/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `def build_server(settings: Settings) -> MCPServer`: `MCPServer("creality",
    instructions=...)` (instructions: 4 lines: what the server does, "call list_presets
    before choosing presets", "overrides use preset keys like layer_height", "3MF keeps
    its own presets"). Loads the `Catalog` once when `check_install` passes; logs
    `catalog.stats()` to stderr.
  - Tools (pattern from `~/repos/home-ops/home_ops/mcp/tools.py:111-135`:
    `@server.tool(description=..., annotations=ToolAnnotations(...))`, raise
    `ToolError(str(e))` from `mcp.server.mcpserver.exceptions`):
    `list_printers(vendor: str | None = None, query: str | None = None) -> list[dict]`;
    `list_presets(printer: str, kind: Literal["process","filament"], vendor: str | None =
    None, query: str | None = None) -> list[dict]`;
    `get_preset(kind: Literal["machine","process","filament"], name: str, vendor: str |
    None = None, keys: list[str] | None = None) -> dict`;
    `slice_model(models: list[str], printer: str | None = None, vendor: str | None = None,
    process: str | None = None, filaments: list[str] | None = None, filament_ids:
    list[int] | None = None, overrides: dict[str, str | int | float | bool] | None =
    None) -> dict`; `read_gcode_summary(path: str) -> dict`.
    Read tools: `read_only_hint=True`; `slice_model`: `read_only_hint=False,
    destructive_hint=False`; all `open_world_hint=False`.
  - `list_printers` item: `{"name", "vendor", "model": data.get("printer_model"),
    "nozzle": first of data.get("nozzle_diameter") from resolve()}`.
  - When `check_install` fails, every tool raises `ToolError(<that message>)`.
  - `def main() -> None`: configure `logging` to stderr, `build_server(Settings()).run()`.

- [ ] **Step 1: failing tests** (in-process `async with Client(server) as client`, as in
  `~/repos/home-ops/tests/test_mcp_tools.py`; reuse its `payload()` helper shape;
  settings point at the Task 2 fixtures and the Task 5 fake slicer):
  - Tool names == `{"list_printers","list_presets","get_preset","slice_model",
    "read_gcode_summary"}`.
  - `list_printers(query="a1")` → 2 items (VendA, VendB), sorted by `(name, vendor)`.
  - `list_presets(printer="A1 0.4 nozzle", kind="process")` → `is_error` and the text
    names both vendors (Review Focus 3); with `vendor="VendA"` → first item
    `0.20mm A @A1`.
  - `get_preset("process","0.20mm A @A1", vendor="VendA", keys=["layer_height"])` ==
    `{"layer_height": "0.2"}`.
  - `get_preset(..., keys=["layer_hieght"])` → `is_error`; text names `layer_height` as a
    close match (unknown keys are an error, not silently dropped).
  - `slice_model(models=[<tmp cube.stl that exists>], vendor="VendA")` with
    `FAKE_MODE=ok` → `plates[0]["print_time_s"]` is an int. (The call needs `vendor`: the
    fixture default printer `A1 0.4 nozzle` exists in VendA and VendB.)
  - Same call with `FAKE_MODE=rc17` → `is_error` true; text contains `-17`.
  - `read_gcode_summary` on the fixture → `layers` > 0.
  - Server built with a missing app → `list_printers` → `is_error`, text contains
    `CREALITYPRINT_APP`.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS; ruff clean.
- [ ] **Step 5: commit** `feat: MCP server with five tools`.

### Task 7: Real-slicer integration, stdio smoke, README, install

**Files:**
- Create: `tests/test_integration.py`, `README.md`
- Modify: none

**Interfaces:**
- Consumes: `run_slice`, `build_server`, `main` entry point.

- [ ] **Step 1: integration tests** (`pytestmark = pytest.mark.slicer`; skip the module
  when `Settings().app` is not executable). Cube: copy
  `tests/fixtures/cube.stl` — add it in this task from
  `~/repos/crealityprint/tests/data/test_stl/ASCII/20mmbox-LF.stl` (ASCII, 12 triangles).
  - K2 Plus defaults → `used["process"] == "0.20mm Standard @Creality K2 Plus 0.4
    nozzle"`, `used["filaments"] == ["Hyper PLA @Creality K2 Plus 0.4 nozzle"]`,
    `print_time_s > 0`.
  - Overrides `{"layer_height": 0.28, "enable_arc_fitting": False}` → G-code config has
    `layer_height = 0.28` and `enable_arc_fitting = 0`.
  - Cube copied to `cube (ñ) 1.stl` → slices (Review Focus 1).
  - Two cubes, filaments `["Hyper PLA @Creality K2 Plus 0.4 nozzle", "CR-PLA @Creality
    K2 Plus 0.4 nozzle"]`, `filament_ids=[1, 2]` → both `filament_mm` values > 0.
  - BBL X1C cube (printer `Bambu Lab X1 Carbon 0.4 nozzle`) → `print_time_s > 0`.
  - 3MF: `~/repos/crealityprint/tests/engine_test/baseline/simple-box.3mf` copied into
    `tests/fixtures/`, override `layer_height` 0.28 → G-code `layer_height = 0.28`.
  - Unknown printer → `SliceError`.
  Run: `uv run python -m pytest -m slicer -q`. Expected: all pass.
- [ ] **Step 2: stdio smoke** (in `test_integration.py`):
  `params = StdioServerParameters(command="uv", args=["run", "--directory", REPO,
  "creality-mcp"], env={"CREALITYPRINT_OUTPUT": str(tmp_path / "jobs")})` (the stdio
  client passes only a safe-list env, so set it explicitly). Open with
  `errlog = open(tmp_path / "err.log", "w")` and
  `async with Client(stdio_client(params, errlog=errlog)) as c:` (checked against mcp
  2.0.0). Calls: `list_printers(query="K2 Plus")` → 4 items (0.2/0.4/0.6/0.8 nozzle);
  `slice_model(models=[cube])` → `plates[0]["print_time_s"] > 0`. Then assert
  `err.log` has no `Failed to parse`: a stray stdout print only logs there, it does not
  fail the call.
- [ ] **Step 3: README** — what it is; tested AppImage version; download:
  `gh release download v7.3.0 -R CrealityOfficial/CrealityPrint -p
  'CrealityPrint-V7.3.0.6151-x86_64-Release.AppImage'`, then `--appimage-extract` into
  `~/Applications/CrealityPrint/`; env variables table (copy from the spec); install:
  `claude mcp add creality -- uv --directory ~/repos/creality-mcp run creality-mcp`;
  example prompts ("slice ~/Downloads/x.stl for my K2 Plus at 0.28 mm, 20% infill");
  limits (spec §Scope Out).
- [ ] **Step 4: full gate:** `uv run python -m pytest -q` (unit + integration) and
  `uv run ruff check .`. Record exact counts in the commit body.
- [ ] **Step 5: commit** `test: real-slicer integration and stdio smoke; README`.
- [ ] **Step 6: install and live check.** `claude mcp add creality -- uv --directory
  ~/repos/creality-mcp run creality-mcp`; `claude mcp list` shows `creality` connected.
  Start a new Claude Code session. Ask "list K2 printers". Then ask "slice the test cube
  for a K2 Plus at 0.28 mm": the answer gives a time and grams. Set the spec status to `done`.
