"""Desired livestream title generation and durable synchronization revision."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any

from .history import HistoryError
from .streak import StreakStats

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
class TitleState:
    def __init__(
        self,
        path: Path,
        title_template: str,
        max_characters: int,
        room_id: int | None,
        polling_interval_seconds: int = 5,
    ) -> None:
        self.path = path
        self.title_template = title_template
        self.max_characters = max_characters
        self.room_id = room_id
        self.polling_interval_seconds = polling_interval_seconds
        self._lock = RLock()
        self._revision = 0
        self._desired_title = ""
        self._sync_status = "sync.pending"
        self._sync_message = ""
        self._load()

    def update(self, stats: StreakStats) -> dict[str, Any]:
        try:
            title = self.title_template.format(
                current_streak=stats.current_streak,
                target=stats.target,
            )
        except (KeyError, ValueError) as error:
            raise ValueError(f"Invalid title template: {error}") from error
        if len(title) > self.max_characters:
            raise ValueError(
                f"Desired title exceeds configured limit of {self.max_characters} characters"
            )
        with self._lock:
            if title != self._desired_title:
                self._desired_title = title
                self._revision += 1
                self._sync_status = "sync.pending"
                self._sync_message = ""
                self._save()
            return self.view(stats)

    def view(self, stats: StreakStats | None = None) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": 1,
                "current_streak": stats.current_streak if stats else None,
                "target": stats.target if stats else None,
                "desired_title": self._desired_title,
                "revision": self._revision,
                "room_id": self.room_id,
                "polling_interval_seconds": self.polling_interval_seconds,
                "sync_status": self._sync_status,
                "sync_message": self._sync_message,
            }

    def report_sync(self, status: str, revision: int, message: str = "") -> bool:
        if not isinstance(status, str) or status not in SYNC_STATES:
            raise ValueError("Unsupported synchronization status")
        if not isinstance(message, str) or len(message) > 200:
            raise ValueError("Synchronization message must be at most 200 characters")
        with self._lock:
            if isinstance(revision, bool) or revision != self._revision:
                return False
            self._sync_status = status
            self._sync_message = message
            self._save()
            return True

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("title state must be an object")
            revision = data.get("revision")
            title = data.get("desired_title")
            status = data.get("sync_status", "sync.pending")
            if (
                isinstance(revision, bool)
                or not isinstance(revision, int)
                or revision < 0
                or not isinstance(title, str)
                or not isinstance(status, str)
                or status not in SYNC_STATES
            ):
                raise ValueError("invalid title state fields")
            self._revision = revision
            self._desired_title = title
            self._sync_status = status
            self._sync_message = str(data.get("sync_message", ""))[:200]
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise HistoryError(
                f"Could not load title state at {self.path}: {error}"
            ) from error

    def _save(self) -> None:
        document = {
            "revision": self._revision,
            "desired_title": self._desired_title,
            "sync_status": self._sync_status,
            "sync_message": self._sync_message,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(document, temporary_file, ensure_ascii=False)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.path)
        except OSError as error:
            raise HistoryError(
                f"Could not save title state at {self.path}: {error}"
            ) from error
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
