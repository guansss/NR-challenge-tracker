import json
import tempfile
import unittest
from pathlib import Path

from app.nr_challenge_tracker.state import PersistedTitleState, StateRepository
from app.nr_challenge_tracker.streak import StreakStats
from app.nr_challenge_tracker.title_state import TitleState


class StateRepositoryTests(unittest.TestCase):
    def test_hud_and_title_state_share_a_validated_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            repository = StateRepository(path)
            repository.save_hud_geometry(10, 20, 420, 360)
            repository.save_title_state(
                PersistedTitleState(
                    revision=3,
                    desired_title="Challenge (3/100)",
                    sync_status="sync.synced",
                    sync_message="Saved",
                )
            )

            restarted = StateRepository(path)

            self.assertEqual(restarted.load_hud_geometry(), (10, 20, 420, 360))
            title = restarted.load_title_state()
            self.assertEqual(title.revision, 3)
            self.assertEqual(title.desired_title, "Challenge (3/100)")
            self.assertEqual(title.sync_status, "sync.synced")
            self.assertEqual(title.sync_message, "Saved")
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["schema_version"], 1)
            self.assertIn("hud", document)
            self.assertIn("title", document)

    def test_invalid_state_uses_defaults_without_rewriting_until_saved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            invalid_document = (
                '{"hud":{"geometry":{"x":true,"y":20,"width":420,"height":360}},'
                '"title":{"revision":5,"desired_title":"stale"}}'
            )
            path.write_text(invalid_document, encoding="utf-8")

            repository = StateRepository(path)

            self.assertIsNone(repository.load_hud_geometry())
            self.assertEqual(repository.load_title_state(), PersistedTitleState())
            self.assertEqual(path.read_text(encoding="utf-8"), invalid_document)

            repository.save_hud_geometry(1, 2, 300, 240)

            self.assertEqual(repository.load_hud_geometry(), (1, 2, 300, 240))
            self.assertEqual(
                StateRepository(path).load_title_state(), PersistedTitleState()
            )

    def test_malformed_json_uses_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("{not json", encoding="utf-8")

            repository = StateRepository(path)

            self.assertIsNone(repository.load_hud_geometry())
            self.assertEqual(repository.load_title_state(), PersistedTitleState())

    def test_revision_increments_only_when_desired_title_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = TitleState(
                StateRepository(Path(directory) / "state.json"),
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
            repository = StateRepository(Path(directory) / "state.json")
            state = TitleState(repository, "{current_streak}/{target}", 40, 123)
            state.update(StreakStats(7, 7, 7, 100, {}))
            state.report_sync("sync.synced", 1)

            restarted = TitleState(
                StateRepository(repository.path), "{current_streak}/{target}", 40, 123
            )
            view = restarted.update(StreakStats(7, 7, 7, 100, {}))

            self.assertEqual(view["revision"], 1)
            self.assertEqual(view["sync_status"], "sync.synced")

    def test_stale_sync_report_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = TitleState(
                StateRepository(Path(directory) / "state.json"),
                "{current_streak}",
                40,
                None,
            )
            state.update(StreakStats(2, 2, 2, 100, {}))

            self.assertFalse(state.report_sync("sync.synced", 0))

    def test_title_length_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = TitleState(
                StateRepository(Path(directory) / "state.json"), "long title", 4, None
            )

            with self.assertRaisesRegex(ValueError, "exceeds configured limit"):
                state.update(StreakStats(0, 0, 0, 100, {}))


if __name__ == "__main__":
    unittest.main()
