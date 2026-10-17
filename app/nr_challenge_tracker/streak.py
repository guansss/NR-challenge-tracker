"""Pure streak projection from authoritative session records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from typing import Iterable, Mapping

from .models import Progress, Session


@dataclass(frozen=True, slots=True)
class StreakStats:
    current_streak: int
    best_streak: int
    total_eligible_victories: int
    target: int
    streak_numbers: Mapping[str, int]
    current_streak_session_ids: frozenset[str] = frozenset()


def calculate_streak(
    sessions: Iterable[Session],
    target: int = 100,
    *,
    eligible_nightfarer: str,
    initial_current_streak: int = 0,
    initial_best_streak: int = 0,
) -> StreakStats:
    """Recompute challenge statistics and historical victory labels.

    Completed outcomes for the eligible Nightfarer are applied in end-time
    order. Unknown, unresolved, interrupted, and discarded sessions have no effect.
    """
    if isinstance(target, bool) or not isinstance(target, int) or target < 0:
        raise ValueError("Streak target must be a non-negative integer")
    for name, value in (
        ("Initial current streak", initial_current_streak),
        ("Initial best streak", initial_best_streak),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if initial_best_streak < initial_current_streak:
        raise ValueError("Initial best streak cannot be lower than initial current streak")
    session_list = list(sessions)
    session_ids = [session.id for session in session_list]
    if len(session_ids) != len(set(session_ids)):
        raise ValueError("Session ids must be unique")

    eligible = [
        session
        for session in session_list
        if session.counts_for_streak(eligible_nightfarer)
    ]
    eligible.sort(
        key=lambda session: (
            session.ended_at.astimezone(timezone.utc),
            session.started_at.astimezone(timezone.utc),
            session.id,
        )
    )

    current = initial_current_streak
    best = initial_best_streak
    total_victories = 0
    streak_numbers: dict[str, int] = {}
    current_streak_session_ids: set[str] = set()
    for session in eligible:
        if session.progress is Progress.DAY_3_VICTORY:
            current += 1
            best = max(best, current)
            total_victories += 1
            streak_numbers[session.id] = current
            current_streak_session_ids.add(session.id)
        else:
            current = 0
            current_streak_session_ids.clear()

    return StreakStats(
        current_streak=current,
        best_streak=best,
        total_eligible_victories=total_victories,
        target=target,
        streak_numbers=streak_numbers,
        current_streak_session_ids=frozenset(current_streak_session_ids),
    )