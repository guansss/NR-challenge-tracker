from datetime import datetime, timezone
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from app.nr_challenge_tracker.history import HistorySnapshot
from app.nr_challenge_tracker.models import (
    NightlordVariant,
    Progress,
    Session,
    SessionStatus,
)
from app.nr_challenge_tracker.streak import calculate_streak
from app.nr_challenge_tracker.ui import ResolveSessionDialog, TrackerWindow


class ResolveSessionDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_unresolved_session_requires_explicit_outcome_selection(self) -> None:
        session = Session(
            id="needs-resolution",
            started_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
            nightfarer="Executor",
            nightlord_name="Caligo",
            progress=Progress.DAY_3_VICTORY,
            status=SessionStatus.UNRESOLVED,
        )

        nightlords = ["Adel", "Caligo", "Fulghor"]
        dialog = ResolveSessionDialog([session], ["Executor"], nightlords)

        self.assertIsNone(dialog.progress.currentData())
        self.assertEqual(
            [dialog.nightlord.itemData(index) for index in range(dialog.nightlord.count())],
            [None, *nightlords],
        )
        self.assertEqual(dialog.nightlord.currentData(), "Caligo")
        dialog.progress.setCurrentIndex(
            dialog.progress.findData(Progress.DAY_3_VICTORY)
        )
        self.assertIs(dialog.selected_progress(), Progress.DAY_3_VICTORY)
        dialog.close()

    def test_switching_sessions_reloads_all_form_fields(self) -> None:
        first_started = datetime(2026, 10, 2, 10, tzinfo=timezone.utc)
        second_started = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
        second_ended = datetime(2026, 10, 3, 13, tzinfo=timezone.utc)
        first = Session(
            id="first-session",
            started_at=first_started,
            nightfarer="Executor",
            nightlord_name="Caligo",
            nightlord_variant=NightlordVariant.NORMAL,
            status=SessionStatus.UNRESOLVED,
        )
        second = Session(
            id="second-session",
            started_at=second_started,
            ended_at=second_ended,
            nightfarer="Raider",
            nightlord_name="Adel",
            nightlord_variant=NightlordVariant.EVERDARK,
            progress=Progress.DAY_2,
            status=SessionStatus.COMPLETED,
        )

        dialog = ResolveSessionDialog(
            [first, second],
            ["Executor", "Raider"],
            ["Adel", "Caligo"],
            selected_session_id="second-session",
        )

        self.assertEqual(dialog.session_picker.currentData(), "second-session")
        self.assertEqual(
            [
                dialog.session_picker.itemData(index)
                for index in range(dialog.session_picker.count())
            ],
            ["second-session", "first-session"],
        )
        self.assertIsInstance(dialog.session_picker.currentData(), str)
        self.assertEqual(dialog.nightfarer.currentData(), "Raider")
        self.assertIsInstance(dialog.nightfarer.currentData(), str)
        self.assertEqual(dialog.nightlord.currentData(), "Adel")
        self.assertIsInstance(dialog.nightlord.currentData(), str)
        self.assertIs(dialog.selected_variant(), NightlordVariant.EVERDARK)
        self.assertIs(dialog.selected_progress(), Progress.DAY_2)
        self.assertEqual(
            dialog.started_at.dateTime().toSecsSinceEpoch(),
            round(second_started.timestamp()),
        )
        self.assertEqual(
            dialog.ended_at.dateTime().toSecsSinceEpoch(),
            round(second_ended.timestamp()),
        )

        dialog.session_picker.setCurrentIndex(
            dialog.session_picker.findData("first-session")
        )
        self.assertEqual(dialog.nightfarer.currentData(), "Executor")
        self.assertEqual(dialog.nightlord.currentData(), "Caligo")
        self.assertIs(dialog.selected_variant(), NightlordVariant.NORMAL)
        self.assertIsNone(dialog.selected_progress())
        dialog.close()


class TrackerWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_live_result_is_shown_before_session_finalization(self) -> None:
        active = Session(
            id="active-session",
            started_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
            nightfarer="Executor",
            nightlord_hidden=True,
            status=SessionStatus.ACTIVE,
        )
        snapshot = HistorySnapshot(
            sessions=(active,), stats=calculate_streak((active,))
        )
        sessions = Mock(snapshot=snapshot)
        monitor = Mock()
        monitor._nightlord_names = {"libra": "Libra"}
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "Disabled",
            "sync_message": "",
        }

        window = TrackerWindow(
            sessions, monitor, title_state, ["Executor"], ["Libra"]
        )
        window.monitor_update(
            {
                "recognition": {
                    "screen": "result",
                    "nightlord": "libra",
                    "variant": "everdark",
                    "outcome": "day_3_victory",
                }
            },
            "Monitoring Nightreign",
        )
        self.application.processEvents()

        self.assertEqual(
            window.current_label.text(),
            "Result: Libra · Everdark · Day 3 Victory",
        )
        self.assertIs(snapshot.sessions[0].status, SessionStatus.ACTIVE)
        window.deleteLater()

    def test_history_shows_unresolved_sessions_but_not_discarded_sessions(self) -> None:
        started_at = datetime(2026, 10, 3, tzinfo=timezone.utc)
        ended_at = datetime(2026, 10, 3, 1, 30, tzinfo=timezone.utc)
        unresolved = Session(
            id="needs-resolution",
            started_at=started_at,
            ended_at=ended_at,
            nightfarer="Executor",
            status=SessionStatus.UNRESOLVED,
        )
        discarded = Session(
            id="discarded-session",
            started_at=started_at,
            nightfarer="Executor",
            status=SessionStatus.DISCARDED,
        )
        snapshot = HistorySnapshot(
            sessions=(unresolved, discarded),
            stats=calculate_streak((unresolved, discarded)),
        )
        sessions = Mock(snapshot=snapshot)
        monitor = Mock()
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "Disabled",
            "sync_message": "",
        }

        window = TrackerWindow(
            sessions,
            monitor,
            title_state,
            ["Executor"],
            ["Caligo"],
            font_size=18,
        )
        window._refresh_timer.stop()
        self.assertEqual(window.history.count(), 1)
        self.assertEqual(
            window.history.item(0).data(Qt.ItemDataRole.UserRole), "needs-resolution"
        )
        self.assertIn(
            ended_at.astimezone().strftime("%Y/%m/%d %H:%M:%S"),
            window.history.item(0).text(),
        )
        self.assertNotIn(
            started_at.astimezone().strftime("%Y/%m/%d %H:%M:%S"),
            window.history.item(0).text(),
        )
        window.show()
        self.application.processEvents()
        item = window.history.item(0)
        item_position = window.history.visualItemRect(item).center()
        QTest.mouseClick(window.history.viewport(), Qt.MouseButton.LeftButton, pos=item_position)
        self.assertIs(window.history.currentItem(), item)
        QTest.mouseClick(window.history.viewport(), Qt.MouseButton.LeftButton, pos=item_position)
        self.assertIsNone(window.history.currentItem())
        self.assertEqual(window.history.selectedItems(), [])
        QTest.mouseClick(window.history.viewport(), Qt.MouseButton.LeftButton, pos=item_position)
        window.refresh()
        self.assertEqual(
            window.history.currentItem().data(Qt.ItemDataRole.UserRole),
            "needs-resolution",
        )
        with patch(
            "app.nr_challenge_tracker.ui.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window.skip_active()
        sessions.discard_session.assert_called_once_with("needs-resolution")
        button_texts = [button.text() for button in window.findChildren(QPushButton)]
        self.assertNotIn("Open config", button_texts)
        self.assertIn("Lock", button_texts)
        for widget in (
            window.heading,
            window.monitor_label,
            window.sync_label,
            window.pause_button,
            window.history,
        ):
            self.assertEqual(widget.font().pixelSize(), 18)
        self.assertEqual(window.current_label.font().pixelSize(), 19)
        self.assertEqual(window.streak_label.font().pixelSize(), 32)
        self.assertIn(
            'QPushButton#lockButton[locked="true"]:hover',
            window.centralWidget().styleSheet(),
        )
        window.lock_button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
        window._set_lock_button_locked(True)
        self.assertTrue(window.lock_button.property("locked"))
        self.assertIn("background: transparent", window.centralWidget().styleSheet())
        history_size = window.history.size()
        button_sizes = [button.size() for button in window.findChildren(QPushButton)]
        window.resize(620, 520)
        self.application.processEvents()
        self.assertGreater(window.history.width(), history_size.width())
        self.assertGreater(window.history.height(), history_size.height())
        self.assertEqual(
            [button.size() for button in window.findChildren(QPushButton)],
            button_sizes,
        )
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()