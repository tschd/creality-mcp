from pathlib import Path

import pytest

from creality_mcp.catalog import Catalog, CatalogError

FIXTURES = Path(__file__).parent / "fixtures" / "profiles"


@pytest.fixture(scope="module")
def cat():
    return Catalog.load(FIXTURES)


@pytest.fixture(scope="module")
def a1(cat):
    return cat.find("machine", "A1 0.4 nozzle", vendor="VendA")


def test_selectable_sorted_and_repeat_keeps_first(cat):
    procs = cat.selectable("process")
    assert [p.name for p in procs] == [
        "0.12mm A @A1",
        "0.16mm A @A1",
        "0.20mm A @A1",
        "any printer",
        "cond only",
        "cross @B",
    ]
    assert cat.resolve(procs[0])["layer_height"] == "0.12"


def test_find_shared_name_needs_vendor(cat):
    with pytest.raises(CatalogError) as err:
        cat.find("machine", "A1 0.4 nozzle")
    assert "VendA" in str(err.value)
    assert "VendB" in str(err.value)
    assert cat.find("machine", "A1 0.4 nozzle", vendor="VendA").vendor == "VendA"


def test_find_unknown_lists_close_names(cat):
    with pytest.raises(CatalogError) as err:
        cat.find("process", "0.20mm A @A")
    assert "0.20mm A @A1" in str(err.value)


def test_find_wrong_vendor(cat):
    with pytest.raises(CatalogError):
        cat.find("process", "cross @B", vendor="VendA")


def test_resolve_same_vendor_parent_first(cat):
    data = cat.resolve(cat.find("process", "0.20mm A @A1"))
    assert data["layer_height"] == "0.2"
    assert data["wall_loops"] == "3"
    assert "inherits" not in data


def test_resolve_cross_vendor_parent(cat):
    data = cat.resolve(cat.find("process", "cross @B"))
    assert data["wall_loops"] == "3"
    assert data["layer_height"] == "0.2"


def test_defaults(cat, a1):
    assert cat.defaults(a1) == ("0.20mm A @A1", ["PLA @A1"])


def test_compatible_process(cat, a1):
    assert [p.name for p in cat.compatible(a1, "process")] == [
        "0.20mm A @A1",
        "0.12mm A @A1",
        "0.16mm A @A1",
        "any printer",
    ]


def test_compatible_filament_in_subfolder(cat, a1):
    assert cat.compatible(a1, "filament")[0].name == "PLA @A1"


def test_stats(cat):
    assert cat.stats()["condition_only"] == 1
    assert cat.stats()["unrestricted"] == 1


def test_non_presets_skipped(cat):
    names = {p.name for kind in ("machine", "process", "filament") for p in cat.selectable(kind)}
    assert "template gcode" not in names
    with pytest.raises(CatalogError):
        cat.find("machine", "template gcode")


def test_missing_parent_and_cycle(tmp_path):
    proc = tmp_path / "V" / "process"
    proc.mkdir(parents=True)
    (proc / "a.json").write_text(
        '{"type": "process", "name": "a", "inherits": "b", "instantiation": "true"}'
    )
    (proc / "b.json").write_text('{"type": "process", "name": "b", "inherits": "a"}')
    (proc / "c.json").write_text(
        '{"type": "process", "name": "c", "inherits": "gone", "instantiation": "true"}'
    )
    cat = Catalog.load(tmp_path)
    with pytest.raises(CatalogError, match="cycle"):
        cat.resolve(cat.find("process", "a"))
    with pytest.raises(CatalogError, match="gone"):
        cat.resolve(cat.find("process", "c"))
