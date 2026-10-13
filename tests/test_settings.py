from pathlib import Path

import pytest

from creality_mcp.settings import Settings, check_install


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("APP", "PROFILES", "OUTPUT", "DEFAULT_PRINTER", "TIMEOUT_S", "MAX_JOBS"):
        monkeypatch.delenv(f"CREALITYPRINT_{var}", raising=False)


def test_profiles_dir_beside_app(monkeypatch):
    monkeypatch.setenv("CREALITYPRINT_APP", "/opt/x/AppRun")
    assert Settings().profiles_dir == Path("/opt/x/resources/profiles")


def test_output_expands_user(monkeypatch):
    monkeypatch.setenv("CREALITYPRINT_OUTPUT", "~/jobs")
    assert Settings().output == Path.home() / "jobs"


def test_defaults():
    s = Settings()
    assert s.default_printer == "Creality K2 Plus 0.4 nozzle"
    assert s.app == Path.home() / "Applications/CrealityPrint/squashfs-root/AppRun"


def test_check_install_missing_app(tmp_path):
    msg = check_install(Settings(app=tmp_path / "nope" / "AppRun"))
    assert msg is not None
    assert "CREALITYPRINT_APP" in msg


def _make_app(tmp_path: Path) -> Path:
    app = tmp_path / "AppRun"
    app.write_text("#!/bin/sh\n")
    app.chmod(0o755)
    return app


def test_check_install_ok(tmp_path):
    app = _make_app(tmp_path)
    (tmp_path / "resources" / "profiles").mkdir(parents=True)
    assert check_install(Settings(app=app)) is None


def test_check_install_missing_profiles(tmp_path):
    msg = check_install(Settings(app=_make_app(tmp_path)))
    assert msg is not None
    assert "CREALITYPRINT_PROFILES" in msg
