---
tags: [session, creality-mcp, 3d-printing, mcp]
date: 2026-10-09
version: 2026.10.09
---

# Session 2026-10-09 — creality-mcp V1 spec and plan

## Headline

- New project: Claude slices with CrealityPrint. The official v7.3.0 AppImage slices headless with `--cli`.
- Audits checked the V1 spec and the 7-task plan (24 findings folded in); GitHub holds both.
- Two audits replaced preset flattening with raw presets plus `--key=value` flags.

## What ships

Docs and setup only. No code yet.

- **Fork:** `tschd/CrealityPrint` from `CrealityOfficial/CrealityPrint`, cloned at
  `~/repos/crealityprint`. `origin` is the fork, `upstream` is Creality. `master` tracks
  `origin/master` and stays a clean mirror.
- **AppImage:** `CrealityPrint-V7.3.0.6151-x86_64-Release.AppImage` in
  `~/Applications/CrealityPrint/`, extracted to `squashfs-root/`.
- **Repo `tschd/creality-mcp`** (public, TS 2026-10-09): `CLAUDE.md` with the session
  conventions, `.gitignore`, the spec and the plan in `docs/plans/`.
- **Vault:** `Software/creality-mcp/` with `Open Items.md`, `Closed Items.md`,
  `Release History.md` and the overview note `creality-mcp.md`.
- **Registry:** `creality-mcp` added to `~/.config/open-items-web/projects.json` (backup
  `projects.json.bak-2026-10-09`).

## Key technical decisions

1. V1 runs the official AppImage, not a source build. A build on devrat (4 cores) takes hours, and the AppImage CLI covers every V1 need.
2. The slicer gets the raw system preset files and `--key=value` override flags. A flattened preset without `inherits` fails with `-17`, because the CLI takes the system name of the machine from `inherits` (`src/slic3r/CLI/SliceCommand.cpp:1410`).
3. The catalog judges compatibility and machine defaults on resolved presets. About 110 leaves inherit `compatible_printers` from a parent, and the defaults are lists.
4. Booleans use `--key=0` or `--key=1`. This build turns off the `--no-` prefix (`src/libslic3r/Config.cpp:1860`), and a bare flag reads the next word as a file.
5. V1.5 runs the GUI on mandalore (Windows), and builds there (TS 2026-10-09). mandalore has a Ryzen 9 7900X, 31 GB and VS 2026 Community.

## Commits

- `9b0f40e` docs: creality-mcp V1 spec (audited) and repo conventions
- `d75252c` docs: creality-mcp V1 implementation plan (audited)

## Lessons

- The first spike "proved" that partial presets fail. The spec audit showed that the real cause of `-17` was the missing `inherits`, not the missing keys. A spike that shows a failure does not show its cause; read the source before you design around it.
- mandalore's SSH shell is `cmd.exe`. Inline PowerShell broke twice on quoting, and a script file copied with `scp` worked the first time.

## Open Items for Next Session

_(snapshot as of close — canonical list lives in [[Open Items]])_

1. **⏳TS Build V1 from the audited plan.** Audits checked the spec and the plan, and git holds both.
   The build has 7 tasks, from the scaffold to the live check in Claude Code.
   Resume: `cd ~/repos/creality-mcp && claude` then "execute docs/plans/2026-10-09-creality-mcp-v1-plan.md natively"
   Ask: Review the plan and build it native? — recommend native (7 tasks in a strict chain)
2. **⏳TS Pick the default K2 printer and nozzle.** The spec uses `Creality K2 Plus 0.4 nozzle`.
   Ask: Which K2 and nozzle? — recommend K2 Plus 0.4 (the stock nozzle; the tests use it)
3. **Write the V1.5 spec: Claude drives the CrealityPrint GUI.** It needs C++ endpoints in the fork.
   Blocked: 1
4. **Prove a Windows build of the fork on mandalore.** A first build shows if VS 2026 works.
   Resume: `ssh -o ConnectTimeout=5 mandalore`, clone `tschd/CrealityPrint`, run `build_release_vs2022.bat`
