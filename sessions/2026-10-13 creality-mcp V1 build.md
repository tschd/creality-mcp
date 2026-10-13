---
tags: [session, creality-mcp, 3d-printing, mcp]
date: 2026-10-13
version: 2026.10.13
---

# Session 2026-10-13 — creality-mcp V1 build

## Headline

- V1 shipped: a stdio MCP server with five tools that slices with the AppImage CLI. 81 tests pass, and a fresh session sliced the cube.
- Security reviews found override keys that run scripts or write outside the job folder; the server now refuses them.
- mandalore has no MSVC; a session there installs VS 2022 Build Tools and times the first fork build.

## What ships

**Code** (`creality_mcp/`, plan Tasks 1–7, built in this session as TS chose):

- `settings.py`: `CREALITYPRINT_*` settings and `check_install()`. The default printer is `Creality K2 Plus 0.4 nozzle` (TS 2026-10-13).
- `catalog.py`: a read-only index of the system presets with `resolve`, `compatible` and `defaults`. On the real presets: 10 process and 101 filament presets for the K2 Plus 0.4, `condition_only` 7, `unrestricted` 1, as the spec says.
- `gcode.py`: plate stats from the comment lines (Creality and BBL time lines; lists for each filament).
- `overrides.py`: `--key=value` flags. It refuses unknown keys, `;`, line breaks and NUL, `post_process`, `filename_format` and preset metadata keys.
- `slicer.py`: the job folder, `AppRun --cli` in its own process group with `stdin=DEVNULL`, `result.json`, and the plates.
- `server.py`: `list_printers`, `list_presets`, `get_preset`, `slice_model` (in a worker thread) and `read_gcode_summary`.

**Tests:** 71 unit tests with a fake `AppRun`, and 10 integration tests with the real AppImage, plus a stdio test that starts the server through `uv`. The G-code fixtures are the comment lines of real slices, and `.gitignore` lets `tests/fixtures/gcode/*.gcode` in.

**Install:** `claude mcp add -s user creality -- uv --directory /home/tsd/repos/creality-mcp run creality-mcp` shows `✔ Connected`. A headless `claude -p` session listed 13 K2 printers and sliced the cube at 0.28 mm: 9m 30s, 4.46 g.

**Repo:** `README.md`; `.planning/.gitkeep` (the gate of the side-column mod); the spec and the plan have status `done`.

**mandalore (item 4):** the probe found no Visual Studio product, no `cl.exe` on any drive, no CMake, no Perl, and SDK 10.0.26100 only. A brief went to the session `mandalore-scalable-sparrow`. TS chose VS 2022 Build Tools, CMake, Strawberry Perl, and the clone path `C:\Users\tschd\Desktop\repos\CrealityPrint`. The clone is done, and the installs still ran at the end of this session.

## Key technical decisions

1. Overrides refuse `post_process` and `filename_format`. Both are valid process keys: the first runs a script, and the second can name an output path outside the job folder.
2. A 3MF can carry its own `post_process`. Tests pin that the V7.3.0.6151 CLI never runs it, so a later AppImage that runs it fails the suite. The review also saw the CLI refuse a 3MF with `post_process` (`return_code -19`).
3. `gcode.py` keeps the last occurrence of a key. The stats footer and the config block close the file, so a stat-like comment in custom start G-code cannot shadow them.
4. The slicer gets `stdin=DEVNULL`, because on stdio the server's stdin is the MCP channel. After every run the server kills the process group, to stop leftover helper processes.
5. `slice_model` runs in `anyio.to_thread`, as in home-ops, so a slice of up to 600 s does not block the stdio event loop.

## Commits

- `94bcece` feat: project scaffold and settings
- `0407d85` feat: preset catalog
- `c109c50` feat: G-code summary parser
- `278637d` feat: override flags
- `f1870ce` fix: refuse post_process and filename_format overrides
- `f53d5b7` feat: slicer runner
- `9062852` feat: MCP server with five tools
- `19a10f2` test: real-slicer integration and stdio smoke; README
- `eb8ebf7` fix: findings from the V1 review
- `dd3a3ca` docs: V1 spec and plan done; default printer answered (K2 Plus 0.4)
- `5e6d616` chore: add .planning/ so the side-column mod shows this repo's open items

## Lessons

- A note from an earlier session said "mandalore has VS 2026 Community". A probe showed only the installer. Probe a host before you plan a build on it.
- The first timeout test killed only one process, so it passed with `os.kill` too. A fake slicer with a child, and a negative control, made the test fail on the bug. A killed child is a zombie until init reaps it: check `/proc/<pid>/stat`, not `kill(pid, 0)`.
- The side-column mod shows nothing for a repo without `.planning/`. Memory: `side-column-needs-planning-dir`.

## Open Items for Next Session

_(snapshot as of close — canonical list lives in [[Open Items]])_

3. **Write the V1.5 spec: Claude drives the CrealityPrint GUI.** Start from the `HttpServer` in the fork, and put the item 4 result in the spec.
   Detail: spec §V1.5 boundary
4. **🔨 Prove a Windows build of the fork on mandalore.** `mandalore-scalable-sparrow` installs the toolchain and times the deps and slicer builds. Record its report in item 4.
   Check: brief `%USERPROFILE%\creality-mandalore-brief.md` on mandalore
5. **A slice outlives a killed server.** The slicer runs until it ends or reaches its timeout (default 600 seconds), so the risk is low.
   Detail: `creality_mcp/slicer.py` `_execute`

## Addendum 16:55

- Item 4 closed: `mandalore-scalable-sparrow` built `master` with no repo changes: VS 2022 Build Tools (MSVC 14.44 + `VC.ATL`), SDK 10.0.22000, CMake 4.4.4, Strawberry Perl. The deps took 14m40s, the slicer 14m40s, and `CrealityPrint.exe` ran for 20 seconds with no crash.
- Workarounds were environment only: `CMAKE_POLICY_VERSION_MINIMUM=3.5` for CMake 4, the `VC.ATL` component for breakpad, and a separate winget package for SDK 22000. `CLAUDE.md` now records the recipe and drops the wrong "VS 2026 Community".
- New item 6: the `install` step needs a WebView2 installer that the repo does not hold. Also, translations did not compile, and nobody has seen the main window yet.
