from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

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
from app.nr_challenge_tracker.settings import SettingsRepository
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
            nightfarer="executor",
            nightlord_name="caligo",
            progress=Progress.DAY_3_VICTORY,
            status=SessionStatus.UNRESOLVED,
        )

        nightlords = ["adel", "caligo", "fulghor"]
        dialog = ResolveSessionDialog([session], ["executor"], nightlords)

        self.assertIsNone(dialog.progress.currentData())
        self.assertEqual(
            [dialog.nightlord.itemData(index) for index in range(dialog.nightlord.count())],
            [None, *nightlords],
        )
        self.assertEqual(dialog.nightlord.currentData(), "caligo")
        dialog.progress.setCurrentIndex(
            dialog.progress.findData(Progress.DAY_3_VICTORY)
        )
        self.assertIs(dialog.selected_progress(), Progress.DAY_3_VICTORY)
        dialog.close()

    def test_dialog_labels_follow_configured_language(self) -> None:
        dialog = ResolveSessionDialog([], ["executor"], ["adel"], language="zh")

        self.assertEqual(dialog.windowTitle(), "修正场次")
        self.assertEqual(dialog.nightfarer.itemText(0), "未知")
        self.assertEqual(dialog.nightfarer.itemText(1), "执行者")
        self.assertEqual(dialog.nightfarer.itemData(1), "executor")
        self.assertEqual(dialog.nightlord.itemText(0), "选择夜王")
        self.assertEqual(dialog.nightlord.itemText(1), "大嘴")
        self.assertEqual(dialog.nightlord.itemData(1), "adel")
        self.assertEqual(dialog.progress.itemText(0), "选择结果")
        dialog.close()

    def test_switching_sessions_reloads_all_form_fields(self) -> None:
        first_started = datetime(2026, 10, 2, 10, tzinfo=timezone.utc)
        second_started = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
        second_ended = datetime(2026, 10, 3, 13, tzinfo=timezone.utc)
        first = Session(
            id="first-session",
            started_at=first_started,
            nightfarer="executor",
            nightlord_name="caligo",
            nightlord_variant=NightlordVariant.NORMAL,
            status=SessionStatus.UNRESOLVED,
        )
        second = Session(
            id="second-session",
            started_at=second_started,
            ended_at=second_ended,
            nightfarer="raider",
            nightlord_name="adel",
            nightlord_variant=NightlordVariant.EVERDARK,
            progress=Progress.DAY_2,
            status=SessionStatus.COMPLETED,
        )

        dialog = ResolveSessionDialog(
            [first, second],
            ["executor", "raider"],
            ["adel", "caligo"],
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
        self.assertEqual(dialog.nightfarer.currentData(), "raider")
        self.assertIsInstance(dialog.nightfarer.currentData(), str)
        self.assertEqual(dialog.nightlord.currentData(), "adel")
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
        self.assertEqual(dialog.nightfarer.currentData(), "executor")
        self.assertEqual(dialog.nightlord.currentData(), "caligo")
        self.assertIs(dialog.selected_variant(), NightlordVariant.NORMAL)
        self.assertIsNone(dialog.selected_progress())
        dialog.close()


class TrackerWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_screen_entry_events_play_the_matching_cues(self) -> None:
        sessions = Mock(
            snapshot=HistorySnapshot(sessions=(), stats=calculate_streak(()))
        )
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }
        window = TrackerWindow(sessions, Mock(), title_state, [], [])

        with patch("app.nr_challenge_tracker.ui._play_screen_cue") as play_cue:
            payload = {"status_values": {"title": "Nightreign"}}
            window.monitor_update(
                {"screen_entry": "preparation", **payload}, "monitor.monitoring_window"
            )
            window.monitor_update(
                {"screen_entry": "result", **payload}, "monitor.monitoring_window"
            )
            self.application.processEvents()

        self.assertEqual(
            play_cue.call_args_list,
            [unittest.mock.call("preparation"), unittest.mock.call("result")],
        )
        window.deleteLater()

    def test_window_geometry_is_restored_after_close(self) -> None:
        sessions = Mock(
            snapshot=HistorySnapshot(sessions=(), stats=calculate_streak(()))
        )
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }

        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.yaml"
            settings_path.write_text("other: preserved\n", encoding="utf-8")
            settings_repository = SettingsRepository(settings_path)
            window = TrackerWindow(
                sessions,
                Mock(),
                title_state,
                [],
                [],
                initial_geometry=settings_repository.load_hud_geometry(),
            )
            window.geometry_saved.connect(settings_repository.save_hud_geometry)
            window.move(120, 140)
            window.resize(560, 520)
            expected_geometry = window.geometry()
            window.close()
            saved_settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))

            restarted = TrackerWindow(
                sessions,
                Mock(),
                title_state,
                [],
                [],
                initial_geometry=settings_repository.load_hud_geometry(),
            )

        self.assertEqual(saved_settings["other"], "preserved")
        self.assertEqual(
            saved_settings["hud"]["geometry"],
            {"x": 120, "y": 140, "width": 560, "height": 520},
        )
        self.assertEqual(restarted.geometry(), expected_geometry)
        restarted.deleteLater()

    def test_chinese_localizes_hud_and_monitor_status(self) -> None:
        sessions = Mock(
            snapshot=HistorySnapshot(sessions=(), stats=calculate_streak(()))
        )
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }
        window = TrackerWindow(
            sessions, Mock(), title_state, [], [], language="zh"
        )

        self.assertEqual(window.windowTitle(), "黑夜君临挑战追踪器")
        self.assertEqual(window.pause_button.text(), "暂停")
        self.assertEqual(window.current_label.text(), "没有进行中的场次")
        self.assertEqual(window.sync_label.text(), "直播标题同步：已禁用")
        window.monitor_update({}, "monitor.window_unavailable")
        self.application.processEvents()
        self.assertEqual(window.monitor_label.text(), "未找到游戏窗口")
        window.deleteLater()

    def test_screen_cues_load_the_configured_audio_assets(self) -> None:
        from app.nr_challenge_tracker import ui

        players = [Mock(), Mock()]
        with (
            patch.object(ui, "_SCREEN_CUE_PLAYERS", {}),
            patch.object(ui, "QMediaPlayer", side_effect=players),
            patch.object(ui, "QAudioOutput"),
        ):
            ui._play_screen_cue("preparation")
            ui._play_screen_cue("result")

        self.assertEqual(
            [
                os.path.basename(player.setSource.call_args.args[0].toLocalFile())
                for player in players
            ],
            ["correct.mp3", "picked-coin-echo-2.mp3"],
        )
        for player in players:
            player.play.assert_called_once_with()

    def test_live_result_is_shown_before_session_finalization(self) -> None:
        active = Session(
            id="active-session",
            started_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
            nightfarer="executor",
            nightlord_hidden=True,
            status=SessionStatus.ACTIVE,
        )
        snapshot = HistorySnapshot(
            sessions=(active,), stats=calculate_streak((active,))
        )
        sessions = Mock(snapshot=snapshot)
        monitor = Mock()
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }

        window = TrackerWindow(
            sessions, monitor, title_state, ["executor"], ["libra"]
        )
        window.monitor_update(
            {
                "recognition": {
                    "screen": "result",
                    "nightlord": "libra",
                    "variant": "everdark",
                    "outcome": "day_3_victory",
                },
                "status_values": {"title": "Nightreign"},
            },
            "monitor.monitoring_window",
        )
        self.application.processEvents()

        self.assertEqual(
            window.current_label.text(),
            "Current: Executor - Hidden Nightlord\nResult: Libra · Everdark · Day 3 Victory",
        )
        self.assertIs(snapshot.sessions[0].status, SessionStatus.ACTIVE)
        window.deleteLater()

    def test_character_names_follow_configured_language(self) -> None:
        active = Session(
            id="active-session",
            started_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
            nightfarer="executor",
            nightlord_name="caligo",
            status=SessionStatus.ACTIVE,
        )
        completed = Session(
            id="completed-session",
            started_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
            ended_at=datetime(2026, 10, 2, 1, tzinfo=timezone.utc),
            nightfarer="wylder",
            nightlord_name="adel",
            nightlord_variant=NightlordVariant.EVERDARK,
            progress=Progress.DAY_3,
            status=SessionStatus.COMPLETED,
        )
        snapshot = HistorySnapshot(
            sessions=(completed, active), stats=calculate_streak((completed, active))
        )
        sessions = Mock(snapshot=snapshot)
        monitor = Mock()
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }

        window = TrackerWindow(
            sessions,
            monitor,
            title_state,
            ["executor", "wylder"],
            ["adel", "caligo"],
            language="zh",
        )

        self.assertEqual(window.current_label.text(), "当前：执行者 - 冰龙")
        self.assertIn(
            "追踪者 - 永夜大嘴 - 最终日", window.history.item(0).text()
        )
        window.deleteLater()

    def test_history_respects_configured_recent_session_limit(self) -> None:
        sessions_list = [
            Session(
                id=f"session-{index}",
                started_at=datetime(2026, 10, index + 1, tzinfo=timezone.utc),
                ended_at=datetime(2026, 10, index + 1, 1, tzinfo=timezone.utc),
                status=SessionStatus.COMPLETED,
            )
            for index in range(4)
        ]
        snapshot = HistorySnapshot(
            sessions=tuple(sessions_list), stats=calculate_streak(tuple(sessions_list))
        )
        sessions = Mock(snapshot=snapshot)
        monitor = Mock()
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }

        window = TrackerWindow(
            sessions,
            monitor,
            title_state,
            ["executor"],
            ["caligo"],
            recent_sessions=2,
        )

        self.assertEqual(window.history.count(), 2)
        self.assertEqual(
            [
                window.history.item(index).data(Qt.ItemDataRole.UserRole)
                for index in range(window.history.count())
            ],
            ["session-3", "session-2"],
        )
        window.deleteLater()

    def test_history_shows_unresolved_sessions_but_not_discarded_sessions(self) -> None:
        started_at = datetime(2026, 10, 3, tzinfo=timezone.utc)
        ended_at = datetime(2026, 10, 3, 1, 30, tzinfo=timezone.utc)
        unresolved = Session(
            id="needs-resolution",
            started_at=started_at,
            ended_at=ended_at,
            nightfarer="executor",
            status=SessionStatus.UNRESOLVED,
        )
        discarded = Session(
            id="discarded-session",
            started_at=started_at,
            nightfarer="Executor",
            status=SessionStatus.DISCARDED,
        )
        active = Session(
            id="active-session",
            started_at=started_at,
            nightfarer="executor",
            nightlord_name="caligo",
            status=SessionStatus.ACTIVE,
        )
        snapshot = HistorySnapshot(
            sessions=(unresolved, active, discarded),
            stats=calculate_streak((unresolved, active, discarded)),
        )
        sessions = Mock(snapshot=snapshot)
        monitor = Mock()
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }

        window = TrackerWindow(
            sessions,
            monitor,
            title_state,
            ["executor"],
            ["caligo"],
            font_size=18,
        )
        window._refresh_timer.stop()
        self.assertEqual(window.current_label.text(), "Current: Executor - Caligo")
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