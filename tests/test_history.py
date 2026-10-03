from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

import yaml

from app.nr_challenge_tracker.history import (
    HistoryError,
    HistoryRepository,
    default_history_path,
)
from app.nr_challenge_tracker.models import Progress, Session, SessionStatus

ELIGIBLE_NIGHTFARER = "executor"


class HistoryRepositoryTests(unittest.TestCase):
    def test_default_history_path_is_project_root(self) -> None:
        root = Path("project-root")

        self.assertEqual(default_history_path(root), root / "history.yaml")

    def test_missing_file_initializes_empty_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.yaml"

            snapshot = HistoryRepository(
                path, eligible_nightfarer=ELIGIBLE_NIGHTFARER
            ).load()

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
                nightfarer="executor",
                nightlord_name="harmonia",
                result_nightlord_name="straghess",
                progress=Progress.DAY_3_VICTORY,
                status=SessionStatus.COMPLETED,
            )
            repository = HistoryRepository(
                path, eligible_nightfarer=ELIGIBLE_NIGHTFARER
            )

            saved = repository.save([session])
            saved_record = yaml.safe_load(path.read_text(encoding="utf-8"))["sessions"][0]
            loaded = repository.load()

            self.assertEqual(saved_record["nightfarer"], "executor")
            self.assertEqual(saved_record["nightlord"]["base_name"], "harmonia")
            self.assertEqual(saved_record["result_nightlord_name"], "straghess")
            self.assertEqual(saved.stats.current_streak, 1)
            self.assertEqual(loaded.stats.streak_numbers, {"win-1": 1})
            self.assertEqual(loaded.sessions[0], session)

    def test_configured_nightfarer_is_used_for_saved_streak_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.yaml"
            start = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
            sessions = [
                Session(
                    id="recluse-win",
                    started_at=start,
                    ended_at=start,
                    nightfarer="recluse",
                    progress=Progress.DAY_3_VICTORY,
                    status=SessionStatus.COMPLETED,
                ),
                Session(
                    id="executor-win",
                    started_at=start,
                    ended_at=start,
                    nightfarer="executor",
                    progress=Progress.DAY_3_VICTORY,
                    status=SessionStatus.COMPLETED,
                ),
            ]
            repository = HistoryRepository(path, eligible_nightfarer="recluse")

            snapshot = repository.save(sessions)
            records = yaml.safe_load(path.read_text(encoding="utf-8"))["sessions"]

            self.assertEqual(snapshot.stats.current_streak, 1)
            self.assertEqual(
                {record["id"]: record["counts_for_streak"] for record in records},
                {"recluse-win": True, "executor-win": False},
            )

    def test_malformed_yaml_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.yaml"
            original = b"schema_version: [broken\n"
            path.write_bytes(original)

            with self.assertRaises(HistoryError):
                HistoryRepository(
                    path, eligible_nightfarer=ELIGIBLE_NIGHTFARER
                ).load()

            self.assertEqual(path.read_bytes(), original)

    def test_duplicate_ids_are_rejected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.yaml"
            start = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
            session = Session(id="same", started_at=start)

            with self.assertRaisesRegex(HistoryError, "unique"):
                HistoryRepository(
                    path, eligible_nightfarer=ELIGIBLE_NIGHTFARER
                ).save([session, session])

            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()