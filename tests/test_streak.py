from datetime import datetime, timedelta, timezone
import unittest

from app.nr_challenge_tracker.models import Progress, Session, SessionStatus
from app.nr_challenge_tracker.streak import calculate_streak


START = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


def completed_session(
    session_id: str,
    minute: int,
    nightfarer: str,
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
    def test_non_executor_outcome_does_not_break_executor_streak(self) -> None:
        sessions = [
            completed_session("win-1", 0, "Executor", Progress.DAY_3_VICTORY),
            completed_session("other-loss", 30, "Revenant", Progress.DAY_2),
            completed_session("win-2", 60, "executor", Progress.DAY_3_VICTORY),
        ]

        stats = calculate_streak(sessions)

        self.assertEqual(stats.current_streak, 2)
        self.assertEqual(stats.total_executor_victories, 2)
        self.assertEqual(stats.streak_numbers, {"win-1": 1, "win-2": 2})

    def test_finalized_executor_nonvictory_resets_streak(self) -> None:
        sessions = [
            completed_session("win-1", 0, "Executor", Progress.DAY_3_VICTORY),
            completed_session("loss", 30, "Executor", Progress.DAY_1),
            completed_session("win-2", 60, "Executor", Progress.DAY_3_VICTORY),
        ]

        stats = calculate_streak(sessions)

        self.assertEqual(stats.current_streak, 1)
        self.assertEqual(stats.best_streak, 1)
        self.assertEqual(stats.streak_numbers, {"win-1": 1, "win-2": 1})

    def test_unresolved_executor_session_has_no_effect(self) -> None:
        win = completed_session("win", 0, "Executor", Progress.DAY_3_VICTORY)
        unresolved_start = START + timedelta(minutes=30)
        unresolved = Session(
            id="unknown",
            started_at=unresolved_start,
            nightfarer="Executor",
            status=SessionStatus.UNRESOLVED,
        )

        stats = calculate_streak([win, unresolved])

        self.assertEqual(stats.current_streak, 1)
        self.assertNotIn("unknown", stats.streak_numbers)

    def test_sessions_are_recomputed_in_end_time_order(self) -> None:
        later_win = completed_session(
            "later", 60, "Executor", Progress.DAY_3_VICTORY
        )
        earlier_loss = completed_session("earlier", 0, "Executor", Progress.DAY_2)

        stats = calculate_streak([later_win, earlier_loss])

        self.assertEqual(stats.current_streak, 1)
        self.assertEqual(stats.streak_numbers, {"later": 1})

    def test_current_streak_is_capped_but_victory_history_is_not(self) -> None:
        sessions = [
            completed_session(
                f"win-{index}", index * 30, "Executor", Progress.DAY_3_VICTORY
            )
            for index in range(102)
        ]

        stats = calculate_streak(sessions)

        self.assertEqual(stats.current_streak, 100)
        self.assertEqual(stats.target, 100)
        self.assertEqual(stats.best_streak, 102)
        self.assertEqual(stats.streak_numbers["win-101"], 102)

    def test_duplicate_session_ids_are_rejected(self) -> None:
        session = completed_session("same", 0, "Executor", Progress.DAY_3_VICTORY)

        with self.assertRaisesRegex(ValueError, "unique"):
            calculate_streak([session, session])

    def test_target_must_be_positive_integer(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive integer"):
            calculate_streak([], target=0)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            calculate_streak([], target=True)


if __name__ == "__main__":
    unittest.main()