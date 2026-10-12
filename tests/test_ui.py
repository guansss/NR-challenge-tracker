import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from app.nr_challenge_tracker.config import load_default_config
from app.nr_challenge_tracker.challenge_dialog import ChallengeManagerDialog
from app.nr_challenge_tracker.history import HistorySnapshot
from app.nr_challenge_tracker.models import (
    NightlordVariant,
    Progress,
    Session,
    SessionStatus,
)
from app.nr_challenge_tracker.state import StateRepository
from app.nr_challenge_tracker.streak import calculate_streak
from app.nr_challenge_tracker.settings_dialog import SettingsDialog
from app.nr_challenge_tracker.ui import (
    ResolveSessionDialog,
    TrackerWindow,
)

ROOT = Path(__file__).resolve().parents[1]
ELIGIBLE_NIGHTFARER = "executor"


def _window_config(eligible_nightfarer: str = ELIGIBLE_NIGHTFARER) -> dict:
    config = load_default_config(ROOT)
    config["challenges"] = [{
        "id": "streak",
        "name": "Streak",
        "type": "winning_streak",
        "eligible_nightfarer": eligible_nightfarer,
        "target": 100,
        "excluded_session_ids": [],
    }]
    config["active_challenge_id"] = "streak"
    return config


def _calculate_test_streak(sessions):
    return calculate_streak(sessions, eligible_nightfarer=ELIGIBLE_NIGHTFARER)


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
            [
                dialog.nightlord.itemData(index)
                for index in range(dialog.nightlord.count())
            ],
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


class SettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_save_writes_only_the_edited_setting(self) -> None:
        defaults = load_default_config(ROOT)
        config = load_default_config(ROOT)

        with tempfile.TemporaryDirectory() as directory:
            dialog = SettingsDialog(
                Path(directory),
                defaults,
                config,
                ["executor", "recluse"],
                language="en",
                assets_root=ROOT,
            )
            self.assertNotIn("paths", dialog.editors)
            self.assertNotIn(
                "recognition.preparation_nightlord_roi", dialog.editors
            )
            reset = dialog.reset_buttons["hud.recent_sessions"]
            self.assertFalse(reset.isEnabled())
            dialog.editors["hud.recent_sessions"].setValue(75)
            self.assertTrue(reset.isEnabled())
            reset.click()
            self.assertEqual(dialog.editors["hud.recent_sessions"].value(), 10)
            self.assertFalse(reset.isEnabled())
            dialog.editors["hud.recent_sessions"].setValue(75)
            dialog._save()

            saved = yaml.safe_load(
                (Path(directory) / "user-config.yaml").read_text(encoding="utf-8")
            )

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(saved, {"hud": {"recent_sessions": 75}})

    def test_wheel_does_not_change_combo_or_numeric_settings(self) -> None:
        defaults = load_default_config(ROOT)
        dialog = SettingsDialog(
            Path(tempfile.gettempdir()),
            defaults,
            defaults,
            ["executor", "recluse"],
            language="en",
            assets_root=ROOT,
        )
        for key in (
            "language",
            "hud.recent_sessions",
            "hud.opacity",
        ):
            editor = dialog.editors[key]
            if hasattr(editor, "value"):
                before = editor.value()
            else:
                before = editor.currentIndex()
            event = QWheelEvent(
                QPointF(5, 5),
                QPointF(5, 5),
                QPoint(0, 0),
                QPoint(0, 120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.ScrollUpdate,
                False,
            )

            editor.wheelEvent(event)

            after = editor.value() if hasattr(editor, "value") else editor.currentIndex()
            self.assertEqual(after, before, key)
            self.assertFalse(event.isAccepted(), key)
        dialog.close()

    def test_active_challenge_is_selected_and_saved_in_settings(self) -> None:
        defaults = load_default_config(ROOT)
        config = load_default_config(ROOT)
        config["challenges"] = [
            {
                "id": "first",
                "name": "First",
                "type": "normal",
                "excluded_session_ids": [],
            },
            {
                "id": "second",
                "name": "Second",
                "type": "normal",
                "excluded_session_ids": [],
            },
        ]
        config["active_challenge_id"] = "first"
        with tempfile.TemporaryDirectory() as directory:
            dialog = SettingsDialog(
                Path(directory), defaults, config, ["executor"], language="en",
                assets_root=ROOT,
            )
            self.assertEqual(dialog.challenge_selector.currentData(), "first")
            self.assertIsNotNone(dialog.challenge_manager_button)
            dialog.challenge_selector.setCurrentIndex(
                dialog.challenge_selector.findData("second")
            )

            dialog._save()

            persisted = yaml.safe_load(
                (Path(directory) / "user-config.yaml").read_text(encoding="utf-8")
            )

        self.assertEqual(persisted["active_challenge_id"], "second")
        self.assertEqual(dialog.saved_config["active_challenge_id"], "second")

    def test_challenge_manager_trigger_is_inside_settings_dialog(self) -> None:
        defaults = load_default_config(ROOT)
        config = load_default_config(ROOT)
        config["challenges"] = [{
            "id": "normal",
            "name": "All Sessions",
            "type": "normal",
            "excluded_session_ids": [],
        }]
        config["active_challenge_id"] = "normal"
        dialog = SettingsDialog(
            Path(tempfile.gettempdir()), defaults, config, ["executor"],
            language="en", assets_root=ROOT,
        )

        with patch("app.nr_challenge_tracker.settings_dialog.ChallengeManagerDialog") as manager:
            manager.return_value.exec.return_value = QDialog.DialogCode.Accepted
            manager.return_value.saved_config = {
                **config,
                "challenges": [
                    *config["challenges"],
                    {
                        "id": "second",
                        "name": "Second",
                        "type": "normal",
                        "excluded_session_ids": [],
                    },
                ],
            }
            dialog.challenge_manager_button.click()

        self.assertEqual(dialog.challenge_selector.count(), 2)
        manager.assert_called_once()
        dialog.close()


class ChallengeManagerDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_adding_challenge_with_blank_name_does_not_parse_unsaved_form(self) -> None:
        defaults = load_default_config(ROOT)
        config = load_default_config(ROOT)
        config["challenges"] = [{
            "id": "normal",
            "name": "All Sessions",
            "type": "normal",
            "excluded_session_ids": [],
        }]
        config["active_challenge_id"] = "normal"

        with tempfile.TemporaryDirectory() as directory:
            parent = QWidget()
            dialog = ChallengeManagerDialog(
                config, (), ["executor"], parent,
                language="en",
            )
            dialog.name.clear()

            dialog._add()

            self.assertEqual(dialog.challenge_list.count(), 2)
            self.assertEqual(
                dialog.challenge_list.currentItem().text(), "New Challenge"
            )
            self.assertEqual(
                dialog.config["challenges"][0]["name"], "All Sessions"
            )
            dialog.close()

    def test_switching_challenges_saves_edits_to_the_previous_challenge(self) -> None:
        defaults = load_default_config(ROOT)
        config = load_default_config(ROOT)
        config["challenges"] = [
            {
                "id": "normal",
                "name": "All Sessions",
                "type": "normal",
                "excluded_session_ids": [],
            },
            {
                "id": "streak",
                "name": "Executor",
                "type": "winning_streak",
                "eligible_nightfarer": "executor",
                "target": 25,
                "excluded_session_ids": [],
            },
        ]
        config["active_challenge_id"] = "normal"
        parent = QWidget()
        dialog = ChallengeManagerDialog(
            config, (), ["executor"],
            parent, language="en",
        )
        dialog.name.setText("Edited Normal")

        dialog.challenge_list.setCurrentRow(1)

        self.assertEqual(dialog.config["challenges"][0]["name"], "Edited Normal")
        self.assertEqual(dialog.name.text(), "Executor")
        dialog.close()

    def test_exclusion_list_displays_localized_session_details(self) -> None:
        started_at = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
        session = Session(
            id="session-details",
            started_at=started_at,
            ended_at=started_at,
            nightfarer="executor",
            nightlord_name="caligo",
            nightlord_variant=NightlordVariant.NORMAL,
            progress=Progress.DAY_3_VICTORY,
            status=SessionStatus.COMPLETED,
        )
        config = load_default_config(ROOT)
        config["challenges"] = [{
            "id": "normal",
            "name": "All Sessions",
            "type": "normal",
            "excluded_session_ids": [],
        }]
        config["active_challenge_id"] = "normal"
        parent = QWidget()
        dialog = ChallengeManagerDialog(
            config, (session,), ["executor"], parent, language="en",
        )

        expected_timestamp = started_at.astimezone().strftime("%Y/%m/%d %H:%M:%S")
        self.assertEqual(
            dialog.exclusions.item(0).text(),
            f"{expected_timestamp} Executor - Caligo - Victory",
        )
        dialog.close()


class TrackerWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_screen_entry_events_play_the_matching_cues(self) -> None:
        sessions = Mock(
            snapshot=HistorySnapshot(sessions=(), stats=_calculate_test_streak(()))
        )
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }
        monitor = Mock(target_window="Nightreign")
        with patch("app.nr_challenge_tracker.ui._play_screen_cue") as play_cue:
            window = TrackerWindow(
                sessions,
                monitor,
                title_state,
                [],
                [],
                config=_window_config("recluse"),
            )
            self.assertEqual(window.goal_label.text(), "Goal: Recluse streak")
            payload = {"status_values": {"title": "Nightreign"}}
            window.monitor_update(
                {"screen_entry": "preparation", **payload}, "monitor.monitoring_window"
            )
            window.monitor_update(
                {"screen_entry": "result", **payload}, "monitor.monitoring_window"
            )
            self.application.processEvents()

        self.assertEqual(window.monitor_label.text(), "Monitoring Nightreign")
        self.assertEqual(
            play_cue.call_args_list,
            [unittest.mock.call("preparation"), unittest.mock.call("result")],
        )
        window.deleteLater()

    def test_live_font_setting_refreshes_existing_hud(self) -> None:
        sessions = Mock(
            snapshot=HistorySnapshot(sessions=(), stats=_calculate_test_streak(()))
        )
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }
        config = _window_config()
        config["hud"]["font_size"] = 22
        window = TrackerWindow(
            sessions,
            Mock(),
            title_state,
            [],
            [],
            config=config,
        )

        window.apply_live_settings(config)

        self.assertEqual(window._panel.font().pixelSize(), 22)
        self.assertEqual(window.history.font().pixelSize(), 22)
        self.assertEqual(window.streak_label.font().pixelSize(), 44)
        self.assertEqual(window.goal_label.text(), "Goal: Executor streak")
        window.close()

    def test_live_always_on_top_setting_keeps_hud_visible(self) -> None:
        sessions = Mock(
            snapshot=HistorySnapshot(sessions=(), stats=_calculate_test_streak(()))
        )
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }
        config = _window_config()
        window = TrackerWindow(sessions, Mock(), title_state, [], [], config=config)
        window.show()
        self.application.processEvents()
        self.assertTrue(window.isVisible())
        self.assertTrue(
            window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        )

        config["hud"]["always_on_top"] = False
        window.apply_live_settings(config)
        self.application.processEvents()

        self.assertTrue(window.isVisible())
        self.assertFalse(
            window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        )

        config["hud"]["always_on_top"] = True
        window.apply_live_settings(config)
        self.application.processEvents()

        self.assertTrue(window.isVisible())
        self.assertTrue(
            window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        )
        window.close()

    def test_window_geometry_is_restored_after_close(self) -> None:
        sessions = Mock(
            snapshot=HistorySnapshot(sessions=(), stats=_calculate_test_streak(()))
        )
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_repository = StateRepository(state_path)
            window = TrackerWindow(
                sessions,
                Mock(),
                title_state,
                [],
                [],
                config=_window_config(),
                initial_geometry=state_repository.load_hud_geometry(),
            )
            window.geometry_saved.connect(state_repository.save_hud_geometry)
            window.move(120, 140)
            window.resize(560, 520)
            expected_geometry = window.geometry()
            window.close()
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

            restarted = TrackerWindow(
                sessions,
                Mock(),
                title_state,
                [],
                [],
                config=_window_config(),
                initial_geometry=state_repository.load_hud_geometry(),
            )

        self.assertEqual(
            saved_state["hud"]["geometry"],
            {"x": 120, "y": 140, "width": 560, "height": 520},
        )
        self.assertIn("title", saved_state)
        self.assertEqual(restarted.geometry(), expected_geometry)
        restarted.deleteLater()

    def test_invalid_saved_geometry_is_ignored(self) -> None:
        invalid_documents = (
            '{"hud":{"geometry":{"x":true,"y":10,"width":320,"height":240}}}',
            '{"hud":{"geometry":{"x":10,"y":10,"width":0,"height":240}}}',
        )
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            for document in invalid_documents:
                with self.subTest(document=document):
                    state_path.write_text(document, encoding="utf-8")
                    repository = StateRepository(state_path)
                    self.assertIsNone(repository.load_hud_geometry())

    def test_chinese_localizes_hud_and_monitor_status(self) -> None:
        sessions = Mock(
            snapshot=HistorySnapshot(sessions=(), stats=_calculate_test_streak(()))
        )
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }
        window = TrackerWindow(
            sessions,
            Mock(),
            title_state,
            [],
            [],
            language="zh",
            config=_window_config(),
        )

        self.assertEqual(window.windowTitle(), "黑夜君临挑战追踪器")
        self.assertEqual(window.pause_button.text(), "暂停")
        self.assertEqual(window.goal_label.text(), "目标：执行者连胜")
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
            sessions=(active,), stats=_calculate_test_streak((active,))
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
            ["libra"],
            config=_window_config(),
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
            sessions=(completed, active),
            stats=_calculate_test_streak((completed, active)),
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
            config=_window_config(),
        )

        self.assertEqual(window.current_label.text(), "当前：执行者 - 冰龙")
        labels = window.history.itemWidget(window.history.item(0)).findChildren(QLabel)
        self.assertIn("追踪者 - 永夜大嘴 - 最终日", [label.text() for label in labels])
        self.assertEqual(window.history.item(0).text(), "")
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
            sessions=tuple(sessions_list),
            stats=_calculate_test_streak(tuple(sessions_list)),
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
            config=_window_config(),
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

    def test_resolved_active_session_is_added_to_history(self) -> None:
        started_at = datetime(2026, 10, 3, tzinfo=timezone.utc)
        ended_at = datetime(2026, 10, 3, 1, tzinfo=timezone.utc)
        active = Session(
            id="active-session",
            started_at=started_at,
            nightfarer="executor",
            nightlord_name="caligo",
            status=SessionStatus.ACTIVE,
        )
        resolved = Session(
            id=active.id,
            started_at=started_at,
            ended_at=ended_at,
            nightfarer="executor",
            nightlord_name="caligo",
            nightlord_variant=NightlordVariant.NORMAL,
            progress=Progress.DAY_3_VICTORY,
            status=SessionStatus.COMPLETED,
        )
        sessions = Mock(
            snapshot=HistorySnapshot(
                sessions=(active,), stats=_calculate_test_streak((active,))
            )
        )

        def save_resolution(*args, **kwargs):
            sessions.snapshot = HistorySnapshot(
                sessions=(resolved,), stats=_calculate_test_streak((resolved,))
            )
            return resolved

        sessions.resolve_session.side_effect = save_resolution
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }
        dialog = Mock()
        dialog.exec.return_value = 1
        dialog.session_picker.currentData.return_value = active.id
        dialog.nightfarer.currentData.return_value = "executor"
        dialog.nightlord.currentData.return_value = "caligo"
        dialog.selected_progress.return_value = Progress.DAY_3_VICTORY
        dialog.selected_variant.return_value = NightlordVariant.NORMAL
        dialog.started_at.dateTime.return_value.toPython.return_value = started_at
        dialog.ended_at.dateTime.return_value.toPython.return_value = ended_at

        window = TrackerWindow(
            sessions,
            Mock(),
            title_state,
            ["executor"],
            ["caligo"],
            config=_window_config(),
        )
        window._refresh_timer.stop()

        with patch(
            "app.nr_challenge_tracker.ui.ResolveSessionDialog", return_value=dialog
        ):
            window.resolve_session()

        self.assertEqual(window.history.count(), 1)
        self.assertEqual(
            window.history.item(0).data(Qt.ItemDataRole.UserRole), active.id
        )
        sessions.resolve_session.assert_called_once()
        window.deleteLater()

    def test_active_session_can_save_preparation_without_an_outcome(self) -> None:
        started_at = datetime(2026, 10, 3, tzinfo=timezone.utc)
        awaiting_result = Session(
            id="awaiting-result",
            started_at=started_at,
            nightfarer="executor",
            nightlord_name="caligo",
            status=SessionStatus.AWAITING_RESULT,
        )
        sessions = Mock(
            snapshot=HistorySnapshot(
                sessions=(awaiting_result,),
                stats=_calculate_test_streak((awaiting_result,)),
            )
        )
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }
        dialog = Mock()
        dialog.exec.return_value = 1
        dialog.session_picker.currentData.return_value = awaiting_result.id
        dialog.nightfarer.currentData.return_value = "wylder"
        dialog.nightlord.currentData.return_value = "libra"
        dialog.selected_progress.return_value = None
        dialog.selected_variant.return_value = NightlordVariant.NORMAL
        dialog.started_at.dateTime.return_value.toPython.return_value = started_at
        dialog.ended_at.dateTime.return_value.toPython.return_value = started_at

        window = TrackerWindow(
            sessions,
            Mock(),
            title_state,
            ["executor", "wylder"],
            ["caligo", "libra"],
            config=_window_config(),
        )
        window._refresh_timer.stop()

        with patch(
            "app.nr_challenge_tracker.ui.ResolveSessionDialog", return_value=dialog
        ):
            window.resolve_session()

        sessions.resolve_session.assert_called_once_with(
            awaiting_result.id,
            nightfarer="wylder",
            nightlord_name="libra",
            variant=NightlordVariant.NORMAL,
            progress=None,
            started_at=started_at,
            ended_at=started_at,
        )
        window.deleteLater()

    def test_history_refresh_preserves_scroll_and_jumps_to_top_on_update(self) -> None:
        sessions_list = tuple(
            Session(
                id=f"session-{index}",
                started_at=datetime(2026, 10, index + 1, tzinfo=timezone.utc),
                ended_at=datetime(2026, 10, index + 1, 1, tzinfo=timezone.utc),
                status=SessionStatus.COMPLETED,
            )
            for index in range(12)
        )
        sessions = Mock(
            snapshot=HistorySnapshot(
                sessions=sessions_list, stats=_calculate_test_streak(sessions_list)
            )
        )
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }
        window = TrackerWindow(
            sessions,
            Mock(),
            title_state,
            [],
            [],
            recent_sessions=12,
            config=_window_config(),
            initial_geometry=(0, 0, 420, 420),
        )
        window.show()
        self.application.processEvents()
        scroll_bar = window.history.verticalScrollBar()
        self.assertGreater(scroll_bar.maximum(), 0)
        scroll_bar.setValue(scroll_bar.maximum() // 2)
        middle_position = scroll_bar.value()

        window.refresh()
        self.application.processEvents()

        self.assertEqual(scroll_bar.value(), middle_position)
        scroll_bar.setValue(scroll_bar.maximum())

        window.refresh()
        self.application.processEvents()

        self.assertEqual(scroll_bar.value(), scroll_bar.maximum())

        new_session = Session(
            id="session-new",
            started_at=datetime(2026, 10, 13, tzinfo=timezone.utc),
            ended_at=datetime(2026, 10, 13, 1, tzinfo=timezone.utc),
            status=SessionStatus.COMPLETED,
        )
        updated_sessions = (*sessions_list, new_session)
        sessions.snapshot = HistorySnapshot(
            sessions=updated_sessions,
            stats=_calculate_test_streak(updated_sessions),
        )
        scroll_bar.setValue(scroll_bar.maximum() // 2)

        window.refresh()
        self.application.processEvents()

        self.assertEqual(scroll_bar.value(), scroll_bar.minimum())
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
            stats=_calculate_test_streak((unresolved, active, discarded)),
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
            config=_window_config(),
        )
        window._refresh_timer.stop()
        self.assertEqual(window.current_label.text(), "Current: Executor - Caligo")
        self.assertEqual(window.history.count(), 1)
        self.assertEqual(
            window.history.item(0).data(Qt.ItemDataRole.UserRole), "needs-resolution"
        )
        labels = window.history.itemWidget(window.history.item(0)).findChildren(QLabel)
        label_texts = [label.text() for label in labels]
        self.assertEqual(window.history.item(0).text(), "")
        self.assertIn(
            ended_at.astimezone().strftime("%Y/%m/%d %H:%M:%S"),
            label_texts,
        )
        self.assertNotIn(
            started_at.astimezone().strftime("%Y/%m/%d %H:%M:%S"),
            label_texts,
        )
        window.show()
        self.application.processEvents()
        item = window.history.item(0)
        item_position = window.history.visualItemRect(item).center()
        QTest.mouseClick(
            window.history.viewport(), Qt.MouseButton.LeftButton, pos=item_position
        )
        self.assertIs(window.history.currentItem(), item)
        QTest.mouseClick(
            window.history.viewport(), Qt.MouseButton.LeftButton, pos=item_position
        )
        self.assertIsNone(window.history.currentItem())
        self.assertEqual(window.history.selectedItems(), [])
        QTest.mouseClick(
            window.history.viewport(), Qt.MouseButton.LeftButton, pos=item_position
        )
        window.refresh()
        self.assertEqual(
            window.history.currentItem().data(Qt.ItemDataRole.UserRole),
            "needs-resolution",
        )
        button_texts = [button.text() for button in window.findChildren(QPushButton)]
        self.assertNotIn("Open config", button_texts)
        self.assertNotIn("Skip", button_texts)
        self.assertIn(window.settings_button, window._action_buttons)
        self.assertGreater(
            window.settings_button.geometry().top(),
            window.history.geometry().bottom(),
        )
        self.assertIn("Lock", button_texts)
        self.assertIn(
            'QPushButton#lockButton[locked="true"]:hover',
            window.centralWidget().styleSheet(),
        )
        window.lock_button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
        window._set_lock_button_locked(True)
        self.assertTrue(window.lock_button.property("locked"))
        self.assertIn("background: transparent", window.centralWidget().styleSheet())
        history_size = window.history.size()
        window.resize(620, 520)
        self.application.processEvents()
        self.assertGreater(window.history.width(), history_size.width())
        self.assertGreater(window.history.height(), history_size.height())
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()
