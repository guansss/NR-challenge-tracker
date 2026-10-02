import unittest
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from app.nr_challenge_tracker.history import HistoryRepository
from app.nr_challenge_tracker.monitor import RecognitionMonitor, ScreenDebouncer
from app.nr_challenge_tracker.sessions import SessionService


class FakeRecognitionEngine:
    manifest = {
        "nightfarers": [
            {"id": "executor", "display_name": "Executor"},
            {"id": "wylder", "display_name": "Wylder"},
        ],
        "nightlords": [
            {"id": "adel", "display_name": "Adel"},
            {"id": "libra", "display_name": "Libra"},
        ],
    }

    def __init__(self, results: list[dict[str, str]]) -> None:
        self.results = iter(results)

    def recognize(self, image: object) -> dict[str, str]:
        return next(self.results)


class ScreenDebouncerTests(unittest.TestCase):
    def test_candidate_requires_consistent_confirmations(self) -> None:
        debouncer = ScreenDebouncer(confirmations=3)

        self.assertIsNone(debouncer.observe("preparation"))
        self.assertIsNone(debouncer.observe("preparation"))
        self.assertEqual(debouncer.observe("preparation"), "preparation")
        self.assertIsNone(debouncer.observe("preparation"))

    def test_unknown_screen_resets_candidate(self) -> None:
        debouncer = ScreenDebouncer(confirmations=2)

        self.assertIsNone(debouncer.observe("result"))
        self.assertIsNone(debouncer.observe("unknown"))
        self.assertIsNone(debouncer.observe("result"))
        self.assertEqual(debouncer.observe("result"), "result")

    def test_changed_identity_restarts_screen_confirmation(self) -> None:
        debouncer = ScreenDebouncer(confirmations=2)

        self.assertIsNone(debouncer.observe("preparation", ("executor", "adel")))
        self.assertEqual(
            debouncer.observe("preparation", ("executor", "adel")),
            "preparation",
        )
        self.assertIsNone(debouncer.observe("preparation", ("executor", "adel")))
        self.assertIsNone(debouncer.observe("preparation", ("executor", "libra")))
        self.assertEqual(
            debouncer.observe("preparation", ("executor", "libra")),
            "preparation",
        )


class PreparationMonitorTests(unittest.TestCase):
    def test_active_preparation_updates_each_frame_and_exits_when_gone(self) -> None:
        results = [
            {"screen": "preparation", "nightfarer": "executor", "nightlord": "adel"},
            {"screen": "preparation", "nightfarer": "executor", "nightlord": "adel"},
            {"screen": "preparation", "nightfarer": "wylder", "nightlord": "libra"},
            {"screen": "unknown"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            sessions = SessionService(
                HistoryRepository(Path(temp_dir) / "history.yaml")
            )
            monitor = RecognitionMonitor(
                FakeRecognitionEngine(results),
                sessions,
                "Nightreign",
                lambda update, status: None,
                confirmations=2,
                idle_interval_ms=1000,
                preparation_interval_ms=200,
            )

            monitor._process(None)
            monitor._process(None)
            monitor._process(None)

            session = sessions.snapshot.sessions[0]
            self.assertEqual(session.nightfarer, "Wylder")
            self.assertEqual(session.nightlord_name, "Libra")
            self.assertEqual(monitor._sample_interval_ms, 200)
            self.assertTrue(monitor._preparation_active)

            monitor._process(None)

            self.assertFalse(monitor._preparation_active)


if __name__ == "__main__":
    unittest.main()