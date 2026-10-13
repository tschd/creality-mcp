# creality-mcp

MCP server that lets Claude slice 3D models with CrealityPrint. V1 runs the official
CrealityPrint AppImage headless (`AppRun --cli`) on this box. V1.5 drives the open
CrealityPrint GUI on mandalore (Windows) through C++ changes in the fork. Stack, domain and
deploy rules specific to this repo. The box-wide baseline (WORKING_STYLE, skills, shared
memories) loads via `~/.claude/CLAUDE.md`.

Current spec: `docs/plans/2026-10-09-creality-mcp-v1-spec.md`.

## Stack

- Python 3.13, `uv`, `mcp==2.0.0` (`mcp.server.mcpserver.MCPServer`), stdio transport.
  Same stack as `~/repos/home-ops`.
- Slicer: official `CrealityPrint-V7.3.0.6151-x86_64-Release.AppImage`, extracted to
  `~/Applications/CrealityPrint/squashfs-root/`. Run `AppRun --cli ...`. Never run it
  without `--cli` from a script: it opens the GUI and hangs.
- Fork of the app (V1.5 only): `~/repos/crealityprint` (`origin` = `tschd/CrealityPrint`,
  `upstream` = `CrealityOfficial/CrealityPrint`). Keep its `master` a clean mirror of
  upstream; V1.5 work goes on branches.
- mandalore: Windows build host for V1.5 (Ryzen 9 7900X, 31 GB). Its shell is `cmd.exe`:
  send PowerShell as a script file (`scp` + `powershell -File`), never inline. Use
  `ssh -o ConnectTimeout=5`.
- Fork build on mandalore (proven 2026-10-13): clone `C:\Users\tschd\Desktop\repos\CrealityPrint`;
  VS 2022 Build Tools (MSVC 14.44 + `VC.ATL`), SDK 10.0.22000, CMake 4.4.4, Strawberry Perl.
  From an x64 `vcvars64` shell, set `CMAKE_POLICY_VERSION_MINIMUM=3.5` (CMake 4 refuses
  `deps/CMakeLists.txt:23`), then run `.\build_release_vs2022.bat deps`, then `... slicer`
  (about 15 min each). `deps` exits 0 even when it fails: read the log.

## Domain rules

- The slicer's success signal is `result.json` `return_code == 0`, not the process exit code.
- Pass full (flattened) presets to the CLI. A preset with only `inherits` plus changed keys
  fails with `return_code -17`.
- Stdout is the MCP channel. Nothing else may print to stdout.

## Session conventions (resume / handoff)

- `SESSIONS_DIR = sessions/` — repo-local session notes (`YYYY-MM-DD <slug>.md`). Not in the
  vault, so Open/Closed Items cite a session as inline `YYYY-MM-DD <slug>`, never `[[…]]`.
- `OPEN_ITEMS_DOC = /home/tsd/Documents/TSD/Software/creality-mcp/Open Items.md` — canonical
  open items; topical `##` sections, every item a numbered top-level line; closed items move
  to sibling `Closed Items.md`.
- `RELEASE_TARGET = main`. The server runs locally from this checkout, so a push to `main` is
  the release.
- `WAITING_OPERATOR = TS`

## Orchestrator project layer

- **TEST_CMD** `uv run python -m pytest -q` · **LINT_CMD** `uv run ruff check .`
- **FORBIDDEN_OPS** force-push to `main`; committing slicer output (`*.gcode`, job folders) or
  the AppImage.
