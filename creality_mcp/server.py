"""The stdio MCP server: five tools over the preset catalog and the slicer.

Stdout is the MCP channel; logging goes to stderr only.
"""

import difflib
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from creality_mcp.catalog import Catalog, CatalogError, Preset
from creality_mcp.gcode import parse_gcode
from creality_mcp.settings import Settings, check_install
from creality_mcp.slicer import SliceError, SliceRequest, run_slice

log = logging.getLogger(__name__)

INSTRUCTIONS = """\
Slices 3D models (STL, OBJ, 3MF) with CrealityPrint on this machine and reports print time, \
filament use and warnings.
Call list_printers and list_presets before choosing presets; use the exact names they return.
Overrides use preset keys like layer_height or sparse_infill_density (see get_preset).
A 3MF keeps its own printer and presets; only overrides apply to it."""

TOOL_NAMES = {"list_printers", "list_presets", "get_preset", "slice_model", "read_gcode_summary"}

_READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)


def build_server(settings: Settings) -> MCPServer:
    server = MCPServer("creality", instructions=INSTRUCTIONS)
    catalog, problem = _load_catalog(settings)

    def need_catalog() -> Catalog:
        if catalog is None:
            raise ToolError(problem)
        return catalog

    @server.tool(
        description=(
            "Printers CrealityPrint knows, sorted by name. `query` is a case-insensitive "
            "substring of the name; `vendor` limits to one vendor folder."
        ),
        annotations=_READ,
    )
    def list_printers(vendor: str | None = None, query: str | None = None) -> list[dict]:
        cat = need_catalog()
        q = (query or "").lower()
        return [
            _printer_item(cat, p)
            for p in cat.selectable("machine")
            if (vendor is None or p.vendor == vendor) and q in p.name.lower()
        ]

    @server.tool(
        description=(
            "Process or filament presets compatible with a printer, the printer's default "
            "first. Pass `vendor` when two vendors share the printer name."
        ),
        annotations=_READ,
    )
    def list_presets(
        printer: str,
        kind: Literal["process", "filament"],
        vendor: str | None = None,
        query: str | None = None,
    ) -> list[dict]:
        cat = need_catalog()
        with _tool_errors():
            machine = cat.find("machine", printer, vendor)
            presets = cat.compatible(machine, kind)
        q = (query or "").lower()
        return [{"name": p.name, "vendor": p.vendor} for p in presets if q in p.name.lower()]

    @server.tool(
        description=(
            "The resolved settings of one preset (its inherits chain merged). A full preset is "
            "large: pass `keys` to get only those settings."
        ),
        annotations=_READ,
    )
    def get_preset(
        kind: Literal["machine", "process", "filament"],
        name: str,
        vendor: str | None = None,
        keys: list[str] | None = None,
    ) -> dict:
        cat = need_catalog()
        with _tool_errors():
            data = cat.resolve(cat.find(kind, name, vendor))
        if keys is None:
            return data
        unknown = [k for k in keys if k not in data]
        if unknown:
            close = sorted({c for k in unknown for c in difflib.get_close_matches(k, data, n=5)})
            hint = f"; close: {', '.join(close)}" if close else ""
            raise ToolError(f"unknown setting(s) {', '.join(unknown)}{hint}")
        return {k: data[k] for k in keys}

    @server.tool(
        description=(
            "Slice models with CrealityPrint. STL/OBJ: printer, process and filaments default "
            "to the printer's defaults; filament_ids gives each model a 1-based filament "
            "number. 3MF: one file, its stored presets; only overrides apply. overrides maps "
            "preset keys to values, e.g. {'layer_height': 0.28, 'enable_support': true}. "
            "Returns print time, filament use and the presets used for each plate."
        ),
        annotations=_WRITE,
    )
    async def slice_model(
        models: list[str],
        printer: str | None = None,
        vendor: str | None = None,
        process: str | None = None,
        filaments: list[str] | None = None,
        filament_ids: list[int] | None = None,
        overrides: dict[str, str | int | float | bool] | None = None,
    ) -> dict:
        cat = need_catalog()
        req = SliceRequest(
            models=models,
            printer=printer,
            printer_vendor=vendor,
            process=process,
            filaments=filaments,
            filament_ids=filament_ids,
            overrides=overrides,
        )
        with _tool_errors():
            result = await anyio.to_thread.run_sync(run_slice, req, settings, cat)
        return asdict(result)

    @server.tool(
        description="Print time, filament use and layers of any sliced G-code file.",
        annotations=_READ,
    )
    def read_gcode_summary(path: str) -> dict:
        gcode = Path(path).expanduser().resolve()
        if not gcode.is_file():
            raise ToolError(f"G-code file not found: {gcode}")
        return asdict(parse_gcode(gcode))

    return server


def _load_catalog(settings: Settings) -> tuple[Catalog | None, str]:
    problem = check_install(settings)
    if problem is not None:
        log.error(problem)
        return None, problem
    try:
        catalog = Catalog.load(settings.profiles_dir)
    except OSError as exc:
        log.exception("cannot read presets")
        return None, f"cannot read CrealityPrint presets at {settings.profiles_dir}: {exc}"
    log.info("preset catalog: %s", catalog.stats())
    return catalog, ""


def _printer_item(cat: Catalog, p: Preset) -> dict:
    try:
        nozzles = cat.resolve(p).get("nozzle_diameter")
    except CatalogError:
        nozzles = None
    nozzle = nozzles[0] if isinstance(nozzles, list) and nozzles else nozzles
    return {
        "name": p.name,
        "vendor": p.vendor,
        "model": p.data.get("printer_model"),
        "nozzle": nozzle,
    }


@contextmanager
def _tool_errors() -> Iterator[None]:
    """Catalog and slice errors carry a message meant for Claude; pass it on as a ToolError."""
    try:
        yield
    except (CatalogError, SliceError) as exc:
        raise ToolError(str(exc)) from exc


def main() -> None:
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(name)s %(message)s"
    )
    build_server(Settings()).run()
