"""Print stats from the comment lines of a sliced G-code file.

Creality and BBL printers write different summary lines; a value the file lacks is None
and its name goes in `missing`, never an exception.
"""

import re
from dataclasses import dataclass
from pathlib import Path

SETTING_KEYS = (
    "printer_model",
    "printer_settings_id",
    "print_settings_id",
    "filament_settings_id",
    "layer_height",
)

_LINE = re.compile(r"^; (?P<k>[^=:]+?)\s*[=:]\s*(?P<v>.*)$")
# BBL: "; model printing time: 10m 22s; total estimated time: 10m 22s"
_BBL_TIME = re.compile(r"^; model printing time: .*?; total estimated time: (?P<v>.+)$")
_DURATION = re.compile(r"^(?:(\d+)d)?\s*(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?$")


@dataclass
class PlateStats:
    plate: int
    gcode_path: str
    print_time_s: int | None
    print_time_text: str | None
    filament_g: list[float] | None
    filament_mm: list[float] | None
    layers: int | None
    settings: dict[str, str]
    missing: list[str]
    warning: str | None = None


def parse_duration(text: str) -> int | None:
    """Seconds from text like `1d 2h 3m 4s` (any subset of units); None if it does not parse."""
    m = _DURATION.match(text.strip())
    if not m or not any(m.groups()):
        return None
    d, h, mins, s = (int(g) if g else 0 for g in m.groups())
    return ((d * 24 + h) * 60 + mins) * 60 + s


def _floats(text: str | None) -> list[float] | None:
    if text is None:
        return None
    try:
        return [float(v) for v in text.split(",")]
    except ValueError:
        return None


def _read_pairs(path: Path) -> tuple[dict[str, str], str | None]:
    """Every `; key = value` / `; key: value` comment. The last occurrence wins: the stats
    footer and the config block close the file, after any comment in custom G-code."""
    pairs: dict[str, str] = {}
    bbl_time = None
    with path.open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            if not raw.startswith(";"):
                continue
            line = raw.rstrip("\r\n")
            if bbl_time is None and (m := _BBL_TIME.match(line)):
                bbl_time = m["v"].strip()
                continue
            if m := _LINE.match(line):
                pairs[m["k"]] = m["v"].strip()
    return pairs, bbl_time


def parse_gcode(path: Path, plate: int = 1) -> PlateStats:
    pairs, bbl_time = _read_pairs(path)
    time_text = pairs.get("estimated printing time (normal mode)") or bbl_time
    time_s = parse_duration(time_text) if time_text else None
    layers_text = pairs.get("total layer number", "")
    stats = {
        "print_time_s": time_s,
        "filament_g": _floats(pairs.get("filament used [g]")),
        "filament_mm": _floats(pairs.get("filament used [mm]")),
        "layers": int(layers_text) if layers_text.isdigit() else None,
    }
    return PlateStats(
        plate=plate,
        gcode_path=str(path),
        print_time_text=time_text,
        settings={k: pairs[k] for k in SETTING_KEYS if k in pairs},
        missing=sorted(k for k, v in stats.items() if v is None),
        **stats,
    )
