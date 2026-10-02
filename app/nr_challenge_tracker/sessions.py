"""Serialized, validated session lifecycle and history updates."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from threading import RLock
from typing import Iterable
from uuid import uuid4

from .history import HistoryRepository, HistorySnapshot
from .models import NightlordVariant, Progress, Session, SessionStatus


ACTIVE_STATUSES = {
    SessionStatus.ACTIVE,
    SessionStatus.AWAITING_RESULT,
    SessionStatus.INTERRUPTED,
}
FINAL_OUTCOMES = {
    Progress.DAY_1,
    Progress.DAY_2,
    Progress.DAY_3,
    Progress.DAY_3_VICTORY,
}


class SessionTransitionError(ValueError):
    """A requested transition is invalid for the current session state."""


class SessionService:
    """Own lifecycle transitions and persist each accepted change atomically."""

    def __init__(
        self,
        repository: HistoryRepository,
        everdark_nightlords: Iterable[str] | None = None,
    ) -> None:
        self._repository = repository
        self._everdark_nightlords = (
            {name.strip().casefold() for name in everdark_nightlords}
            if everdark_nightlords is not None
            else None
        )
        initial = repository.load()
        self._sessions = list(initial.sessions)
        self._target = initial.stats.target
        self._lock = RLock()
        recovered = [
            replace(session, status=SessionStatus.INTERRUPTED)
            if session.status in {SessionStatus.ACTIVE, SessionStatus.AWAITING_RESULT}
            else session
            for session in self._sessions
        ]
        if recovered != self._sessions:
            self._commit(recovered)

    @property
    def snapshot(self) -> HistorySnapshot:
        with self._lock:
            return self._repository._snapshot(tuple(self._sessions), self._target)

    def interrupt_active_sessions(self) -> None:
        with self._lock:
            candidate = [
                replace(session, status=SessionStatus.INTERRUPTED)
                if session.status in {SessionStatus.ACTIVE, SessionStatus.AWAITING_RESULT}
                else session
                for session in self._sessions
            ]
            if candidate != self._sessions:
                self._commit(candidate)

    def start_session(
        self,
        *,
        nightfarer: str,
        nightlord_name: str | None,
        hidden_nightlord: bool,
        started_at: datetime,
    ) -> Session:
        if not isinstance(nightfarer, str) or not nightfarer.strip():
            raise SessionTransitionError("A confirmed Nightfarer is required")
        if not hidden_nightlord and not (nightlord_name or "").strip():
            raise SessionTransitionError(
                "A Nightlord identity or hidden-Nightlord marker is required"
            )
        session = Session(
            id=str(uuid4()),
            started_at=started_at,
            nightfarer=nightfarer,
            nightlord_name=nightlord_name,
            nightlord_hidden=hidden_nightlord,
            status=SessionStatus.ACTIVE,
        )
        with self._lock:
            if any(existing.status in ACTIVE_STATUSES for existing in self._sessions):
                raise SessionTransitionError("An active session already exists")
            self._commit([*self._sessions, session])
        return session

    def set_awaiting_result(self, session_id: str) -> Session:
        return self._update_status(
            session_id,
            expected={SessionStatus.ACTIVE},
            status=SessionStatus.AWAITING_RESULT,
        )

    def resume_gameplay(self, session_id: str) -> Session:
        return self._update_status(
            session_id,
            expected={SessionStatus.AWAITING_RESULT},
            status=SessionStatus.ACTIVE,
        )

    def interrupt(self, session_id: str) -> Session:
        return self._update_status(
            session_id,
            expected={SessionStatus.ACTIVE, SessionStatus.AWAITING_RESULT},
            status=SessionStatus.INTERRUPTED,
        )

    def resume_interrupted(self, session_id: str) -> Session:
        return self._update_status(
            session_id,
            expected={SessionStatus.INTERRUPTED},
            status=SessionStatus.ACTIVE,
        )

    def update_preparation(
        self,
        session_id: str,
        *,
        nightfarer: str,
        nightlord_name: str | None,
        hidden_nightlord: bool,
    ) -> Session:
        if not isinstance(nightfarer, str) or not nightfarer.strip():
            raise SessionTransitionError("A confirmed Nightfarer is required")
        if not hidden_nightlord and not (nightlord_name or "").strip():
            raise SessionTransitionError(
                "A Nightlord identity or hidden-Nightlord marker is required"
            )
        with self._lock:
            session = self._find(session_id)
            if session.status not in {SessionStatus.ACTIVE, SessionStatus.AWAITING_RESULT}:
                raise SessionTransitionError(
                    f"Cannot update preparation for a session in state {session.status.value}"
                )
            if (
                session.nightfarer == nightfarer
                and session.nightlord_name == nightlord_name
                and session.nightlord_hidden == hidden_nightlord
            ):
                return session
            updated = replace(
                session,
                nightfarer=nightfarer,
                nightlord_name=nightlord_name,
                nightlord_hidden=hidden_nightlord,
            )
            self._replace_and_commit(updated)
            return updated

    def finalize_result(
        self,
        session_id: str,
        *,
        progress: Progress | None,
        ended_at: datetime,
        nightlord_name: str | None = None,
        variant: NightlordVariant = NightlordVariant.UNKNOWN,
    ) -> Session:
        with self._lock:
            session = self._find(session_id)
            if session.status not in ACTIVE_STATUSES:
                raise SessionTransitionError(
                    f"Cannot finalize a session in state {session.status.value}"
                )
            self._validate_variant(nightlord_name or session.nightlord_name, variant)

            conflict = (
                session.nightlord_name is not None
                and nightlord_name is not None
                and session.nightlord_name.strip().casefold()
                != nightlord_name.strip().casefold()
            )
            outcome_known = progress in FINAL_OUTCOMES
            hidden_identity_missing = session.nightlord_hidden and not nightlord_name
            reason = None
            if conflict:
                reason = (
                    f"Nightlord identity conflict: preparation showed "
                    f"{session.nightlord_name}, result showed {nightlord_name}"
                )
            elif not outcome_known:
                reason = "Final progress could not be confidently recognized"
            elif hidden_identity_missing:
                reason = "Hidden Nightlord identity could not be recognized"

            updated = replace(
                session,
                ended_at=ended_at,
                nightlord_name=(
                    session.nightlord_name
                    if conflict
                    else nightlord_name or session.nightlord_name
                ),
                nightlord_variant=variant,
                result_nightlord_name=nightlord_name,
                progress=progress,
                status=(
                    SessionStatus.UNRESOLVED
                    if conflict or not outcome_known or hidden_identity_missing
                    else SessionStatus.COMPLETED
                ),
                review_reason=reason,
            )
            self._replace_and_commit(updated)
            return updated

    def resolve_session(
        self,
        session_id: str,
        *,
        nightfarer: str | None,
        nightlord_name: str | None,
        variant: NightlordVariant,
        progress: Progress,
        started_at: datetime | None = None,
        ended_at: datetime,
    ) -> Session:
        if progress not in FINAL_OUTCOMES:
            raise SessionTransitionError("Manual resolution requires an explicit outcome")
        with self._lock:
            session = self._find(session_id)
            if session.status is SessionStatus.DISCARDED:
                raise SessionTransitionError("Discarded sessions cannot be resolved")
            self._validate_variant(nightlord_name, variant)
            updated = replace(
                session,
                started_at=started_at or session.started_at,
                nightfarer=nightfarer,
                nightlord_name=nightlord_name,
                nightlord_variant=variant,
                progress=progress,
                ended_at=ended_at,
                status=SessionStatus.COMPLETED,
                review_reason=None,
            )
            self._replace_and_commit(updated)
            return updated

    def discard_session(self, session_id: str) -> Session:
        with self._lock:
            session = self._find(session_id)
            if session.status is SessionStatus.DISCARDED:
                return session
            updated = replace(session, status=SessionStatus.DISCARDED)
            self._replace_and_commit(updated)
            return updated

    def _update_status(
        self,
        session_id: str,
        *,
        expected: set[SessionStatus],
        status: SessionStatus,
    ) -> Session:
        with self._lock:
            session = self._find(session_id)
            if session.status not in expected:
                raise SessionTransitionError(
                    f"Cannot transition {session.status.value} to {status.value}"
                )
            updated = replace(session, status=status)
            self._replace_and_commit(updated)
            return updated

    def _replace_and_commit(self, updated: Session) -> None:
        candidate = [
            updated if session.id == updated.id else session
            for session in self._sessions
        ]
        self._commit(candidate)

    def _commit(self, candidate: Iterable[Session]) -> None:
        snapshot = self._repository.save(candidate, target=self._target)
        self._sessions = list(snapshot.sessions)

    def _find(self, session_id: str) -> Session:
        for session in self._sessions:
            if session.id == session_id:
                return session
        raise KeyError(f"Unknown session: {session_id}")

    def _validate_variant(
        self, nightlord_name: str | None, variant: NightlordVariant
    ) -> None:
        if (
            variant is NightlordVariant.EVERDARK
            and self._everdark_nightlords is not None
            and (nightlord_name or "").strip().casefold()
            not in self._everdark_nightlords
        ):
            raise SessionTransitionError(
                "This Nightlord does not have a confirmed Everdark variant"
            )