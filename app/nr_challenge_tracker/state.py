"""Validated persistence for mutable application state."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .history import HistoryError

SYNC_STATES = frozenset(
    {
        "sync.synced",
        "sync.pending",
        "sync.retrying",
        "sync.authentication_required",
        "sync.title_rejected",
        "sync.offline",
    }
)

WindowGeometry = tuple[int, int, int, int]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _WindowGeometry(_StrictModel):
    x: int
    y: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class _HudState(_StrictModel):
    geometry: _WindowGeometry | None = None


class PersistedTitleState(_StrictModel):
    revision: int = Field(default=0, ge=0)
    desired_title: str = ""
    sync_status: str = "sync.pending"
    sync_message: str = Field(default="", max_length=200)

    @field_validator("sync_status")
    @classmethod
    def validate_sync_status(cls, value: str) -> str:
        if value not in SYNC_STATES:
            raise ValueError("Unsupported synchronization status")
        return value


class _StateDocument(_StrictModel):
    schema_version: Literal[1] = 1
    hud: _HudState = Field(default_factory=_HudState)
    title: PersistedTitleState = Field(default_factory=PersistedTitleState)


class StateRepository:
    """Load and atomically save validated runtime state as JSON."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()
        self._document = self._load()

    def load_hud_geometry(self) -> WindowGeometry | None:
        with self._lock:
            geometry = self._document.hud.geometry
            if geometry is None:
                return None
            return geometry.x, geometry.y, geometry.width, geometry.height

    def save_hud_geometry(self, x: int, y: int, width: int, height: int) -> None:
        with self._lock:
            hud_data = self._document.hud.model_dump()
            hud_data["geometry"] = {
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            }
            document_data = self._document.model_dump()
            document_data["hud"] = hud_data
            self._save_document(_StateDocument.model_validate(document_data))

    def load_title_state(self) -> PersistedTitleState:
        with self._lock:
            return self._document.title.model_copy(deep=True)

    def save_title_state(self, title: PersistedTitleState) -> None:
        validated_title = PersistedTitleState.model_validate(title.model_dump())
        with self._lock:
            document_data = self._document.model_dump()
            document_data["title"] = validated_title.model_dump()
            self._save_document(_StateDocument.model_validate(document_data))

    def _load(self) -> _StateDocument:
        if not self.path.exists():
            return _StateDocument()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _StateDocument()
        except OSError as error:
            raise HistoryError(
                f"Could not load runtime state at {self.path}: {error}"
            ) from error
        try:
            return _StateDocument.model_validate(data)
        except ValidationError:
            return _StateDocument()

    def _save_document(self, document: _StateDocument) -> None:
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
                json.dump(document.model_dump(mode="json"), temporary_file)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.path)
            self._document = document
        except OSError as error:
            raise HistoryError(
                f"Could not save runtime state at {self.path}: {error}"
            ) from error
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError as error:
                    raise HistoryError(
                        f"Could not clean up temporary runtime state at "
                        f"{temporary_path}: {error}"
                    ) from error
