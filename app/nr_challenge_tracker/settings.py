"""Persistence for application settings stored outside the main config."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
import yaml


WindowGeometry = tuple[int, int, int, int]


class _WindowGeometry(BaseModel):
    model_config = ConfigDict(strict=True)

    x: int
    y: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class _HudSettings(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    geometry: _WindowGeometry | None = None


class _SettingsDocument(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    hud: _HudSettings | None = None


class SettingsRepository:
    """Load and save runtime settings in a YAML document."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load_hud_geometry(self) -> WindowGeometry | None:
        settings = self._read_document()
        if settings is None:
            return None
        try:
            document = _SettingsDocument.model_validate(settings)
        except ValidationError:
            return None
        geometry = document.hud.geometry if document.hud is not None else None
        if geometry is None:
            return None
        return geometry.x, geometry.y, geometry.width, geometry.height

    def save_hud_geometry(
        self, x: int, y: int, width: int, height: int
    ) -> None:
        settings = self._read_document()
        if settings is None:
            return
        hud = settings.setdefault("hud", {})
        if not isinstance(hud, dict):
            return
        hud["geometry"] = {"x": x, "y": y, "width": width, "height": height}
        temporary_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                yaml.safe_dump(settings, temporary_file, sort_keys=False)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.path)
        except OSError:
            return
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

    def _read_document(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return {}
        try:
            settings = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return None
        if settings is None:
            return {}
        return settings if isinstance(settings, dict) else None