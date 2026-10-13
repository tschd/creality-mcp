import json
from pathlib import Path

import pytest
from mcp.client import Client

from creality_mcp.server import TOOL_NAMES, build_server
from creality_mcp.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        app=FIXTURES / "fake_slicer.py",
        profiles=FIXTURES / "profiles",
        output=tmp_path / "jobs",
        timeout_s=5,
        default_printer="A1 0.4 nozzle",
    )


@pytest.fixture
def server(settings):
    return build_server(settings)


@pytest.fixture
def cube(tmp_path):
    path = tmp_path / "cube.stl"
    path.write_text("solid cube\nendsolid cube\n")
    return path


def payload(result):
    """A dict return comes back as JSON text; a list return as structured {"result": [...]}."""
    if result.structured_content is not None and "result" in result.structured_content:
        return result.structured_content["result"]
    return json.loads(result.content[0].text)


async def test_tool_names(server):
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == TOOL_NAMES


async def test_list_printers(server):
    async with Client(server) as client:
        result = await client.call_tool("list_printers", {"query": "a1"})
    items = payload(result)
    assert [(i["name"], i["vendor"]) for i in items] == [
        ("A1 0.4 nozzle", "VendA"),
        ("A1 0.4 nozzle", "VendB"),
    ]
    assert items[0]["model"] == "A1"
    assert items[0]["nozzle"] == "0.4"


async def test_list_presets_needs_vendor(server):
    async with Client(server) as client:
        shared = await client.call_tool(
            "list_presets", {"printer": "A1 0.4 nozzle", "kind": "process"}
        )
        ok = await client.call_tool(
            "list_presets", {"printer": "A1 0.4 nozzle", "kind": "process", "vendor": "VendA"}
        )
    assert shared.is_error is True
    assert "VendA" in shared.content[0].text
    assert "VendB" in shared.content[0].text
    assert payload(ok)[0] == {"name": "0.20mm A @A1", "vendor": "VendA"}


async def test_get_preset_keys(server):
    args = {"kind": "process", "name": "0.20mm A @A1", "vendor": "VendA"}
    async with Client(server) as client:
        ok = await client.call_tool("get_preset", {**args, "keys": ["layer_height"]})
        bad = await client.call_tool("get_preset", {**args, "keys": ["layer_hieght"]})
    assert payload(ok) == {"layer_height": "0.2"}
    assert bad.is_error is True
    assert "layer_height" in bad.content[0].text


async def test_slice_model(server, cube, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "ok")
    async with Client(server) as client:
        result = await client.call_tool("slice_model", {"models": [str(cube)], "vendor": "VendA"})
    assert result.is_error is False
    data = payload(result)
    assert isinstance(data["plates"][0]["print_time_s"], int)
    assert data["used"]["process"] == "0.20mm A @A1"


async def test_slice_model_error(server, cube, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "rc17")
    async with Client(server) as client:
        result = await client.call_tool("slice_model", {"models": [str(cube)], "vendor": "VendA"})
    assert result.is_error is True
    assert "-17" in result.content[0].text


async def test_read_gcode_summary(server):
    path = FIXTURES / "gcode" / "creality_k2.gcode"
    async with Client(server) as client:
        result = await client.call_tool("read_gcode_summary", {"path": str(path)})
    assert payload(result)["layers"] > 0


async def test_missing_app(tmp_path):
    server = build_server(Settings(app=tmp_path / "nope" / "AppRun", output=tmp_path / "jobs"))
    async with Client(server) as client:
        result = await client.call_tool("list_printers", {})
    assert result.is_error is True
    assert "CREALITYPRINT_APP" in result.content[0].text
