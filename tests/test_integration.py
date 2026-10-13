"""Real slices with the CrealityPrint AppImage, and the server over real stdio.

Skipped when the AppImage is not installed. Run alone: `pytest -m slicer`.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from creality_mcp.catalog import Catalog
from creality_mcp.settings import Settings
from creality_mcp.slicer import SliceError, SliceRequest, run_slice

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).parent.parent
K2 = "Creality K2 Plus 0.4 nozzle"

_app = Settings().app
pytestmark = [
    pytest.mark.slicer,
    pytest.mark.skipif(
        not (_app.is_file() and os.access(_app, os.X_OK)), reason=f"no AppImage at {_app}"
    ),
]


@pytest.fixture(scope="module")
def catalog():
    return Catalog.load(Settings().profiles_dir)


@pytest.fixture
def settings(tmp_path):
    return Settings(output=tmp_path / "jobs", default_printer=K2)


@pytest.fixture
def cube(tmp_path):
    return Path(shutil.copy(FIXTURES / "cube.stl", tmp_path / "cube.stl"))


def config_value(gcode_path: str, key: str) -> str | None:
    pattern = re.compile(rf"^; {re.escape(key)} = (.*)$")
    with open(gcode_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if m := pattern.match(line.rstrip("\n")):
                return m[1]
    return None


def test_k2_defaults(settings, catalog, cube):
    result = run_slice(SliceRequest(models=[str(cube)]), settings, catalog)
    assert result.used["printer"] == K2
    assert result.used["process"] == "0.20mm Standard @Creality K2 Plus 0.4 nozzle"
    assert result.used["filaments"] == ["Hyper PLA @Creality K2 Plus 0.4 nozzle"]
    assert result.plates[0].print_time_s > 0
    assert result.missing_stats == []


def test_overrides_reach_gcode(settings, catalog, cube):
    req = SliceRequest(
        models=[str(cube)], overrides={"layer_height": 0.28, "enable_arc_fitting": False}
    )
    gcode = run_slice(req, settings, catalog).plates[0].gcode_path
    assert config_value(gcode, "layer_height") == "0.28"
    assert config_value(gcode, "enable_arc_fitting") == "0"


def test_path_with_space_and_non_ascii(settings, catalog, cube):
    model = cube.rename(cube.with_name("cube (ñ) 1.stl"))
    result = run_slice(SliceRequest(models=[str(model)]), settings, catalog)
    assert result.plates[0].print_time_s > 0


def test_two_filaments(settings, catalog, cube):
    req = SliceRequest(
        models=[str(cube), str(cube)],
        filaments=[
            "Hyper PLA @Creality K2 Plus 0.4 nozzle",
            "CR-PLA @Creality K2 Plus 0.4 nozzle",
        ],
        filament_ids=[1, 2],
    )
    mm = run_slice(req, settings, catalog).plates[0].filament_mm
    assert mm is not None
    assert len(mm) == 2
    assert all(v > 0 for v in mm)


def test_bbl_x1c(settings, catalog, cube):
    req = SliceRequest(models=[str(cube)], printer="Bambu Lab X1 Carbon 0.4 nozzle")
    assert run_slice(req, settings, catalog).plates[0].print_time_s > 0


def test_3mf_override(settings, catalog, tmp_path):
    model = shutil.copy(FIXTURES / "simple-box.3mf", tmp_path / "simple-box.3mf")
    req = SliceRequest(models=[str(model)], overrides={"layer_height": 0.28})
    result = run_slice(req, settings, catalog)
    assert config_value(result.plates[0].gcode_path, "layer_height") == "0.28"
    assert result.used["printer"]
    assert result.used["process"]


def test_unknown_printer(settings, catalog, cube):
    with pytest.raises(SliceError):
        run_slice(SliceRequest(models=[str(cube)], printer="Creality K9"), settings, catalog)


def test_3mf_with_printer_refused(settings, catalog, tmp_path):
    model = shutil.copy(FIXTURES / "simple-box.3mf", tmp_path / "simple-box.3mf")
    with pytest.raises(SliceError, match="3MF"):
        run_slice(SliceRequest(models=[str(model)], printer=K2), settings, catalog)


def test_cli_does_not_run_post_process(settings, catalog, cube, tmp_path):
    # A downloaded 3MF can carry post_process in its stored settings. The tested CLI keeps
    # the value but never runs it (only the GUI does); pin that, since 3MF presets pass
    # through unchecked.
    marker = tmp_path / "RAN"
    hook = tmp_path / "hook.sh"
    hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    hook.chmod(0o755)
    machine = catalog.find("machine", K2)
    process_name, filament_names = catalog.defaults(machine)
    process = catalog.find("process", process_name, machine.vendor)
    filament = catalog.find("filament", filament_names[0], machine.vendor)
    out = tmp_path / "out"
    out.mkdir()
    argv = [
        str(settings.app),
        "--cli",
        "--slice",
        "0",
        "--need-gcode-file",
        "--outputdir",
        str(out),
        "--load-settings",
        f"{machine.path};{process.path}",
        "--load-filaments",
        str(filament.path),
        f"--post-process={hook}",
        str(cube),
    ]
    subprocess.run(argv, cwd=out, capture_output=True, timeout=300, check=False)
    assert json.loads((out / "result.json").read_text())["return_code"] == 0
    assert not marker.exists()


async def test_stdio_smoke(tmp_path, cube):
    # The stdio client passes only a safe-list of env variables, so set the output here.
    params = StdioServerParameters(
        command="uv",
        args=["run", "--directory", str(REPO), "creality-mcp"],
        env={"CREALITYPRINT_OUTPUT": str(tmp_path / "jobs")},
    )
    with open(tmp_path / "err.log", "w") as errlog:
        async with Client(stdio_client(params, errlog=errlog)) as client:
            printers = await client.call_tool("list_printers", {"query": "K2 Plus"})
            sliced = await client.call_tool("slice_model", {"models": [str(cube)]})
    names = [p["name"] for p in printers.structured_content["result"]]
    assert names == [f"Creality K2 Plus {n} nozzle" for n in ("0.2", "0.4", "0.6", "0.8")]
    assert sliced.is_error is False
    assert json.loads(sliced.content[0].text)["plates"][0]["print_time_s"] > 0
    # A stray stdout print only logs here; it does not fail the call.
    assert "Failed to parse" not in (tmp_path / "err.log").read_text()
