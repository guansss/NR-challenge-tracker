import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from app.nr_challenge_tracker.challenges import Challenge, ChallengeType, analyze_challenge
from app.nr_challenge_tracker.models import Progress, Session, SessionStatus
from app.nr_challenge_tracker.state import PersistedTitleState, StateRepository
from app.nr_challenge_tracker.title_state import TitleState


def _normal_analysis():
    started = datetime(2026, 10, 3, tzinfo=UTC)
    session = Session(
        id="win",
        started_at=started,
        ended_at=started,
        nightfarer="executor",
        progress=Progress.DAY_3_VICTORY,
        status=SessionStatus.COMPLETED,
    )
    return analyze_challenge((session,), Challenge("normal", "Normal", ChallengeType.NORMAL))


def _streak_analysis():
    started = datetime(2026, 10, 3, tzinfo=UTC)
    session = Session(
        id="win",
        started_at=started,
        ended_at=started,
        nightfarer="executor",
        progress=Progress.DAY_3_VICTORY,
        status=SessionStatus.COMPLETED,
    )
    return analyze_challenge(
        (session,),
        Challenge(
            "streak", "Streak", ChallengeType.WINNING_STREAK,
            eligible_nightfarer="executor", target=100,
        ),
    )


class StateRepositoryTests(unittest.TestCase):
    def test_hud_and_title_state_share_a_validated_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            repository = StateRepository(path)
            repository.save_hud_geometry(10, 20, 420, 360)
            repository.save_title_state(
                PersistedTitleState(
                    revision=3,
                    desired_title="Challenge (W:0/0 S:3/100)",
                    sync_status="sync.synced",
                    sync_message="Saved",
                )
            )

            restarted = StateRepository(path)

            self.assertEqual(restarted.load_hud_geometry(), (10, 20, 420, 360))
            title = restarted.load_title_state()
            self.assertEqual(title.revision, 3)
            self.assertEqual(title.desired_title, "Challenge (W:0/0 S:3/100)")
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
                "Challenge ({wins}/{total}) ({streak}/{goal})",
            )
            analysis = _normal_analysis()

            first = state.update(analysis)
            second = state.update(analysis)

            self.assertEqual(first["desired_title"], "Challenge (1/1) (0/0)")
            self.assertEqual(
                {key: first[key] for key in ("wins", "total", "streak", "goal")},
                {"wins": 1, "total": 1, "streak": 0, "goal": 0},
            )
            self.assertEqual(first["revision"], 1)
            self.assertEqual(second["revision"], 1)

    def test_winning_streak_challenge_populates_only_streak_and_goal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = TitleState(
                StateRepository(Path(directory) / "state.json"),
                "Wins {wins}/{total}, streak {streak}/{goal}",
            )

            view = state.update(_streak_analysis())

        self.assertEqual(view["desired_title"], "Wins 0/0, streak 1/100")
        self.assertEqual(
            {key: view[key] for key in ("wins", "total", "streak", "goal")},
            {"wins": 0, "total": 0, "streak": 1, "goal": 100},
        )

    def test_revision_and_sync_status_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = StateRepository(Path(directory) / "state.json")
            state = TitleState(repository, "{wins}/{total}:{streak}/{goal}")
            state.update(_streak_analysis())
            state.report_sync("sync.synced", 1)

            restarted = TitleState(
                StateRepository(repository.path), "{wins}/{total}:{streak}/{goal}"
            )
            view = restarted.update(_streak_analysis())

            self.assertEqual(view["revision"], 1)
            self.assertEqual(view["sync_status"], "sync.synced")

    def test_stale_sync_report_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = TitleState(
                StateRepository(Path(directory) / "state.json"),
                "{streak}",
            )
            state.update(_streak_analysis())

            self.assertFalse(state.report_sync("sync.synced", 0))

    def test_long_title_is_not_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = TitleState(
                StateRepository(Path(directory) / "state.json"),
                "A title longer than any configured limit",
            )

            view = state.update(_normal_analysis())

            self.assertEqual(
                view["desired_title"], "A title longer than any configured limit"
            )


if __name__ == "__main__":
    unittest.main()
