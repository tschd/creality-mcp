"""Read-only index of the CrealityPrint system presets.

The slicer always gets the raw leaf file. `resolve()` merges the `inherits` chain only to
show settings, to judge compatibility and to know the valid override keys.
"""

import difflib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

KINDS = ("machine", "process", "filament")


@dataclass(frozen=True)
class Preset:
    vendor: str
    kind: str
    name: str
    path: Path
    data: dict


class CatalogError(Exception):
    pass


def _as_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return []


class Catalog:
    def __init__(self, presets: list[Preset]) -> None:
        # Every preset, by (vendor, kind, name); the first path in sorted order wins.
        self._all: dict[tuple[str, str, str], Preset] = {}
        self._vendors = sorted({p.vendor for p in presets})
        for p in presets:
            key = (p.vendor, p.kind, p.name)
            if key in self._all:
                log.info(
                    "repeated %s preset %r in %s; keeping %s",
                    *key[1:],
                    p.vendor,
                    self._all[key].path,
                )
                continue
            self._all[key] = p
        self._selectable = {
            kind: sorted(
                (
                    p
                    for p in self._all.values()
                    if p.kind == kind and p.data.get("instantiation") == "true"
                ),
                key=lambda p: (p.name, p.vendor),
            )
            for kind in KINDS
        }
        self._resolved: dict[tuple[str, str, str], dict] = {}

    @classmethod
    def load(cls, profiles_dir: Path) -> "Catalog":
        presets = []
        for vendor_dir in sorted(p for p in profiles_dir.iterdir() if p.is_dir()):
            for folder in KINDS:
                for path in sorted((vendor_dir / folder).rglob("*.json")):
                    preset = _read_preset(vendor_dir.name, path)
                    if preset is not None:
                        presets.append(preset)
        return cls(presets)

    def selectable(self, kind: str) -> list[Preset]:
        return list(self._selectable[kind])

    def find(self, kind: str, name: str, vendor: str | None = None) -> Preset:
        matches = [p for p in self._selectable[kind] if p.name == name]
        if vendor is not None:
            matches = [p for p in matches if p.vendor == vendor]
        if not matches:
            where = f" from vendor '{vendor}'" if vendor else ""
            msg = f"no {kind} preset named '{name}'{where}"
            names = sorted({p.name for p in self._selectable[kind]})
            close = difflib.get_close_matches(name, names, n=5, cutoff=0.6)
            if close:
                msg += "; close: " + ", ".join(close)
            raise CatalogError(msg)
        if len(matches) > 1:
            vendors = ", ".join(p.vendor for p in matches)
            raise CatalogError(
                f"{kind} preset '{name}' exists in several vendors ({vendors}); pass vendor"
            )
        return matches[0]

    def resolve(self, preset: Preset) -> dict:
        """The preset merged over its `inherits` chain, root first, without `inherits`."""
        key = (preset.vendor, preset.kind, preset.name)
        if key not in self._resolved:
            chain = [preset]
            seen = {key}
            node = preset
            while parent_name := node.data.get("inherits"):
                parent = self._parent(node, parent_name)
                pkey = (parent.vendor, parent.kind, parent.name)
                if pkey in seen:
                    raise CatalogError(f"inherits cycle at {preset.kind} preset '{parent_name}'")
                seen.add(pkey)
                chain.append(parent)
                node = parent
            merged: dict = {}
            for p in reversed(chain):
                merged.update(p.data)
            merged.pop("inherits", None)
            self._resolved[key] = merged
        return dict(self._resolved[key])

    def _parent(self, node: Preset, name: str) -> Preset:
        vendors = [node.vendor] + [v for v in self._vendors if v != node.vendor]
        for vendor in vendors:
            found = self._all.get((vendor, node.kind, name))
            if found is not None:
                return found
        raise CatalogError(f"{node.kind} preset '{node.name}' inherits missing preset '{name}'")

    def defaults(self, machine: Preset) -> tuple[str | None, list[str]]:
        data = self.resolve(machine)
        processes = _as_list(data.get("default_print_profile"))
        filaments = _as_list(data.get("default_filament_profile"))
        return (processes[0] if processes else None), filaments

    def compatible(self, printer: Preset, kind: str) -> list[Preset]:
        result = []
        for p in self._selectable[kind]:
            if p.vendor != printer.vendor:
                continue
            restriction = self._restriction(p)
            if restriction is None or printer.name in restriction:
                result.append(p)
        default_process, default_filaments = self.defaults(printer)
        first = [default_process] if kind == "process" else default_filaments
        rank = {name: i for i, name in enumerate(n for n in first if n)}
        return sorted(result, key=lambda p: rank.get(p.name, len(rank)))

    def _restriction(self, preset: Preset) -> list[str] | None:
        """The printers a preset allows; None = every printer of its vendor. A preset that
        fails to resolve, or has only a condition, allows none."""
        try:
            data = self.resolve(preset)
        except CatalogError as exc:
            log.warning("skipping %s: %s", preset.path, exc)
            return []
        printers = _as_list(data.get("compatible_printers"))
        if printers:
            return printers
        return [] if data.get("compatible_printers_condition") else None

    def stats(self) -> dict:
        counts = {kind: len(self._selectable[kind]) for kind in KINDS}
        condition_only = unrestricted = 0
        for kind in ("process", "filament"):
            for p in self._selectable[kind]:
                restriction = self._restriction(p)
                if restriction is None:
                    unrestricted += 1
                elif not restriction and self._resolve_or_empty(p).get(
                    "compatible_printers_condition"
                ):
                    condition_only += 1
        return {**counts, "condition_only": condition_only, "unrestricted": unrestricted}

    def _resolve_or_empty(self, preset: Preset) -> dict:
        try:
            return self.resolve(preset)
        except CatalogError:
            return {}


def _read_preset(vendor: str, path: Path) -> Preset | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        log.warning("skipping unreadable preset %s: %s", path, exc)
        return None
    if not isinstance(data, dict) or data.get("type") not in KINDS:
        log.debug("skipping non-preset %s", path)
        return None
    return Preset(vendor, data["type"], data.get("name", path.stem), path, data)
