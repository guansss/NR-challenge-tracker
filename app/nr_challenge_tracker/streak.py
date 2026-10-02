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
    total_executor_victories: int
    target: int
    streak_numbers: Mapping[str, int]


def calculate_streak(
    sessions: Iterable[Session], target: int = 100
) -> StreakStats:
    """Recompute challenge statistics and historical victory labels.

    Completed Executor outcomes are applied in end-time order. Unknown,
    unresolved, interrupted, and discarded sessions have no effect.
    """
    if isinstance(target, bool) or not isinstance(target, int) or target <= 0:
        raise ValueError("Streak target must be a positive integer")

    session_list = list(sessions)
    session_ids = [session.id for session in session_list]
    if len(session_ids) != len(set(session_ids)):
        raise ValueError("Session ids must be unique")

    eligible = [session for session in session_list if session.counts_for_streak]
    eligible.sort(
        key=lambda session: (
            session.ended_at.astimezone(timezone.utc),
            session.started_at.astimezone(timezone.utc),
            session.id,
        )
    )

    current = 0
    best = 0
    total_victories = 0
    streak_numbers: dict[str, int] = {}
    for session in eligible:
        if session.progress is Progress.DAY_3_VICTORY:
            current += 1
            best = max(best, current)
            total_victories += 1
            streak_numbers[session.id] = current
        else:
            current = 0

    return StreakStats(
        current_streak=min(current, target),
        best_streak=best,
        total_executor_victories=total_victories,
        target=target,
        streak_numbers=streak_numbers,
    )