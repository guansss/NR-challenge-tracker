from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

import yaml

from app.nr_challenge_tracker.challenges import (
    Challenge,
    ChallengeType,
    analyze_challenge,
)
from app.nr_challenge_tracker.config import load_project_settings
from app.nr_challenge_tracker.history import HistoryRepository
from app.nr_challenge_tracker.models import (
    ANY_NIGHTFARER,
    Progress,
    Session,
    SessionStatus,
)


def _session(
    session_id: str, minute: int, nightfarer: str, progress: Progress
) -> Session:
    started = datetime(2026, 10, 3, tzinfo=timezone.utc) + timedelta(minutes=minute)
    return Session(
        id=session_id,
        started_at=started,
        ended_at=started + timedelta(minutes=1),
        nightfarer=nightfarer,
        progress=progress,
        status=SessionStatus.COMPLETED,
    )


class ChallengeAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sessions = (
            _session("executor-win", 0, "executor", Progress.DAY_3_VICTORY),
            _session("other-win", 5, "recluse", Progress.DAY_3_VICTORY),
            _session("executor-loss", 10, "executor", Progress.DAY_2),
        )

    def test_normal_counts_all_included_sessions_and_wins(self) -> None:
        analysis = analyze_challenge(
            self.sessions,
            Challenge(
                "all", "All Sessions", ChallengeType.NORMAL,
                frozenset({"executor-loss"}),
            ),
        )

        self.assertEqual(analysis.total_sessions, 2)
        self.assertEqual(analysis.total_wins, 2)
        self.assertIsNone(analysis.streak)

    def test_streak_uses_eligible_nightfarer_and_exclusions(self) -> None:
        analysis = analyze_challenge(
            self.sessions,
            Challenge(
                "executor", "Executor", ChallengeType.WINNING_STREAK,
                frozenset({"executor-loss"}), "executor", 10,
            ),
        )

        self.assertEqual(analysis.total_sessions, 2)
        self.assertEqual(analysis.total_wins, 1)
        self.assertEqual(analysis.streak.current_streak, 1)
        self.assertEqual(analysis.streak_numbers, {"executor-win": 1})

    def test_any_nightfarer_streak_includes_every_identity(self) -> None:
        analysis = analyze_challenge(
            self.sessions,
            Challenge(
                "any", "Any Nightfarer", ChallengeType.WINNING_STREAK,
                frozenset(), ANY_NIGHTFARER, 10,
            ),
        )

        self.assertEqual(analysis.total_wins, 2)
        self.assertEqual(analysis.streak.current_streak, 0)
        self.assertEqual(analysis.streak.best_streak, 2)
        self.assertEqual(
            analysis.streak_numbers,
            {"executor-win": 1, "other-win": 2},
        )
        self.assertEqual(analysis.current_streak_session_ids, frozenset())

    def test_streak_challenge_accepts_zero_goal(self) -> None:
        analysis = analyze_challenge(
            self.sessions,
            Challenge(
                "no-goal", "No goal", ChallengeType.WINNING_STREAK,
                frozenset(), "executor", 0,
            ),
        )

        self.assertEqual(analysis.streak.target, 0)
        self.assertEqual(analysis.streak.current_streak, 0)


class SessionOnlyHistoryTests(unittest.TestCase):
    def test_legacy_history_is_rewritten_without_derived_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "schema_version": 1,
                        "challenge": {"target": 100, "current_streak": 4},
                        "sessions": [
                            {
                                "id": "one",
                                "started_at": "2026-10-03T00:00:00+00:00",
                                "ended_at": "2026-10-03T00:01:00+00:00",
                                "nightlord": {"hidden": False, "variant": "unknown"},
                                "status": "completed",
                                "progress": "day_3_victory",
                                "counts_for_streak": True,
                                "streak_number": 4,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            snapshot = HistoryRepository(path).load()
            persisted = yaml.safe_load(path.read_text(encoding="utf-8"))

        self.assertEqual([session.id for session in snapshot.sessions], ["one"])
        self.assertEqual(persisted["schema_version"], 2)
        self.assertEqual(set(persisted), {"schema_version", "sessions"})
        self.assertNotIn("counts_for_streak", persisted["sessions"][0])
        self.assertNotIn("streak_number", persisted["sessions"][0])


class ChallengeConfigTests(unittest.TestCase):
    def test_first_run_creates_and_persists_a_normal_challenge(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            config, _settings = load_project_settings(
                Path(directory), assets_root=root
            )
            persisted = yaml.safe_load(
                (Path(directory) / "user-config.yaml").read_text(encoding="utf-8")
            )

        self.assertEqual(config["active_challenge_id"], "normal")
        self.assertEqual(config["challenges"][0]["type"], "normal")
        self.assertEqual(persisted["challenges"][0]["type"], "normal")

    def test_challenges_may_share_names(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "user-config.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "challenges": [
                            {
                                "id": "first",
                                "name": "Same name",
                                "type": "normal",
                                "excluded_session_ids": [],
                            },
                            {
                                "id": "second",
                                "name": "Same name",
                                "type": "normal",
                                "excluded_session_ids": [],
                            },
                        ],
                        "active_challenge_id": "first",
                    }
                ),
                encoding="utf-8",
            )

            config, _settings = load_project_settings(
                Path(directory), assets_root=root
            )

        self.assertEqual(
            [challenge["name"] for challenge in config["challenges"]],
            ["Same name", "Same name"],
        )


if __name__ == "__main__":
    unittest.main()
