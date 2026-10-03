import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

import numpy as np

from app.nr_challenge_tracker.history import HistoryRepository
from app.nr_challenge_tracker.models import NightlordVariant, Progress
from app.nr_challenge_tracker.monitor import RecognitionMonitor, ScreenDebouncer
from app.nr_challenge_tracker.sessions import SessionService


class FakeRecognitionEngine:
    manifest = {
        "nightfarers": [
            {"id": "executor"},
            {"id": "wylder"},
        ],
        "nightlords": [
            {"id": "adel"},
            {"id": "libra"},
        ],
    }

    def __init__(self, results: list[dict[str, str]]) -> None:
        self.results = iter(results)

    def recognize(self, image: object) -> dict[str, str]:
        return next(self.results)

    def render_debug_image(self, image: object, result: dict[str, str]) -> object:
        return image.copy()


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


class ScreenEntryEventTests(unittest.TestCase):
    def test_monitor_publishes_one_event_per_confirmed_screen_entry(self) -> None:
        results = [
            {"screen": "preparation"},
            {"screen": "preparation"},
            {"screen": "preparation"},
            {"screen": "unknown"},
            {"screen": "result"},
            {"screen": "result"},
            {"screen": "result"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            sessions = SessionService(
                HistoryRepository(Path(temp_dir) / "history.yaml")
            )
            updates: list[dict[str, object]] = []
            monitor = RecognitionMonitor(
                FakeRecognitionEngine(results),
                sessions,
                "Nightreign",
                lambda payload, status: updates.append(payload),
                confirmations=2,
            )

            for _ in results:
                monitor._process(None)

        self.assertEqual(
            [update["screen_entry"] for update in updates if update["screen_entry"]],
            ["preparation", "result"],
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
            self.assertEqual(session.nightfarer, "wylder")
            self.assertEqual(session.nightlord_name, "libra")
            self.assertEqual(monitor._sample_interval_ms, 200)
            self.assertTrue(monitor._preparation_active)

            monitor._process(None)

            self.assertFalse(monitor._preparation_active)


class ResultMonitorTests(unittest.TestCase):
    def test_result_stays_active_until_exit_and_keeps_later_identity(self) -> None:
        results = [
            {
                "screen": "result",
                "nightlord": None,
                "variant": "unknown",
                "outcome": "unknown",
            },
            {
                "screen": "result",
                "nightlord": None,
                "variant": "unknown",
                "outcome": "unknown",
            },
            {
                "screen": "result",
                "nightlord": "libra",
                "variant": "everdark",
                "outcome": "day_3_victory",
            },
            {"screen": "unknown"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            sessions = SessionService(
                HistoryRepository(Path(temp_dir) / "history.yaml")
            )
            active = sessions.start_session(
                nightfarer="executor",
                nightlord_name=None,
                hidden_nightlord=True,
                started_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            )
            monitor = RecognitionMonitor(
                FakeRecognitionEngine(results),
                sessions,
                "Nightreign",
                lambda update, status: None,
                confirmations=2,
                idle_interval_ms=1000,
                result_interval_ms=200,
            )

            monitor._process(None)
            monitor._process(None)

            self.assertTrue(monitor._result_active)
            self.assertEqual(monitor._sample_interval_ms, 200)
            self.assertEqual(sessions.snapshot.sessions[-1].id, active.id)
            self.assertIsNone(sessions.snapshot.sessions[-1].ended_at)

            monitor._process(None)

            self.assertTrue(monitor._result_active)
            self.assertIsNone(sessions.snapshot.sessions[-1].ended_at)

            monitor._process(None)

            session = sessions.snapshot.sessions[-1]
            self.assertFalse(monitor._result_active)
            self.assertEqual(session.status.value, "completed")
            self.assertEqual(session.result_nightlord_name, "libra")
            self.assertEqual(session.nightlord_variant, NightlordVariant.EVERDARK)
            self.assertEqual(session.progress, Progress.DAY_3_VICTORY)


class DebugScreenshotMonitorTests(unittest.TestCase):
    def test_preparation_saves_after_confirmation_and_keeps_each_identity(self) -> None:
        results = [
            {"screen": "preparation", "nightfarer": "executor", "nightlord": "adel"},
            {"screen": "preparation", "nightfarer": "executor", "nightlord": "adel"},
            {"screen": "preparation", "nightfarer": "wylder", "nightlord": "libra"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            debug_dir = root / "debug" / "screenshots"
            sessions = SessionService(HistoryRepository(root / "history.yaml"))
            monitor = RecognitionMonitor(
                FakeRecognitionEngine(results),
                sessions,
                "Nightreign",
                lambda update, status: None,
                confirmations=2,
                debug_dir=debug_dir,
            )

            monitor._process(np.full((60, 100, 3), 1, dtype=np.uint8))
            self.assertFalse(debug_dir.exists())
            monitor._process(np.full((60, 100, 3), 2, dtype=np.uint8))

            first_path = debug_dir / "0001_preparation_executor_adel.png"
            self.assertTrue(first_path.is_file())
            original_contents = first_path.read_bytes()
            monitor._process(np.full((60, 100, 3), 3, dtype=np.uint8))

            second_path = debug_dir / "0001_preparation_wylder_libra.png"
            self.assertTrue(second_path.is_file())
            self.assertNotEqual(first_path, second_path)
            self.assertEqual(first_path.read_bytes(), original_contents)
            self.assertEqual(len(list(debug_dir.glob("*.png"))), 2)
            second_contents = second_path.read_bytes()

            monitor._save_debug_screenshot(
                np.full((60, 100, 3), 9, dtype=np.uint8),
                results[-1],
                sessions.snapshot.sessions[-1],
            )
            self.assertEqual(second_path.read_bytes(), second_contents)

    def test_result_uses_all_attempt_history_ordinal_and_skips_duplicate(self) -> None:
        result = {
            "screen": "result",
            "nightlord": "libra",
            "variant": "everdark",
            "outcome": "day_3_victory",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            start = datetime.now(timezone.utc) - timedelta(seconds=10)
            sessions = SessionService(HistoryRepository(root / "history.yaml"))
            previous = sessions.start_session(
                nightfarer="executor",
                nightlord_name="adel",
                hidden_nightlord=False,
                started_at=start,
            )
            sessions.finalize_result(
                previous.id,
                progress=Progress.DAY_1,
                ended_at=start + timedelta(seconds=1),
                nightlord_name="adel",
                variant=NightlordVariant.NORMAL,
            )
            active = sessions.start_session(
                nightfarer="executor",
                nightlord_name="libra",
                hidden_nightlord=False,
                started_at=start + timedelta(seconds=2),
            )
            debug_dir = root / "debug" / "screenshots"
            updates = []
            monitor = RecognitionMonitor(
                FakeRecognitionEngine([result, result]),
                sessions,
                "Nightreign",
                lambda update, status: updates.append((update, status)),
                confirmations=2,
                debug_dir=debug_dir,
            )

            monitor._process(np.full((60, 100, 3), 4, dtype=np.uint8))
            self.assertFalse(debug_dir.exists())
            monitor._process(np.full((60, 100, 3), 5, dtype=np.uint8))

            screenshot = debug_dir / "0002_result_libra_everdark_day_3_victory.png"
            self.assertTrue(screenshot.is_file())
            original_contents = screenshot.read_bytes()
            monitor._save_debug_screenshot(
                np.full((60, 100, 3), 9, dtype=np.uint8),
                result,
                sessions.snapshot.sessions[-1],
            )
            self.assertEqual(screenshot.read_bytes(), original_contents)
            self.assertEqual(sessions.snapshot.sessions[-1].id, active.id)

    def test_debug_write_failure_does_not_stop_monitor_processing(self) -> None:
        result = {"screen": "preparation", "nightfarer": "executor", "nightlord": "adel"}
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            blocked_path = root / "not-a-directory"
            blocked_path.write_text("blocked", encoding="utf-8")
            sessions = SessionService(HistoryRepository(root / "history.yaml"))
            updates = []
            monitor = RecognitionMonitor(
                FakeRecognitionEngine([result, result]),
                sessions,
                "Nightreign",
                lambda update, status: updates.append((update, status)),
                confirmations=2,
                debug_dir=blocked_path,
            )

            monitor._process(np.zeros((60, 100, 3), dtype=np.uint8))
            monitor._process(np.zeros((60, 100, 3), dtype=np.uint8))

            self.assertEqual(len(sessions.snapshot.sessions), 1)
            self.assertEqual(monitor.status, "monitor.debug_screenshot_error")
            self.assertEqual(updates[-1][1], "monitor.debug_screenshot_error")
            self.assertTrue(updates[-1][0]["status_values"]["detail"])


if __name__ == "__main__":
    unittest.main()