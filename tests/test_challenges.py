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
from app.nr_challenge_tracker.config import (
    load_default_config,
    load_project_settings,
    save_user_config,
)
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

    def test_challenge_start_time_includes_sessions_at_or_after_boundary(self) -> None:
        analysis = analyze_challenge(
            self.sessions,
            Challenge(
                "started", "Started", ChallengeType.NORMAL,
                start_time=self.sessions[1].started_at,
            ),
        )

        self.assertEqual(analysis.total_sessions, 2)
        self.assertEqual(analysis.total_wins, 1)

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

    def test_streak_challenge_uses_initial_streak_values(self) -> None:
        analysis = analyze_challenge(
            (self.sessions[0],),
            Challenge(
                "seeded", "Seeded", ChallengeType.WINNING_STREAK,
                frozenset(), "executor", 100, 5, 12,
            ),
        )

        self.assertEqual(analysis.streak.current_streak, 6)
        self.assertEqual(analysis.streak.best_streak, 12)
        self.assertEqual(analysis.streak_numbers, {"executor-win": 6})
        self.assertEqual(analysis.total_wins, 1)

    def test_normal_challenge_rejects_nonzero_initial_streaks(self) -> None:
        with self.assertRaisesRegex(ValueError, "streak settings"):
            Challenge(
                "normal", "Normal", ChallengeType.NORMAL,
                initial_current_streak=1,
                initial_best_streak=1,
            )

    def test_best_initial_streak_cannot_be_below_current_streak(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be lower"):
            Challenge(
                "seeded", "Seeded", ChallengeType.WINNING_STREAK,
                frozenset(), "executor", 100, 3, 2,
            )

    def test_challenge_start_time_must_be_timezone_aware(self) -> None:
        with self.assertRaisesRegex(ValueError, "must include a timezone"):
            Challenge(
                "naive", "Naive", ChallengeType.NORMAL,
                start_time=datetime(2026, 10, 3),
            )


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
        self.assertEqual(
            persisted["challenges"][0]["start_time"],
            "1970-01-01T00:00:00+00:00",
        )

    def test_legacy_challenges_default_to_unix_epoch_start_time(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "user-config.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "challenges": [
                            {
                                "id": "legacy",
                                "name": "Legacy",
                                "type": "normal",
                                "excluded_session_ids": [],
                            }
                        ],
                        "active_challenge_id": "legacy",
                    }
                ),
                encoding="utf-8",
            )

            config, _settings = load_project_settings(
                Path(directory), assets_root=root
            )

        self.assertEqual(
            config["challenges"][0]["start_time"],
            "1970-01-01T00:00:00+00:00",
        )

    def test_streak_initial_values_default_to_zero_and_round_trip(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "user-config.yaml"
            challenge = {
                "id": "streak",
                "name": "Streak",
                "type": "winning_streak",
                "eligible_nightfarer": "executor",
                "target": 100,
                "excluded_session_ids": [],
            }
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "challenges": [challenge],
                        "active_challenge_id": "streak",
                    }
                ),
                encoding="utf-8",
            )

            config, _settings = load_project_settings(
                Path(directory), assets_root=root
            )

            self.assertEqual(
                config["challenges"][0]["initial_current_streak"], 0
            )
            self.assertEqual(config["challenges"][0]["initial_best_streak"], 0)
            config["challenges"][0]["initial_current_streak"] = 5
            config["challenges"][0]["initial_best_streak"] = 12
            save_user_config(Path(directory), load_default_config(root), config)

            persisted = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            reloaded, _settings = load_project_settings(
                Path(directory), assets_root=root
            )

        self.assertEqual(
            persisted["challenges"][0]["initial_current_streak"], 5
        )
        self.assertEqual(persisted["challenges"][0]["initial_best_streak"], 12)
        self.assertEqual(
            reloaded["challenges"][0]["initial_current_streak"], 5
        )
        self.assertEqual(reloaded["challenges"][0]["initial_best_streak"], 12)

    def test_best_initial_streak_must_not_be_below_current_streak(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "user-config.yaml").write_text(
                yaml.safe_dump(
                    {
                        "challenges": [
                            {
                                "id": "streak",
                                "name": "Streak",
                                "type": "winning_streak",
                                "eligible_nightfarer": "executor",
                                "target": 100,
                                "initial_current_streak": 5,
                                "initial_best_streak": 4,
                                "excluded_session_ids": [],
                            }
                        ],
                        "active_challenge_id": "streak",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "cannot be lower"):
                load_project_settings(Path(directory), assets_root=root)


if __name__ == "__main__":
    unittest.main()
