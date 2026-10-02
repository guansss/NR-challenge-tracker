from pathlib import Path
import tempfile
import unittest

from app.nr_challenge_tracker.streak import StreakStats
from app.nr_challenge_tracker.title_state import TitleState


class TitleStateTests(unittest.TestCase):
    def test_revision_increments_only_when_desired_title_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = TitleState(
                Path(directory) / "title.json",
                "Challenge ({current_streak}/{target})",
                40,
                123,
            )
            stats = StreakStats(4, 8, 20, 100, {})

            first = state.update(stats)
            second = state.update(stats)

            self.assertEqual(first["desired_title"], "Challenge (4/100)")
            self.assertEqual(first["revision"], 1)
            self.assertEqual(second["revision"], 1)

    def test_revision_and_sync_status_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "title.json"
            state = TitleState(path, "{current_streak}/{target}", 40, 123)
            state.update(StreakStats(7, 7, 7, 100, {}))
            state.report_sync("Synced", 1)

            restarted = TitleState(path, "{current_streak}/{target}", 40, 123)
            view = restarted.update(StreakStats(7, 7, 7, 100, {}))

            self.assertEqual(view["revision"], 1)
            self.assertEqual(view["sync_status"], "Synced")

    def test_stale_sync_report_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = TitleState(
                Path(directory) / "title.json", "{current_streak}", 40, None
            )
            state.update(StreakStats(2, 2, 2, 100, {}))

            self.assertFalse(state.report_sync("Synced", 0))

    def test_title_length_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = TitleState(Path(directory) / "title.json", "long title", 4, None)

            with self.assertRaisesRegex(ValueError, "exceeds configured limit"):
                state.update(StreakStats(0, 0, 0, 100, {}))


if __name__ == "__main__":
    unittest.main()