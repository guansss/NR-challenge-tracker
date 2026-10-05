"""Desired livestream title generation and durable synchronization revision."""

from __future__ import annotations

from threading import RLock
from typing import Any

from .state import SYNC_STATES, PersistedTitleState, StateRepository
from .streak import StreakStats


class TitleState:
    def __init__(
        self,
        repository: StateRepository,
        title_template: str,
        max_characters: int,
        room_id: int | None,
        polling_interval_seconds: int = 5,
    ) -> None:
        self.repository = repository
        self.title_template = title_template
        self.max_characters = max_characters
        self.room_id = room_id
        self.polling_interval_seconds = polling_interval_seconds
        self._lock = RLock()
        persisted = repository.load_title_state()
        self._revision = persisted.revision
        self._desired_title = persisted.desired_title
        self._sync_status = persisted.sync_status
        self._sync_message = persisted.sync_message

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

    def _save(self) -> None:
        self.repository.save_title_state(
            PersistedTitleState(
                revision=self._revision,
                desired_title=self._desired_title,
                sync_status=self._sync_status,
                sync_message=self._sync_message,
            )
        )
