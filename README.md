# creality-mcp

A local MCP server that lets Claude slice 3D models with
[CrealityPrint](https://github.com/CrealityOfficial/CrealityPrint). It runs the official
AppImage headless (`AppRun --cli`): Claude picks a printer, a process preset and filament
presets, changes settings when asked, and reads back print time, filament use and warnings.
No CrealityPrint window opens.

Tested with `CrealityPrint-V7.3.0.6151-x86_64-Release.AppImage` on Linux x86_64. A later
release can change CLI flags or G-code lines; the integration tests (`pytest -m slicer`)
catch that.

## Tools

| Tool | What it does |
|---|---|
| `list_printers` | Printers CrealityPrint knows (all bundled vendors), filter by `vendor` / `query` |
| `list_presets` | Process or filament presets compatible with a printer, its default first |
| `get_preset` | The resolved settings of a preset; pass `keys` for a few |
| `slice_model` | Slice STL/OBJ (or one 3MF) with presets and `overrides` such as `{"layer_height": 0.28}` |
| `read_gcode_summary` | Print time, filament use and layers of any G-code file |

## Install

1. Get the AppImage and extract it (the extracted folder avoids a FUSE mount per slice):

   ```bash
   mkdir -p ~/Applications/CrealityPrint && cd ~/Applications/CrealityPrint
   gh release download v7.3.0 -R CrealityOfficial/CrealityPrint \
     -p 'CrealityPrint-V7.3.0.6151-x86_64-Release.AppImage'
   chmod +x CrealityPrint-V7.3.0.6151-x86_64-Release.AppImage
   ./CrealityPrint-V7.3.0.6151-x86_64-Release.AppImage --appimage-extract
   ```

2. Install the server and register it with Claude Code:

   ```bash
   cd ~/repos/creality-mcp && uv sync
   claude mcp add -s user creality -- uv --directory ~/repos/creality-mcp run creality-mcp
   ```

   `claude mcp list` should show `creality` connected. Remove it with
   `claude mcp remove -s user creality`.

## Configuration

Environment variables (set them with `claude mcp add -e KEY=value ...`):

| Variable | Default | Use |
|---|---|---|
| `CREALITYPRINT_APP` | `~/Applications/CrealityPrint/squashfs-root/AppRun` | The binary |
| `CREALITYPRINT_PROFILES` | `<app dir>/resources/profiles` | System presets |
| `CREALITYPRINT_OUTPUT` | `~/.cache/creality-mcp/jobs` | One folder for each slice job |
| `CREALITYPRINT_DEFAULT_PRINTER` | `Creality K2 Plus 0.4 nozzle` | Used when the request names no printer |
| `CREALITYPRINT_TIMEOUT_S` | `600` | Kill the slicer after this time |
| `CREALITYPRINT_MAX_JOBS` | `50` | Keep this many job folders; delete the oldest |

## Example prompts

- "List the K2 printers."
- "Slice ~/Downloads/benchy.stl for my K2 Plus at 0.28 mm, 20% infill."
- "Slice these two parts with Hyper PLA and CR-PLA, one filament each."
- "How long does ~/Downloads/part.gcode take to print?"

## Limits (V1)

- No sending to a printer and no printer status.
- A 3MF keeps its stored printer and presets; only `overrides` apply. Old 3MF files that
  need `--allow-newer-file` are refused.
- System presets only; user presets made in the GUI are not read.
- `post_process` and `filename_format` cannot be overridden.
- Local stdio only (no remote access from Claude Desktop or the phone).

## Development

```bash
uv run python -m pytest -q        # unit + integration (integration skips without the AppImage)
uv run python -m pytest -m slicer -q
uv run ruff check .
```

Design: `docs/plans/2026-10-09-creality-mcp-v1-spec.md`.
