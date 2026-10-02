from datetime import datetime, timezone
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.nr_challenge_tracker.models import Progress, Session, SessionStatus
from app.nr_challenge_tracker.ui import ResolveSessionDialog


class ResolveSessionDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_unresolved_session_requires_explicit_outcome_selection(self) -> None:
        session = Session(
            id="needs-resolution",
            started_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
            nightfarer="Executor",
            progress=Progress.DAY_3_VICTORY,
            status=SessionStatus.UNRESOLVED,
        )

        dialog = ResolveSessionDialog([session], ["Executor"])

        self.assertIsNone(dialog.progress.currentData())
        dialog.close()


if __name__ == "__main__":
    unittest.main()