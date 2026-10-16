from datetime import datetime, timedelta, timezone
import unittest

from app.nr_challenge_tracker.models import (
    ANY_NIGHTFARER,
    Progress,
    Session,
    SessionStatus,
)
from app.nr_challenge_tracker.streak import calculate_streak


START = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
ELIGIBLE_NIGHTFARER = "executor"


def completed_session(
    session_id: str,
    minute: int,
    nightfarer: str | None,
    progress: Progress,
) -> Session:
    started_at = START + timedelta(minutes=minute)
    return Session(
        id=session_id,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=20),
        nightfarer=nightfarer,
        progress=progress,
        status=SessionStatus.COMPLETED,
    )


class StreakTests(unittest.TestCase):
    def test_other_nightfarer_outcome_does_not_break_eligible_streak(self) -> None:
        sessions = [
            completed_session("win-1", 0, "executor", Progress.DAY_3_VICTORY),
            completed_session("other-loss", 30, "revenant", Progress.DAY_2),
            completed_session("win-2", 60, "executor", Progress.DAY_3_VICTORY),
        ]

        stats = calculate_streak(
            sessions, eligible_nightfarer=ELIGIBLE_NIGHTFARER
        )

        self.assertEqual(stats.current_streak, 2)
        self.assertEqual(stats.total_eligible_victories, 2)
        self.assertEqual(stats.streak_numbers, {"win-1": 1, "win-2": 2})

    def test_configured_nightfarer_controls_streak_eligibility(self) -> None:
        sessions = [
            completed_session("recluse-win", 0, "recluse", Progress.DAY_3_VICTORY),
            completed_session("executor-loss", 30, "executor", Progress.DAY_1),
        ]

        stats = calculate_streak(sessions, eligible_nightfarer="recluse")

        self.assertEqual(stats.current_streak, 1)
        self.assertEqual(stats.total_eligible_victories, 1)
        self.assertEqual(stats.streak_numbers, {"recluse-win": 1})

    def test_any_nightfarer_counts_all_identities_and_unknown_runs(self) -> None:
        sessions = [
            completed_session("executor-win", 0, "executor", Progress.DAY_3_VICTORY),
            completed_session("recluse-win", 30, "recluse", Progress.DAY_3_VICTORY),
            completed_session("unknown-loss", 60, None, Progress.DAY_2),
            completed_session("unknown-win", 90, None, Progress.DAY_3_VICTORY),
        ]

        stats = calculate_streak(sessions, eligible_nightfarer=ANY_NIGHTFARER)

        self.assertEqual(stats.current_streak, 1)
        self.assertEqual(stats.best_streak, 2)
        self.assertEqual(stats.total_eligible_victories, 3)
        self.assertEqual(
            stats.streak_numbers,
            {"executor-win": 1, "recluse-win": 2, "unknown-win": 1},
        )
        self.assertEqual(stats.current_streak_session_ids, frozenset({"unknown-win"}))

    def test_finalized_executor_nonvictory_resets_streak(self) -> None:
        sessions = [
            completed_session("win-1", 0, "executor", Progress.DAY_3_VICTORY),
            completed_session("loss", 30, "executor", Progress.DAY_1),
            completed_session("win-2", 60, "executor", Progress.DAY_3_VICTORY),
        ]

        stats = calculate_streak(
            sessions, eligible_nightfarer=ELIGIBLE_NIGHTFARER
        )

        self.assertEqual(stats.current_streak, 1)
        self.assertEqual(stats.best_streak, 1)
        self.assertEqual(stats.streak_numbers, {"win-1": 1, "win-2": 1})
        self.assertEqual(stats.current_streak_session_ids, frozenset({"win-2"}))

    def test_unresolved_executor_session_has_no_effect(self) -> None:
        win = completed_session("win", 0, "executor", Progress.DAY_3_VICTORY)
        unresolved_start = START + timedelta(minutes=30)
        unresolved = Session(
            id="unknown",
            started_at=unresolved_start,
            nightfarer="executor",
            status=SessionStatus.UNRESOLVED,
        )

        stats = calculate_streak(
            [win, unresolved], eligible_nightfarer=ELIGIBLE_NIGHTFARER
        )

        self.assertEqual(stats.current_streak, 1)
        self.assertNotIn("unknown", stats.streak_numbers)

    def test_sessions_are_recomputed_in_end_time_order(self) -> None:
        later_win = completed_session(
            "later", 60, "executor", Progress.DAY_3_VICTORY
        )
        earlier_loss = completed_session("earlier", 0, "executor", Progress.DAY_2)

        stats = calculate_streak(
            [later_win, earlier_loss], eligible_nightfarer=ELIGIBLE_NIGHTFARER
        )

        self.assertEqual(stats.current_streak, 1)
        self.assertEqual(stats.streak_numbers, {"later": 1})

    def test_current_streak_can_exceed_target(self) -> None:
        sessions = [
            completed_session(
                f"win-{index}", index * 30, "executor", Progress.DAY_3_VICTORY
            )
            for index in range(102)
        ]

        stats = calculate_streak(
            sessions, eligible_nightfarer=ELIGIBLE_NIGHTFARER
        )

        self.assertEqual(stats.current_streak, 102)
        self.assertEqual(stats.target, 100)
        self.assertEqual(stats.best_streak, 102)
        self.assertEqual(stats.streak_numbers["win-101"], 102)

    def test_duplicate_session_ids_are_rejected(self) -> None:
        session = completed_session("same", 0, "executor", Progress.DAY_3_VICTORY)

        with self.assertRaisesRegex(ValueError, "unique"):
            calculate_streak(
                [session, session], eligible_nightfarer=ELIGIBLE_NIGHTFARER
            )

    def test_target_must_be_positive_integer(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive integer"):
            calculate_streak(
                [], target=0, eligible_nightfarer=ELIGIBLE_NIGHTFARER
            )
        with self.assertRaisesRegex(ValueError, "positive integer"):
            calculate_streak(
                [], target=True, eligible_nightfarer=ELIGIBLE_NIGHTFARER
            )


if __name__ == "__main__":
    unittest.main()