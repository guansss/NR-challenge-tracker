"""Runtime-only Challenge definitions and session analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping

from .models import Progress, Session, SessionStatus
from .streak import StreakStats, calculate_streak


class ChallengeType(str, Enum):
    NORMAL = "normal"
    WINNING_STREAK = "winning_streak"


@dataclass(frozen=True, slots=True)
class Challenge:
    id: str
    name: str
    type: ChallengeType
    excluded_session_ids: frozenset[str] = field(default_factory=frozenset)
    eligible_nightfarer: str | None = None
    target: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Challenge id must be a non-empty string")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Challenge name must be a non-empty string")
        if not isinstance(self.type, ChallengeType):
            raise TypeError("Challenge type must be a ChallengeType")
        if any(not isinstance(value, str) or not value.strip() for value in self.excluded_session_ids):
            raise ValueError("Excluded session ids must be non-empty strings")
        if self.type is ChallengeType.NORMAL:
            if self.eligible_nightfarer is not None or self.target is not None:
                raise ValueError("Normal Challenges cannot have streak settings")
        else:
            if not isinstance(self.eligible_nightfarer, str) or not self.eligible_nightfarer.strip():
                raise ValueError("Winning Streak Challenges require an eligible Nightfarer")
            if isinstance(self.target, bool) or not isinstance(self.target, int) or self.target <= 0:
                raise ValueError("Winning Streak Challenge target must be a positive integer")


@dataclass(frozen=True, slots=True)
class ChallengeAnalysis:
    challenge: Challenge
    total_sessions: int
    total_wins: int
    streak: StreakStats | None = None

    @property
    def streak_numbers(self) -> Mapping[str, int]:
        return self.streak.streak_numbers if self.streak is not None else {}


def analyze_challenge(
    sessions: Iterable[Session], challenge: Challenge
) -> ChallengeAnalysis:
    """Derive one Challenge's display data without changing session history."""
    included = tuple(
        session
        for session in sessions
        if session.id not in challenge.excluded_session_ids
    )
    total_sessions = len(included)
    if challenge.type is ChallengeType.NORMAL:
        return ChallengeAnalysis(
            challenge=challenge,
            total_sessions=total_sessions,
            total_wins=sum(
                session.status is SessionStatus.COMPLETED
                and session.progress is Progress.DAY_3_VICTORY
                for session in included
            ),
        )
    streak = calculate_streak(
        included,
        target=challenge.target,
        eligible_nightfarer=challenge.eligible_nightfarer or "",
    )
    return ChallengeAnalysis(
        challenge=challenge,
        total_sessions=total_sessions,
        total_wins=streak.total_eligible_victories,
        streak=streak,
    )
