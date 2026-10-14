from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

import yaml

from app.nr_challenge_tracker.history import HistoryRepository
from app.nr_challenge_tracker.models import (
    NightlordVariant,
    Progress,
    Session,
    SessionStatus,
)
from app.nr_challenge_tracker.sessions import (
    NightlordStats,
    NightlordVariantStats,
    SessionService,
    SessionTransitionError,
    calculate_nightlord_stats,
)


START = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
ELIGIBLE_NIGHTFARER = "recluse"


class SessionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.history_path = Path(self.temp_dir.name) / "history.yaml"
        self.service = SessionService(
            HistoryRepository(
                self.history_path, eligible_nightfarer=ELIGIBLE_NIGHTFARER
            )
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def start_eligible_session(self):
        return self.service.start_session(
            nightfarer=ELIGIBLE_NIGHTFARER,
            nightlord_name="harmonia",
            hidden_nightlord=False,
            started_at=START,
        )

    def test_nightlord_stats_separate_variants_and_ignore_unassignable_sessions(self) -> None:
        sessions = (
            Session(
                id="normal-win",
                started_at=START,
                ended_at=START + timedelta(minutes=1),
                nightlord_name="Harmonia",
                nightlord_variant=NightlordVariant.NORMAL,
                progress=Progress.DAY_3_VICTORY,
                status=SessionStatus.COMPLETED,
            ),
            Session(
                id="normal-loss",
                started_at=START,
                ended_at=START + timedelta(minutes=2),
                nightlord_name="harmonia",
                nightlord_variant=NightlordVariant.NORMAL,
                progress=Progress.DAY_2,
                status=SessionStatus.COMPLETED,
            ),
            Session(
                id="everdark-win",
                started_at=START,
                ended_at=START + timedelta(minutes=3),
                nightlord_name="harmonia",
                nightlord_variant=NightlordVariant.EVERDARK,
                progress=Progress.DAY_3_VICTORY,
                status=SessionStatus.COMPLETED,
            ),
            Session(
                id="unknown-variant",
                started_at=START,
                ended_at=START + timedelta(minutes=4),
                nightlord_name="harmonia",
                nightlord_variant=NightlordVariant.UNKNOWN,
                progress=Progress.DAY_3_VICTORY,
                status=SessionStatus.COMPLETED,
            ),
            Session(
                id="unknown-identity",
                started_at=START,
                ended_at=START + timedelta(minutes=5),
                nightlord_variant=NightlordVariant.NORMAL,
                progress=Progress.DAY_3_VICTORY,
                status=SessionStatus.COMPLETED,
            ),
            Session(
                id="unresolved",
                started_at=START,
                nightlord_name="harmonia",
                nightlord_variant=NightlordVariant.NORMAL,
                progress=Progress.DAY_3_VICTORY,
                status=SessionStatus.UNRESOLVED,
            ),
        )

        self.assertEqual(
            calculate_nightlord_stats(sessions),
            {
                "Harmonia": NightlordStats(
                    normal=NightlordVariantStats(runs=2, wins=1),
                    everdark=NightlordVariantStats(runs=1, wins=1),
                )
            },
        )

    def test_session_history_remains_unchanged_by_runtime_analysis(self) -> None:
        session = self.start_eligible_session()
        self.service.finalize_result(
            session.id,
            progress=Progress.DAY_3_VICTORY,
            ended_at=START + timedelta(minutes=45),
        )

        saved = yaml.safe_load(self.history_path.read_text(encoding="utf-8"))
        self.assertEqual(set(saved), {"schema_version", "sessions"})
        self.assertNotIn("counts_for_streak", saved["sessions"][0])

    def test_result_is_finalized_once_and_persisted(self) -> None:
        session = self.start_eligible_session()

        finalized = self.service.finalize_result(
            session.id,
            progress=Progress.DAY_3_VICTORY,
            ended_at=START + timedelta(minutes=45),
            nightlord_name="harmonia",
            variant=NightlordVariant.EVERDARK,
        )

        self.assertEqual(finalized.status, SessionStatus.COMPLETED)
        self.assertEqual(self.service.snapshot.stats.current_streak, 1)
        with self.assertRaises(SessionTransitionError):
            self.service.finalize_result(
                session.id,
                progress=Progress.DAY_3_VICTORY,
                ended_at=START + timedelta(minutes=46),
            )

    def test_identity_conflict_is_preserved_for_review_without_streak_effect(self) -> None:
        session = self.start_eligible_session()

        result = self.service.finalize_result(
            session.id,
            progress=Progress.DAY_3_VICTORY,
            ended_at=START + timedelta(minutes=45),
            nightlord_name="adel",
        )

        self.assertEqual(result.status, SessionStatus.UNRESOLVED)
        self.assertEqual(result.nightlord_name, "harmonia")
        self.assertEqual(result.result_nightlord_name, "adel")
        self.assertIn("identity conflict", result.review_reason or "")
        self.assertEqual(self.service.snapshot.stats.current_streak, 0)

    def test_unknown_result_identity_preserves_known_preparation_identity(self) -> None:
        session = self.start_eligible_session()

        result = self.service.finalize_result(
            session.id,
            progress=Progress.DAY_3_VICTORY,
            ended_at=START + timedelta(minutes=45),
            nightlord_name="unknown",
        )

        self.assertEqual(result.status, SessionStatus.COMPLETED)
        self.assertEqual(result.nightlord_name, "harmonia")
        self.assertIsNone(result.result_nightlord_name)

    def test_hidden_nightlord_without_result_identity_stays_unresolved(self) -> None:
        session = self.service.start_session(
            nightfarer=ELIGIBLE_NIGHTFARER,
            nightlord_name=None,
            hidden_nightlord=True,
            started_at=START,
        )

        result = self.service.finalize_result(
            session.id,
            progress=Progress.DAY_3_VICTORY,
            ended_at=START + timedelta(minutes=45),
        )

        self.assertEqual(result.status, SessionStatus.UNRESOLVED)
        self.assertIn("identity", result.review_reason or "")
        self.assertEqual(self.service.snapshot.stats.current_streak, 0)

    def test_interruption_and_resume_do_not_change_streak(self) -> None:
        session = self.start_eligible_session()

        self.service.interrupt(session.id)
        self.assertEqual(self.service.snapshot.stats.current_streak, 0)
        self.service.resume_interrupted(session.id)
        self.assertEqual(self.service.snapshot.stats.current_streak, 0)

    def test_preparation_selection_updates_active_session(self) -> None:
        session = self.start_eligible_session()

        updated = self.service.update_preparation(
            session.id,
            nightfarer="wylder",
            nightlord_name="libra",
            hidden_nightlord=False,
        )

        self.assertEqual(updated.nightfarer, "wylder")
        self.assertEqual(updated.nightlord_name, "libra")
        self.assertEqual(self.service.snapshot.sessions[0], updated)

    def test_manual_resolution_requires_explicit_outcome(self) -> None:
        session = self.start_eligible_session()
        unresolved = self.service.finalize_result(
            session.id,
            progress=None,
            ended_at=START + timedelta(minutes=45),
        )

        with self.assertRaisesRegex(SessionTransitionError, "explicit outcome"):
            self.service.resolve_session(
                session.id,
                nightfarer=ELIGIBLE_NIGHTFARER,
                nightlord_name="harmonia",
                variant=NightlordVariant.UNKNOWN,
                progress=Progress.UNKNOWN,
                ended_at=unresolved.ended_at,
            )

        resolved = self.service.resolve_session(
            session.id,
            nightfarer=ELIGIBLE_NIGHTFARER,
            nightlord_name="harmonia",
            variant=NightlordVariant.UNKNOWN,
            progress=Progress.DAY_3_VICTORY,
            ended_at=unresolved.ended_at,
        )
        self.assertEqual(resolved.status, SessionStatus.COMPLETED)
        self.assertEqual(self.service.snapshot.stats.current_streak, 1)

    def test_manual_correction_without_outcome_preserves_session_state(self) -> None:
        session = self.start_eligible_session()
        awaiting_result = self.service.set_awaiting_result(session.id)

        corrected = self.service.resolve_session(
            session.id,
            nightfarer="wylder",
            nightlord_name="libra",
            variant=NightlordVariant.EVERDARK,
            progress=None,
            started_at=START + timedelta(minutes=5),
            ended_at=START + timedelta(hours=1),
        )

        self.assertEqual(corrected.nightfarer, "wylder")
        self.assertEqual(corrected.nightlord_name, "libra")
        self.assertEqual(corrected.started_at, START + timedelta(minutes=5))
        self.assertEqual(corrected.status, awaiting_result.status)
        self.assertEqual(corrected.progress, awaiting_result.progress)
        self.assertEqual(corrected.ended_at, awaiting_result.ended_at)
        self.assertEqual(
            corrected.nightlord_variant, awaiting_result.nightlord_variant
        )
        self.assertEqual(corrected.result_nightlord_name, awaiting_result.result_nightlord_name)

    def test_everdark_variant_must_exist_in_catalog(self) -> None:
        validated_service = SessionService(
            HistoryRepository(
                Path(self.temp_dir.name) / "validated.yaml",
                eligible_nightfarer=ELIGIBLE_NIGHTFARER,
            ),
            everdark_nightlords={"harmonia"},
        )
        session = validated_service.start_session(
            nightfarer="executor",
            nightlord_name="heolstor",
            hidden_nightlord=False,
            started_at=START,
        )

        with self.assertRaisesRegex(SessionTransitionError, "does not have"):
            validated_service.finalize_result(
                session.id,
                progress=Progress.DAY_3_VICTORY,
                ended_at=START + timedelta(minutes=45),
                nightlord_name="heolstor",
                variant=NightlordVariant.EVERDARK,
            )

    def test_discard_recomputes_derived_streak(self) -> None:
        session = self.start_eligible_session()
        self.service.finalize_result(
            session.id,
            progress=Progress.DAY_3_VICTORY,
            ended_at=START + timedelta(minutes=45),
        )
        self.assertEqual(self.service.snapshot.stats.current_streak, 1)

        discarded = self.service.discard_session(session.id)

        self.assertEqual(discarded.status, SessionStatus.DISCARDED)
        self.assertEqual(self.service.snapshot.stats.current_streak, 0)

    def test_second_active_session_is_rejected(self) -> None:
        self.start_eligible_session()

        with self.assertRaisesRegex(SessionTransitionError, "already exists"):
            self.start_eligible_session()

    def test_restart_marks_active_session_interrupted_without_streak_effect(self) -> None:
        session = self.start_eligible_session()

        restarted = SessionService(
            HistoryRepository(
                self.history_path, eligible_nightfarer=ELIGIBLE_NIGHTFARER
            )
        )

        recovered = restarted.snapshot.sessions[0]
        self.assertEqual(recovered.id, session.id)
        self.assertEqual(recovered.status, SessionStatus.INTERRUPTED)
        self.assertEqual(restarted.snapshot.stats.current_streak, 0)


if __name__ == "__main__":
    unittest.main()