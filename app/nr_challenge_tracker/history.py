"""Authoritative YAML persistence for session history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Any, Iterable

import yaml

from .models import NightlordVariant, Progress, Session, SessionStatus
from .streak import StreakStats, calculate_streak


SCHEMA_VERSION = 1
DEFAULT_TARGET = 100


class HistoryError(ValueError):
    """The history file could not be safely loaded or validated."""


@dataclass(frozen=True, slots=True)
class HistorySnapshot:
    sessions: tuple[Session, ...]
    stats: StreakStats


def default_history_path(project_root: Path) -> Path:
    """Return the session history path beside the project configuration."""
    return project_root / "history.yaml"


class HistoryRepository:
    """Load and atomically save session records and their derived projection."""

    def __init__(self, path: Path, default_target: int = DEFAULT_TARGET) -> None:
        if isinstance(default_target, bool) or default_target <= 0:
            raise ValueError("History target must be a positive integer")
        self.path = path
        self.default_target = default_target
        self._lock = RLock()

    def load(self) -> HistorySnapshot:
        with self._lock:
            if not self.path.exists():
                return self.save((), target=self.default_target)
            try:
                raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
                sessions, target = self._parse_document(raw)
            except (OSError, yaml.YAMLError, TypeError, KeyError, ValueError) as error:
                raise HistoryError(f"Could not load history at {self.path}: {error}") from error

            snapshot = self._snapshot(sessions, target)
            return snapshot

    def save(
        self, sessions: Iterable[Session], target: int = DEFAULT_TARGET
    ) -> HistorySnapshot:
        with self._lock:
            session_list = tuple(sessions)
            snapshot = self._snapshot(session_list, target)
            self._write_document(snapshot)
            return snapshot

    def _snapshot(
        self, sessions: tuple[Session, ...], target: int
    ) -> HistorySnapshot:
        try:
            stats = calculate_streak(sessions, target=target)
        except (TypeError, ValueError) as error:
            raise HistoryError(f"Invalid session history: {error}") from error
        return HistorySnapshot(sessions=sessions, stats=stats)

    def _parse_document(
        self, raw: Any
    ) -> tuple[tuple[Session, ...], int]:
        if not isinstance(raw, dict):
            raise HistoryError("History document must be a YAML mapping")
        if raw.get("schema_version") != SCHEMA_VERSION:
            raise HistoryError("Unsupported history schema version")

        challenge = raw.get("challenge")
        records = raw.get("sessions")
        if not isinstance(challenge, dict) or not isinstance(records, list):
            raise HistoryError("History must contain challenge and sessions")
        target = challenge.get("target")
        if isinstance(target, bool) or not isinstance(target, int) or target <= 0:
            raise HistoryError("History challenge target must be a positive integer")

        sessions: list[Session] = []
        for record in records:
            sessions.append(self._parse_session(record))
        return tuple(sessions), target

    @staticmethod
    def _parse_session(record: Any) -> Session:
        if not isinstance(record, dict):
            raise HistoryError("Each session record must be a YAML mapping")
        nightlord = record.get("nightlord")
        if nightlord is None:
            nightlord_data = {}
        elif isinstance(nightlord, dict):
            nightlord_data = nightlord
        else:
            raise HistoryError("Session Nightlord must be a mapping or null")

        hidden = nightlord_data.get("hidden", False)
        if not isinstance(hidden, bool):
            raise HistoryError("Nightlord hidden field must be a boolean")

        try:
            variant = NightlordVariant(
                nightlord_data.get("variant", NightlordVariant.UNKNOWN.value)
            )
            progress_value = record.get("progress")
            progress = Progress(progress_value) if progress_value is not None else None
            status = SessionStatus(record.get("status", SessionStatus.ACTIVE.value))
            started_at = _parse_timestamp(record.get("started_at"), "started_at")
            ended_value = record.get("ended_at")
            ended_at = (
                _parse_timestamp(ended_value, "ended_at")
                if ended_value is not None
                else None
            )
            session = Session(
                id=record["id"],
                started_at=started_at,
                ended_at=ended_at,
                nightfarer=record.get("nightfarer"),
                nightlord_name=nightlord_data.get("base_name"),
                nightlord_hidden=hidden,
                nightlord_variant=variant,
                result_nightlord_name=record.get("result_nightlord_name"),
                review_reason=record.get("review_reason"),
                progress=progress,
                status=status,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise HistoryError(f"Invalid session record: {error}") from error
        return session

    def _write_document(self, snapshot: HistorySnapshot) -> None:
        document = {
            "schema_version": SCHEMA_VERSION,
            "challenge": {
                "target": snapshot.stats.target,
                "current_streak": snapshot.stats.current_streak,
                "best_streak": snapshot.stats.best_streak,
                "total_executor_victories": snapshot.stats.total_executor_victories,
            },
            "sessions": [
                _session_to_record(session, snapshot.stats.streak_numbers)
                for session in snapshot.sessions
            ],
        }
        serialized = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
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
                temporary_file.write(serialized)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.path)
        except OSError as error:
            raise HistoryError(f"Could not save history at {self.path}: {error}") from error
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise HistoryError(f"Session {field} must be a timestamp string")
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise HistoryError(f"Session {field} is not a valid ISO timestamp") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise HistoryError(f"Session {field} must include a timezone")
    return timestamp


def _session_to_record(
    session: Session, streak_numbers: dict[str, int]
) -> dict[str, Any]:
    return {
        "id": session.id,
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "nightfarer": session.nightfarer,
        "nightlord": {
            "hidden": session.nightlord_hidden,
            "base_name": session.nightlord_name,
            "variant": session.nightlord_variant.value,
        },
        "result_nightlord_name": session.result_nightlord_name,
        "review_reason": session.review_reason,
        "progress": session.progress.value if session.progress else None,
        "status": session.status.value,
        "counts_for_streak": session.counts_for_streak,
        "streak_number": streak_numbers.get(session.id),
    }