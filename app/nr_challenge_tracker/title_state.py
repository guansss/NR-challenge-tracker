"""Desired livestream title generation and durable synchronization revision."""

from __future__ import annotations

from threading import RLock
from typing import Any

from .challenges import ChallengeAnalysis, ChallengeType
from .state import SYNC_STATES, PersistedTitleState, StateRepository


class InvalidTitleTemplateError(ValueError):
    """The configured title template cannot be formatted with current values."""


class TitleState:
    def __init__(
        self,
        repository: StateRepository,
        title_template: str,
        polling_interval_seconds: int = 5,
    ) -> None:
        self.repository = repository
        self.title_template = title_template
        self.polling_interval_seconds = polling_interval_seconds
        self._lock = RLock()
        persisted = repository.load_title_state()
        self._revision = persisted.revision
        self._desired_title = persisted.desired_title
        self._sync_status = persisted.sync_status
        self._sync_message = persisted.sync_message

    def update(self, analysis: ChallengeAnalysis) -> dict[str, Any]:
        values = _title_values(analysis)
        try:
            title = self.title_template.format(**values)
        except (KeyError, ValueError) as error:
            raise InvalidTitleTemplateError(
                f"Invalid title template: {error}"
            ) from error
        with self._lock:
            if title != self._desired_title:
                self._desired_title = title
                self._revision += 1
                self._sync_status = "sync.pending"
                self._sync_message = ""
                self._save()
            return self.view(analysis)

    def view(self, analysis: ChallengeAnalysis | None = None) -> dict[str, Any]:
        values = _title_values(analysis) if analysis else _empty_title_values()
        with self._lock:
            return {
                "schema_version": 2,
                **values,
                "challenge_type": (
                    analysis.challenge.type.value if analysis is not None else None
                ),
                "total_sessions": (
                    analysis.total_sessions if analysis is not None else None
                ),
                "total_wins": analysis.total_wins if analysis is not None else None,
                "desired_title": self._desired_title,
                "revision": self._revision,
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


def _title_values(analysis: ChallengeAnalysis | None) -> dict[str, int]:
    if analysis is None:
        return _empty_title_values()
    if analysis.challenge.type is ChallengeType.WINNING_STREAK:
        if analysis.streak is None:
            raise ValueError("Winning Streak Challenge has no streak analysis")
        return {
            "wins": 0,
            "total": 0,
            "streak": analysis.streak.current_streak,
            "goal": analysis.streak.target,
        }
    return {
        "wins": analysis.total_wins,
        "total": analysis.total_sessions,
        "streak": 0,
        "goal": 0,
    }


def _empty_title_values() -> dict[str, int]:
    return {"wins": 0, "total": 0, "streak": 0, "goal": 0}
