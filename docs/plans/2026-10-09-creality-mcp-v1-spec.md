---
status: draft
---

# creality-mcp V1: headless slicing for Claude

## Goal

Claude can slice a 3D model with CrealityPrint and report the result. Claude picks a
printer, a process preset and filament presets, changes settings when asked, and reads
back print time, filament use and warnings. No CrealityPrint window opens.

V1.5 (Claude drives the open CrealityPrint app on mandalore) is a separate spec. See
§V1.5 boundary.

## Facts this spec stands on (spike + audit, 2026-10-09)

All runs used the official AppImage `CrealityPrint-V7.3.0.6151-x86_64-Release.AppImage`,
extracted to `~/Applications/CrealityPrint/squashfs-root/`. The shell had no `DISPLAY`
and no `WAYLAND_DISPLAY`. Source references are in the fork `~/repos/crealityprint`.

1. `AppRun --cli` starts the command-line mode. Without `--cli` the app opens the GUI and
   hangs a headless caller (`src/CrealityPrint.cpp:152-160`, `:287-290`).
2. `AppRun --cli --slice 0 --need-gcode-file --outputdir D --load-settings "M;P"
   --load-filaments "F" model.stl` slices. It writes `D/plate_N.gcode` and
   `D/result.json`. A 20 mm cube took about 1 s. The CLI wrote nothing outside `D`.
3. `result.json` holds `return_code`, `error_string` and `sliced_plates[]` (`id`,
   `warning_message`, `triangle_count`, ...). Success is `return_code: 0`. The exit code
   is not the signal (0, 239, 250, 253, 254 seen). Seen codes: `-2` invalid parameters,
   `-3` input file not found, `-6` the CLI cannot parse the model, `-17` printer not compatible
   with process, `-24` unsupported 3MF version.
4. Some failures write **no** `result.json`: an unknown override flag ("CLI parameter
   parsing failed", exit 254), and a segfault (exit 139, seen on an old 3MF with
   `--allow-newer-file`).
5. **Raw system preset files work as they are.** Pass the leaf files from
   `resources/profiles/<Vendor>/{machine,process,filament}/` to `--load-settings` and
   `--load-filaments`. The CLI resolves their parents. Checked for Creality K1C, K2 Plus
   and BBL X1C.
6. **Overrides are CLI flags `--<key with - for _>=<value>`.** The parser splits on `=`
   (`src/libslic3r/Config.cpp:1850-1890`). Checked: `--layer-height=0.28`,
   `--sparse-infill-pattern=gyroid`, `--wall-loops=4`, `--enable-support=1`,
   `--enable-arc-fitting=0` (a preset `1` set to `0`); the G-code config shows each value.
   This build turns off the `--no-` prefix. A boolean flag without `=` takes no value:
   `--enable-support 1` reads `1` as an input file (`-3`). An unknown flag, or
   `--layer_height` with underscores, fails with no `result.json` (fact 4).
7. A flattened user preset without `inherits` fails with `-17`. The CLI takes the
   machine's system name from `inherits` (`src/slic3r/CLI/SliceCommand.cpp:1410-1415`,
   `:1579-1587`). Fact 5 makes flattening unnecessary, so V1 does not flatten.
8. G-code summary lines vary with the printer:
   - Creality: `; estimated printing time (normal mode) = 22m 25s`,
     `; total filament used [g] = 3.64`, `; filament used [mm] = 1210.18`.
   - BBL X1C: no `estimated printing time (normal mode)` and no `[g]` keys. The header
     has `; model printing time: 10m 22s; total estimated time: ...`.
   - All: `; total layer number: 125` (colon, not `=`). With 2 filaments, values are
     lists: `filament used [mm] = 1454.20, 0.00`.
   - All: the config block `; key = value` (`layer_height`, `print_settings_id`, ...).
9. The CLI puts several STL/OBJ models on plate 1. `--slice 2` on one STL still writes
   `plate_1.gcode`.
10. With 2 filaments and no `--load-filament-ids`, every object prints with filament 1.
    With no filament, the slice "succeeds" with 0.00 g.
11. 3MF input: the CLI uses the settings stored in the 3MF. Overrides work
    (`--layer-height 0.28` on `simple-box.3mf`: 15m 43s → 11m 25s). `--load-settings`
    with a 3MF fails with `-2`.
12. Profiles: 36 vendor folders. Every JSON file parses. Only presets with
    `instantiation: "true"` are user-selectable. Base names repeat across vendors with
    different content (`fdm_process_common`: 36 copies, 22 different), so the lookup for a parent
    must try the same vendor first. One parent is in another vendor (RatRig → BBL).
    187 files are in subfolders (`BBL/filament/Polymaker`, ...). Some JSON files in
    `machine/` are not presets (BBL G-code templates).
13. Each machine preset names `default_print_profile` and `default_filament_profile`
    (490 of 491 user-selectable machines). K2 Plus 0.4 → `0.20mm Standard @Creality K2
    Plus 0.4 nozzle` and `Hyper PLA @Creality K2 Plus 0.4 nozzle`.

Spike and audit scratch files were in the session scratchpad (not kept). The commands
above repeat them.

## Scope

In:

- Stdio MCP server, local only, started by Claude Code (`claude mcp add`).
- All vendors that the installed CrealityPrint bundles ("wide support"). The K2 family
  is the default when the caller names no printer.
- Inputs: STL, OBJ, 3MF on the local disk.
- Overrides of process settings on STL, OBJ and 3MF input.
- Several filaments, with a filament number for each object.

Out (V1):

- Sending a print to a printer, or printer status. (Possible later item.)
- Driving the GUI (V1.5).
- Printer or preset changes on a 3MF (fact 11: the CLI refuses them).
- Old 3MF files that need `--allow-newer-file` (fact 4: one segfaulted). V1 returns the
  `-24` error and says why.
- User presets made in the GUI (`~/.config/CrealityPrint/user/...`). V1 reads system
  presets only.
- Remote access from Claude Desktop or the phone. (home-ops does this with
  `tailscale serve` + `mcp-remote`; the same pattern can come later.)
- Progress reports during a slice (`--pipe`).

## Design

### Stack

Python 3.13, `uv`, `mcp==2.0.0` (`mcp.server.mcpserver.MCPServer`, `ToolError` from
`mcp.server.mcpserver.exceptions`), `pydantic`, `pydantic-settings`, `ruff`, `pytest`.
This is the home-ops stack (`~/repos/home-ops/pyproject.toml`). home-ops serves streamable
HTTP; V1 serves stdio: `server.run()` (default `transport="stdio"`).

Package: `creality_mcp/`. Entry point: `creality-mcp` (stdio).

### Configuration

Environment variables, read with `pydantic-settings`:

| Variable | Default | Use |
|---|---|---|
| `CREALITYPRINT_APP` | `~/Applications/CrealityPrint/squashfs-root/AppRun` | The binary. The extracted folder avoids a FUSE mount on each call. |
| `CREALITYPRINT_PROFILES` | `<app dir>/resources/profiles` | System presets. |
| `CREALITYPRINT_OUTPUT` | `~/.cache/creality-mcp/jobs` | One folder for each slice job. |
| `CREALITYPRINT_DEFAULT_PRINTER` | `Creality K2 Plus 0.4 nozzle` | Used when the caller names no printer. (Open question 1.) |
| `CREALITYPRINT_TIMEOUT_S` | `600` | Kill the slicer after this time. |
| `CREALITYPRINT_MAX_JOBS` | `50` | Keep this many job folders; delete the oldest. |

At start, the server checks that the binary and the profile folder exist. If not, every
tool returns a clear error that names the variable to set. The server does not crash.

### Preset catalog (read-only)

`catalog.py` scans all vendor folders once at start, **recursively** (fact 12).

- Index entry: `(vendor, kind, name) → file path, raw dict`. Keep only files whose `type`
  is `machine`, `process` or `filament`. Sort all lists by name, so output order is
  stable.
- Selectable presets: `instantiation == "true"`. If a name repeats inside one vendor
  (Prusa `0.15mm Speed @MK3S`), keep the first path in sorted order and log the repeat.
- Lookup by name across vendors: a name that is unique among selectable presets resolves
  directly. A name that two vendors share needs a `vendor` argument; else tool error that
  lists the vendors.
- `resolve(vendor, kind, name)`: walk `inherits`; look a parent up in the same vendor
  first, then in the other vendors (sorted). Merge root first, leaf last. Used **only**
  to show settings (`get_preset`) and to know the valid override keys and their current
  values. The slicer always gets the raw leaf file (fact 5).
- `compatible(printer, kind)`: process and filament presets of the printer's vendor whose
  `compatible_printers` list holds the printer name. Presets with an empty list and a
  `compatible_printers_condition` are left out (7 Prusa process presets). Presets with an
  empty list and no condition (1 Sovol) count as compatible with every printer of their
  vendor. The start log states both counts. For K2 Plus 0.4 this gives 10 process and
  101 filament presets.

### Overrides

Input: `{key: value}` with config keys as they appear in presets (`layer_height`).

1. Each key must be in the resolved process preset. For a 3MF, the process preset is
   unknown before the slice. So check the key against all keys of all resolved process
   presets. Else tool error that names the key and up to 5 close matches
   (`difflib`). This guards fact 6: the CLI fails with no `result.json` on an
   unknown flag.
2. Flag: `--` + key with `_` → `-`, then `=`, then the value, as one argument (fact 6).
3. Value: Python `bool` → `1`/`0`; other types → `str(value)`. The server refuses a value
   with a `;` or a newline (the CLI splits lists on `;`, and one argument must stay one value).

### Slice job

`slicer.py`:

1. Make a job folder `<output>/<UTC timestamp>-<short id>/`. Delete the oldest job
   folders past `CREALITYPRINT_MAX_JOBS`, only inside the output folder.
2. Check inputs: each model exists and ends in `.stl`, `.obj` or `.3mf`; 3MF and STL/OBJ
   are not mixed; a 3MF gets no printer, process or filament argument (fact 11).
3. STL/OBJ: printer = argument or default printer; process = argument or the machine's
   `default_print_profile`; filaments = argument or `[default_filament_profile]`; at
   least one filament (fact 10). The process and each filament must be in
   `compatible(printer)`; else tool error that names the compatible list tool.
4. Build the argument list: `--cli --slice 0 --need-gcode-file --outputdir <job>`, then
   for STL/OBJ `--load-settings "<machine>;<process>" --load-filaments "<f1>;<f2>"`, and
   `--load-filament-ids "<n1>,<n2>,..."` when the caller gives a filament number for each
   model. Then the override flags, then the model paths.
5. Run with `subprocess.run`: argument list (no shell), `cwd=<job>`,
   `start_new_session=True`, the timeout, stdout and stderr to `<job>/slicer.log`.
   Timeout → kill the process group, tool error "slicer timed out after N s".
6. Read `result.json`. Missing file → tool error with the exit code and the last 20
   non-trace lines of `slicer.log` (fact 4). `return_code != 0` → tool error with
   `error_string`, `return_code` and the log tail.
7. For each `plate_N.gcode`, parse the summary (§G-code summary).

### G-code summary

`gcode.py` reads the header and the config block (fact 8). It accepts both `key = value`
and `key: value` lines, and both the Creality and the BBL time lines.

- `print_time_s` and `print_time_text`: from `estimated printing time (normal mode)`,
  else from `total estimated time` in the `model printing time` line.
- `filament_mm`, `filament_g`: lists, one value for each filament; `null` when the line is
  absent.
- `layers`: from `total layer number`.
- `settings`: `printer_model`, `print_settings_id`, `filament_settings_id`,
  `layer_height`.
- A missing value is `null`, never a crash, and its name goes in `missing_stats`.

### Tools

All tools only read the user's files. `slice_model` writes only inside the output folder.

| Tool | Input | Output |
|---|---|---|
| `list_printers` | `vendor?`, `query?` (substring, case-insensitive) | `[{name, vendor, model, nozzle}]`, selectable only, sorted |
| `list_presets` | `printer`, `kind` (`process`/`filament`), `query?` | `[{name, vendor}]` from `compatible()`, sorted; the machine's default first |
| `get_preset` | `kind`, `name`, `vendor?`, `keys?` | resolved settings; only `keys` when given (a full preset is large) |
| `slice_model` | `models[]`, `printer?`, `process?`, `filaments?[]`, `filament_ids?[]`, `overrides?{}` | `{job_dir, plates:[{plate, gcode_path, print_time_s, print_time_text, filament_g[], filament_mm[], layers, warning}], used:{printer, process, filaments, overrides}, missing_stats}` |
| `read_gcode_summary` | `path` | the same plate stats for any G-code file |

`used` always names the presets the slice used, so Claude can tell the user. For a 3MF,
`used` holds the values from the G-code config block.

### Errors

Tool errors use `ToolError` with a short message for Claude. Tracebacks go to stderr
only: stdout is the MCP channel on stdio, and nothing else may print there.

## Tests

New repo, so no existing tests to extend.

- Unit (no binary):
  - catalog on a fixture vendor tree (`tests/fixtures/profiles/`). It holds: two vendors
    with one base name and different values; a subfolder; a non-preset JSON; a repeated
    name; a cross-vendor parent;
  - override checks: unknown key with close matches, boolean, plain value, a value with
    `;`;
  - G-code parser on trimmed fixtures from a Creality slice, a BBL slice and a
    2-filament slice;
  - `result.json` handling: success, `-17`, missing file.
- Integration (marker `slicer`, skipped when `CREALITYPRINT_APP` is absent):
  - K2 Plus cube with defaults: `used` names `0.20mm Standard` and `Hyper PLA`;
  - `layer_height` 0.28 and `enable_arc_fitting` false → the G-code shows both;
  - 3MF with an override;
  - 2 cubes, 2 filaments, `filament_ids` [1, 2] → both filament lengths > 0;
  - bad preset name, and a 3MF with a printer argument → tool errors;
  - BBL X1C cube → `print_time_s` is set.
- MCP smoke: start the server over stdio in a test and call `list_printers` and
  `slice_model` through a client session.

## Setup and rollout

1. `uv sync`, then `claude mcp add creality -- uv --directory ~/repos/creality-mcp run creality-mcp`.
2. README: get the AppImage (`gh release download v7.3.0 -R CrealityOfficial/CrealityPrint
   -p '*6151-x86_64-Release.AppImage'`), extract it with `--appimage-extract`.
3. GitHub repo `tschd/creality-mcp`, public (TS, 2026-10-09). Create it at first push.

Rollback: `claude mcp remove creality`. The server writes only to its job folder.

## Risks

- **AppImage updates change CLI flags, `result.json` or G-code lines.** Pin the tested
  version in the README; the integration tests catch drift.
- **Large models slice for minutes.** The timeout covers hangs; the MCP call blocks until
  the slice ends.
- **The catalog hides presets that have only a `compatible_printers_condition`.** Small today (7
  Prusa process presets); the start log shows the count.

## V1.5 boundary

V1.5: Claude drives the open CrealityPrint GUI on mandalore (Windows). It needs C++ changes
in the fork `tschd/CrealityPrint`. The app has an embedded `HttpServer`
(`src/slic3r/GUI/HttpServer.hpp`). It also needs a native Windows build on mandalore, and
a network path plus auth from Claude to mandalore. Known risk: the repo's build scripts target
VS 2022 (`build_release_vs2022.bat`); mandalore has VS 2026 Community, and its VS 2022
BuildTools folder is not registered with the VS installer. V1.5 gets its own spec after
V1 ships. The V1 tool names and result shapes should carry over, so the same Claude
prompts work in both.

## Open questions

1. Default printer: which K2 model and nozzle? (Spec assumes `Creality K2 Plus 0.4
   nozzle`. It is one setting, so a wrong guess costs one line.)
