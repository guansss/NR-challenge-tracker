from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from app.nr_challenge_tracker.history import HistoryRepository
from app.nr_challenge_tracker.models import NightlordVariant, Progress, SessionStatus
from app.nr_challenge_tracker.sessions import SessionService, SessionTransitionError


START = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


class SessionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.history_path = Path(self.temp_dir.name) / "history.yaml"
        self.service = SessionService(HistoryRepository(self.history_path))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def start_executor(self):
        return self.service.start_session(
            nightfarer="Executor",
            nightlord_name="Harmonia",
            hidden_nightlord=False,
            started_at=START,
        )

    def test_result_is_finalized_once_and_persisted(self) -> None:
        session = self.start_executor()

        finalized = self.service.finalize_result(
            session.id,
            progress=Progress.DAY_3_VICTORY,
            ended_at=START + timedelta(minutes=45),
            nightlord_name="Harmonia",
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
        session = self.start_executor()

        result = self.service.finalize_result(
            session.id,
            progress=Progress.DAY_3_VICTORY,
            ended_at=START + timedelta(minutes=45),
            nightlord_name="Adel",
        )

        self.assertEqual(result.status, SessionStatus.UNRESOLVED)
        self.assertEqual(result.nightlord_name, "Harmonia")
        self.assertEqual(result.result_nightlord_name, "Adel")
        self.assertIn("identity conflict", result.review_reason or "")
        self.assertEqual(self.service.snapshot.stats.current_streak, 0)

    def test_hidden_nightlord_without_result_identity_stays_unresolved(self) -> None:
        session = self.service.start_session(
            nightfarer="Executor",
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
        session = self.start_executor()

        self.service.interrupt(session.id)
        self.assertEqual(self.service.snapshot.stats.current_streak, 0)
        self.service.resume_interrupted(session.id)
        self.assertEqual(self.service.snapshot.stats.current_streak, 0)

    def test_preparation_selection_updates_active_session(self) -> None:
        session = self.start_executor()

        updated = self.service.update_preparation(
            session.id,
            nightfarer="Wylder",
            nightlord_name="Libra",
            hidden_nightlord=False,
        )

        self.assertEqual(updated.nightfarer, "Wylder")
        self.assertEqual(updated.nightlord_name, "Libra")
        self.assertEqual(self.service.snapshot.sessions[0], updated)

    def test_manual_resolution_requires_explicit_outcome(self) -> None:
        session = self.start_executor()
        unresolved = self.service.finalize_result(
            session.id,
            progress=None,
            ended_at=START + timedelta(minutes=45),
        )

        with self.assertRaisesRegex(SessionTransitionError, "explicit outcome"):
            self.service.resolve_session(
                session.id,
                nightfarer="Executor",
                nightlord_name="Harmonia",
                variant=NightlordVariant.UNKNOWN,
                progress=Progress.UNKNOWN,
                ended_at=unresolved.ended_at,
            )

        resolved = self.service.resolve_session(
            session.id,
            nightfarer="Executor",
            nightlord_name="Harmonia",
            variant=NightlordVariant.UNKNOWN,
            progress=Progress.DAY_3_VICTORY,
            ended_at=unresolved.ended_at,
        )
        self.assertEqual(resolved.status, SessionStatus.COMPLETED)
        self.assertEqual(self.service.snapshot.stats.current_streak, 1)

    def test_everdark_variant_must_exist_in_catalog(self) -> None:
        validated_service = SessionService(
            HistoryRepository(Path(self.temp_dir.name) / "validated.yaml"),
            everdark_nightlords={"Harmonia"},
        )
        session = validated_service.start_session(
            nightfarer="Executor",
            nightlord_name="Heolstor",
            hidden_nightlord=False,
            started_at=START,
        )

        with self.assertRaisesRegex(SessionTransitionError, "does not have"):
            validated_service.finalize_result(
                session.id,
                progress=Progress.DAY_3_VICTORY,
                ended_at=START + timedelta(minutes=45),
                nightlord_name="Heolstor",
                variant=NightlordVariant.EVERDARK,
            )

    def test_discard_recomputes_derived_streak(self) -> None:
        session = self.start_executor()
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
        self.start_executor()

        with self.assertRaisesRegex(SessionTransitionError, "already exists"):
            self.start_executor()

    def test_restart_marks_active_session_interrupted_without_streak_effect(self) -> None:
        session = self.start_executor()

        restarted = SessionService(HistoryRepository(self.history_path))

        recovered = restarted.snapshot.sessions[0]
        self.assertEqual(recovered.id, session.id)
        self.assertEqual(recovered.status, SessionStatus.INTERRUPTED)
        self.assertEqual(restarted.snapshot.stats.current_streak, 0)


if __name__ == "__main__":
    unittest.main()