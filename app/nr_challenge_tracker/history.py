"""Authoritative YAML persistence for session history."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Any

import yaml

from .models import NightlordVariant, Progress, Session, SessionStatus
from .streak import StreakStats, calculate_streak

SCHEMA_VERSION = 2


class HistoryError(ValueError):
    """The history file could not be safely loaded or validated."""


@dataclass(frozen=True, slots=True)
class HistorySnapshot:
    sessions: tuple[Session, ...]
    # Compatibility projection for callers that have not adopted Challenges.
    stats: StreakStats = field(
        default_factory=lambda: StreakStats(0, 0, 0, 100, {})
    )


def default_history_path(project_root: Path) -> Path:
    return project_root / "history.yaml"


class HistoryRepository:
    """Load and atomically save authoritative session records only."""

    def __init__(
        self,
        path: Path,
        default_target: int = 100,
        *,
        eligible_nightfarer: str | None = None,
    ) -> None:
        self.path = path
        self._legacy_target = default_target
        self._legacy_nightfarer = eligible_nightfarer
        self._lock = RLock()

    def load(self) -> HistorySnapshot:
        with self._lock:
            if not self.path.exists():
                return self.save(())
            try:
                raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
                sessions, legacy = self._parse_document(raw)
            except (OSError, yaml.YAMLError, TypeError, KeyError, ValueError) as error:
                raise HistoryError(f"Could not load history at {self.path}: {error}") from error
            snapshot = self._snapshot(sessions)
            if legacy:
                self._write_document(snapshot)
            return snapshot

    def save(self, sessions: Iterable[Session], target: int | None = None) -> HistorySnapshot:
        with self._lock:
            if target is not None:
                self._legacy_target = target
            snapshot = self._snapshot(tuple(sessions))
            self._validate_unique_ids(snapshot.sessions)
            self._write_document(snapshot)
            return snapshot

    def _snapshot(self, sessions: tuple[Session, ...]) -> HistorySnapshot:
        if self._legacy_nightfarer is None:
            return HistorySnapshot(sessions)
        return HistorySnapshot(
            sessions,
            calculate_streak(
                sessions,
                target=self._legacy_target,
                eligible_nightfarer=self._legacy_nightfarer,
            ),
        )

    def _parse_document(self, raw: Any) -> tuple[tuple[Session, ...], bool]:
        if not isinstance(raw, dict):
            raise HistoryError("History document must be a YAML mapping")
        version = raw.get("schema_version")
        if version not in {1, SCHEMA_VERSION}:
            raise HistoryError("Unsupported history schema version")
        records = raw.get("sessions")
        if not isinstance(records, list):
            raise HistoryError("History must contain sessions")
        sessions = tuple(self._parse_session(record) for record in records)
        self._validate_unique_ids(sessions)
        return sessions, version == 1

    @staticmethod
    def _validate_unique_ids(sessions: tuple[Session, ...]) -> None:
        if len({session.id for session in sessions}) != len(sessions):
            raise HistoryError("Session ids must be unique")

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
            return Session(
                id=record["id"],
                started_at=_parse_timestamp(record.get("started_at"), "started_at"),
                ended_at=_parse_timestamp(record["ended_at"], "ended_at") if record.get("ended_at") is not None else None,
                nightfarer=record.get("nightfarer"),
                nightlord_name=nightlord_data.get("base_name"),
                nightlord_hidden=hidden,
                nightlord_variant=NightlordVariant(nightlord_data.get("variant", NightlordVariant.UNKNOWN.value)),
                result_nightlord_name=record.get("result_nightlord_name"),
                review_reason=record.get("review_reason"),
                progress=Progress(record["progress"]) if record.get("progress") is not None else None,
                status=SessionStatus(record.get("status", SessionStatus.ACTIVE.value)),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise HistoryError(f"Invalid session record: {error}") from error

    def _write_document(self, snapshot: HistorySnapshot) -> None:
        document = {"schema_version": SCHEMA_VERSION, "sessions": [_session_to_record(session) for session in snapshot.sessions]}
        serialized = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp", delete=False) as temporary_file:
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


def _session_to_record(session: Session) -> dict[str, Any]:
    return {
        "id": session.id,
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "nightfarer": session.nightfarer,
        "nightlord": {"hidden": session.nightlord_hidden, "base_name": session.nightlord_name, "variant": session.nightlord_variant.value},
        "result_nightlord_name": session.result_nightlord_name,
        "review_reason": session.review_reason,
        "progress": session.progress.value if session.progress else None,
        "status": session.status.value,
    }
