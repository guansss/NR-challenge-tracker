from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from app.nr_challenge_tracker.history import (
    HistoryError,
    HistoryRepository,
    default_history_path,
)
from app.nr_challenge_tracker.models import Progress, Session, SessionStatus


class HistoryRepositoryTests(unittest.TestCase):
    def test_default_history_path_is_project_root(self) -> None:
        root = Path("project-root")

        self.assertEqual(default_history_path(root), root / "history.yaml")

    def test_missing_file_initializes_empty_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.yaml"

            snapshot = HistoryRepository(path).load()

            self.assertEqual(snapshot.sessions, ())
            self.assertEqual(snapshot.stats.current_streak, 0)
            self.assertTrue(path.is_file())

    def test_round_trip_recomputes_derived_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.yaml"
            start = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
            session = Session(
                id="win-1",
                started_at=start,
                ended_at=start,
                nightfarer="Executor",
                nightlord_name="Harmonia",
                progress=Progress.DAY_3_VICTORY,
                status=SessionStatus.COMPLETED,
            )
            repository = HistoryRepository(path)

            saved = repository.save([session])
            loaded = repository.load()

            self.assertEqual(saved.stats.current_streak, 1)
            self.assertEqual(loaded.stats.streak_numbers, {"win-1": 1})
            self.assertEqual(loaded.sessions[0], session)

    def test_legacy_nightlord_string_migrates_to_unknown_variant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.yaml"
            path.write_text(
                """schema_version: 1
challenge:
  target: 100
  current_streak: 999
sessions:
  - id: win-1
    started_at: '2026-10-03T12:00:00+00:00'
    ended_at: '2026-10-03T12:20:00+00:00'
    nightfarer: Executor
    nightlord: Harmonia
    progress: day_3_victory
    status: completed
""",
                encoding="utf-8",
            )

            snapshot = HistoryRepository(path).load()

            self.assertEqual(snapshot.sessions[0].nightlord_name, "Harmonia")
            self.assertEqual(snapshot.sessions[0].nightlord_variant.value, "unknown")
            self.assertEqual(snapshot.stats.current_streak, 1)
            self.assertIn("base_name: Harmonia", path.read_text(encoding="utf-8"))
            self.assertIn("variant: unknown", path.read_text(encoding="utf-8"))

    def test_malformed_yaml_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.yaml"
            original = b"schema_version: [broken\n"
            path.write_bytes(original)

            with self.assertRaises(HistoryError):
                HistoryRepository(path).load()

            self.assertEqual(path.read_bytes(), original)

    def test_duplicate_ids_are_rejected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.yaml"
            start = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
            session = Session(id="same", started_at=start)

            with self.assertRaisesRegex(HistoryError, "unique"):
                HistoryRepository(path).save([session, session])

            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()