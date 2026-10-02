"""Core domain types shared by the tracker services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SessionStatus(str, Enum):
    ACTIVE = "active"
    AWAITING_RESULT = "awaiting_result"
    INTERRUPTED = "interrupted"
    UNRESOLVED = "unresolved"
    COMPLETED = "completed"
    DISCARDED = "discarded"


class Progress(str, Enum):
    DAY_1 = "day_1"
    DAY_2 = "day_2"
    DAY_3 = "day_3"
    DAY_3_VICTORY = "day_3_victory"
    UNKNOWN = "unknown"


class NightlordVariant(str, Enum):
    NORMAL = "normal"
    EVERDARK = "everdark"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Session:
    """A recorded attempt; streak-affecting values are finalized separately."""

    id: str
    started_at: datetime
    ended_at: datetime | None = None
    nightfarer: str | None = None
    nightlord_name: str | None = None
    nightlord_hidden: bool = False
    nightlord_variant: NightlordVariant = NightlordVariant.UNKNOWN
    result_nightlord_name: str | None = None
    review_reason: str | None = None
    progress: Progress | None = None
    status: SessionStatus = SessionStatus.ACTIVE

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Session id must not be empty")
        if not isinstance(self.started_at, datetime):
            raise TypeError("Session start time must be a datetime")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("Session start time must include a timezone")
        if self.ended_at is not None:
            if not isinstance(self.ended_at, datetime):
                raise TypeError("Session end time must be a datetime or None")
            if self.ended_at.tzinfo is None or self.ended_at.utcoffset() is None:
                raise ValueError("Session end time must include a timezone")
            if self.ended_at < self.started_at:
                raise ValueError("Session end time cannot precede its start time")
        if not isinstance(self.status, SessionStatus):
            raise TypeError("Session status must be a SessionStatus")
        if self.nightfarer is not None and not isinstance(self.nightfarer, str):
            raise TypeError("Nightfarer must be a string or None")
        if self.nightlord_name is not None and not isinstance(self.nightlord_name, str):
            raise TypeError("Nightlord name must be a string or None")
        if not isinstance(self.nightlord_hidden, bool):
            raise TypeError("Nightlord hidden flag must be a boolean")
        if self.result_nightlord_name is not None and not isinstance(
            self.result_nightlord_name, str
        ):
            raise TypeError("Result Nightlord name must be a string or None")
        if self.review_reason is not None and not isinstance(self.review_reason, str):
            raise TypeError("Review reason must be a string or None")
        if self.status is SessionStatus.COMPLETED and self.ended_at is None:
            raise ValueError("Completed sessions must have an end time")
        if self.progress is not None and not isinstance(self.progress, Progress):
            raise TypeError("Session progress must be a Progress or None")
        if not isinstance(self.nightlord_variant, NightlordVariant):
            raise TypeError("Nightlord variant must be a NightlordVariant")

    @property
    def counts_for_streak(self) -> bool:
        """Whether this finalized Executor record has a known final outcome."""
        return (
            self.status is SessionStatus.COMPLETED
            and (self.nightfarer or "").strip().casefold() == "executor"
            and self.progress in {
                Progress.DAY_1,
                Progress.DAY_2,
                Progress.DAY_3,
                Progress.DAY_3_VICTORY,
            }
        )