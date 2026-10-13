"""Server configuration from CREALITYPRINT_* environment variables."""

import os
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CREALITYPRINT_")

    app: Path = Path("~/Applications/CrealityPrint/squashfs-root/AppRun")
    profiles: Path | None = None
    output: Path = Path("~/.cache/creality-mcp/jobs")
    default_printer: str = "Creality K2 Plus 0.4 nozzle"
    timeout_s: int = Field(default=600, ge=1)
    max_jobs: int = Field(default=50, ge=1)

    @field_validator("app", "profiles", "output")
    @classmethod
    def _expand(cls, value: Path | None) -> Path | None:
        return value.expanduser() if value is not None else None

    @property
    def profiles_dir(self) -> Path:
        return self.profiles or self.app.parent / "resources" / "profiles"


def check_install(s: Settings) -> str | None:
    """None when the slicer and its presets are in place; else a message naming the variable."""
    if not (s.app.is_file() and os.access(s.app, os.X_OK)):
        return f"CrealityPrint binary not found at {s.app}; set CREALITYPRINT_APP"
    if not s.profiles_dir.is_dir():
        return f"CrealityPrint presets not found at {s.profiles_dir}; set CREALITYPRINT_PROFILES"
    return None
