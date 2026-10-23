import os
import tempfile
import tomllib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDateTime, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QWidget,
)

from app.nr_challenge_tracker.config import load_default_config, load_project_settings
from app.nr_challenge_tracker.challenge_dialog import ChallengeManagerDialog
from app.nr_challenge_tracker.challenges import ChallengeType
from app.nr_challenge_tracker.history import HistorySnapshot
from app.nr_challenge_tracker.i18n import tr
from app.nr_challenge_tracker.models import (
    ANY_NIGHTFARER,
    NightlordVariant,
    Progress,
    Session,
    SessionStatus,
)
from app.nr_challenge_tracker.streak import calculate_streak
from app.nr_challenge_tracker.settings_dialog import SettingsDialog
from app.nr_challenge_tracker.ui import (
    ResolveSessionDialog,
    TrackerWindow,
)
from tools.extract_templates import NIGHTLORDS as TEMPLATE_NIGHTLORDS

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

    def test_nightlord_catalogs_and_resolution_picker_use_requested_order(self) -> None:
        expected_order = [
            "gladius",
            "adel",
            "gnoster",
            "maris",
            "libra",
            "fulghor",
            "caligo",
            "heolstor",
            "harmonia",
            "straghess",
        ]
        manifest = yaml.safe_load(
            (ROOT / "assets" / "templates" / "manifest.yaml").read_text(
                encoding="utf-8"
            )
        )
        translations = yaml.safe_load(
            (ROOT / "assets" / "translations.yaml").read_text(encoding="utf-8")
        )
        nightlords = [entry["id"] for entry in manifest["nightlords"]]

        self.assertEqual(list(TEMPLATE_NIGHTLORDS), expected_order)
        self.assertEqual(nightlords, expected_order)
        self.assertEqual(list(translations["nightlords"]), expected_order)

        dialog = ResolveSessionDialog([], [], nightlords)
        self.assertEqual(
            [
                dialog.nightlord.itemData(index)
                for index in range(1, dialog.nightlord.count())
            ],
            expected_order,
        )
        dialog.close()

    def test_dialog_choices_use_stable_data_values(self) -> None:
        dialog = ResolveSessionDialog([], ["executor"], ["adel"], language="en")

        self.assertEqual(dialog.nightfarer.itemData(1), "executor")
        self.assertEqual(
            [dialog.nightlord.itemData(index) for index in range(2)],
            [None, "adel"],
        )
        self.assertIsNone(dialog.progress.currentData())
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

    def test_api_server_can_be_disabled_and_userscript_url_is_interactive(self) -> None:
        defaults = load_default_config(ROOT)
        with tempfile.TemporaryDirectory() as directory:
            dialog = SettingsDialog(
                Path(directory),
                defaults,
                defaults,
                ["executor", "recluse"],
                language="en",
                assets_root=ROOT,
                userscript_url="http://127.0.0.1:5678/bilibili.user.js",
            )
            enabled = dialog.editors["api.enabled"]
            self.assertTrue(enabled.isChecked())
            self.assertFalse(dialog.reset_buttons["api.enabled"].isEnabled())
            install_link = dialog.findChild(QLabel, "bilibiliInstallUrl")
            self.assertIsNotNone(install_link)
            self.assertIn(
                "http://127.0.0.1:5678/bilibili.user.js",
                install_link.text(),
            )
            self.assertTrue(install_link.openExternalLinks())
            self.assertTrue(
                install_link.textInteractionFlags()
                & Qt.TextInteractionFlag.TextSelectableByMouse
            )
            enabled.setChecked(False)
            dialog._save()

            saved = yaml.safe_load(
                (Path(directory) / "user-config.yaml").read_text(encoding="utf-8")
            )

        self.assertEqual(saved, {"api": {"enabled": False}})

        dialog = SettingsDialog(
            Path(tempfile.gettempdir()),
            defaults,
            defaults,
            ["executor", "recluse"],
            language="zh",
            assets_root=ROOT,
            userscript_url="http://127.0.0.1:5678/bilibili.user.js",
        )
        install_link = dialog.findChild(QLabel, "bilibiliInstallUrl")
        self.assertIsNotNone(install_link)
        dialog.close()

    def test_about_section_shows_project_metadata_and_external_repository_link(self) -> None:
        defaults = load_default_config(ROOT)
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        dialog = SettingsDialog(
            Path(tempfile.gettempdir()),
            defaults,
            defaults,
            ["executor"],
            language="en",
            assets_root=ROOT,
        )

        version = dialog.findChild(QLabel, "appVersion")
        repository_link = dialog.findChild(QLabel, "repositoryLink")

        self.assertIsNotNone(version)
        self.assertEqual(version.text(), project["project"]["version"])
        self.assertIsNotNone(repository_link)
        self.assertIn(
            project["project"]["urls"]["Repository"],
            repository_link.text(),
        )
        self.assertIn(
            f">{project['project']['urls']['Repository']}</a>",
            repository_link.text(),
        )
        self.assertTrue(repository_link.openExternalLinks())

        dialog.close()

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

    def test_invalid_settings_error_uses_the_selected_language(self) -> None:
        defaults = load_default_config(ROOT)
        for language in ("en", "zh"):
            with tempfile.TemporaryDirectory() as directory:
                dialog = SettingsDialog(
                    Path(directory),
                    defaults,
                    defaults,
                    ["executor"],
                    language=language,
                    assets_root=ROOT,
                )
                with (
                    patch(
                        "app.nr_challenge_tracker.settings_dialog.validate_project_config",
                        side_effect=ValueError("invalid input"),
                    ),
                    patch(
                        "app.nr_challenge_tracker.settings_dialog.QMessageBox.warning"
                    ) as warning,
                ):
                    dialog._save()

                warning.assert_called_once_with(
                    dialog,
                    tr(language, "settings.title"),
                    tr(
                        language,
                        "settings.invalid",
                        error=tr(
                            language,
                            "common.error_details",
                            error="invalid input",
                        ),
                    ),
                )
                dialog.close()

    def test_nightlord_stats_visibility_can_be_saved(self) -> None:
        defaults = load_default_config(ROOT)
        with tempfile.TemporaryDirectory() as directory:
            dialog = SettingsDialog(
                Path(directory),
                defaults,
                defaults,
                ["executor"],
                language="en",
                assets_root=ROOT,
            )
            editor = dialog.editors["hud.show_nightlord_stats"]
            self.assertTrue(editor.isChecked())
            editor.setChecked(False)
            dialog._save()
            saved = yaml.safe_load(
                (Path(directory) / "user-config.yaml").read_text(encoding="utf-8")
            )

        self.assertEqual(saved, {"hud": {"show_nightlord_stats": False}})

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

    def test_missing_eligible_nightfarer_defaults_to_any(self) -> None:
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
            config, (), ["executor"], parent, language="en"
        )

        dialog.type.setCurrentIndex(
            dialog.type.findData(ChallengeType.WINNING_STREAK.value)
        )

        self.assertEqual(dialog.nightfarer.currentData(), ANY_NIGHTFARER)

        dialog.close()

    def test_pre_start_sessions_remain_visible_but_disabled(self) -> None:
        start_time = datetime(2026, 10, 3, tzinfo=timezone.utc)
        sessions = (
            Session("before", start_time - timedelta(minutes=1)),
            Session("boundary", start_time),
            Session("after", start_time + timedelta(minutes=1)),
        )
        config = _window_config()
        config["challenges"][0]["start_time"] = start_time.isoformat()
        config["challenges"][0]["excluded_session_ids"] = ["before"]
        parent = QWidget()
        dialog = ChallengeManagerDialog(
            config, sessions, ["executor"], parent, language="en"
        )

        items = {
            dialog.exclusions.item(index).data(256): dialog.exclusions.item(index)
            for index in range(dialog.exclusions.count())
        }
        self.assertEqual(set(items), {"before", "boundary", "after"})
        self.assertFalse(items["before"].flags() & Qt.ItemFlag.ItemIsEnabled)
        self.assertTrue(items["before"].checkState() is Qt.CheckState.Checked)
        self.assertTrue(items["boundary"].flags() & Qt.ItemFlag.ItemIsEnabled)
        self.assertTrue(items["after"].flags() & Qt.ItemFlag.ItemIsEnabled)

        later_start = start_time + timedelta(minutes=1)
        dialog.start_time.setDateTime(
            QDateTime.fromSecsSinceEpoch(round(later_start.timestamp()))
        )
        self.assertFalse(items["boundary"].flags() & Qt.ItemFlag.ItemIsEnabled)
        self.assertTrue(items["after"].flags() & Qt.ItemFlag.ItemIsEnabled)
        dialog._store_selected()
        self.assertEqual(
            dialog.config["challenges"][0]["excluded_session_ids"], ["before"]
        )

        dialog.close()

    def test_any_nightfarer_is_available_as_a_streak_choice(self) -> None:
        config = load_default_config(ROOT)
        config["challenges"] = [{
            "id": "streak",
            "name": "Any Nightfarer",
            "type": "winning_streak",
            "eligible_nightfarer": ANY_NIGHTFARER,
            "target": 100,
            "excluded_session_ids": [],
        }]
        config["active_challenge_id"] = "streak"
        parent = QWidget()
        dialog = ChallengeManagerDialog(
            config, (), ["executor"], parent, language="en"
        )

        self.assertEqual(dialog.nightfarer.itemData(0), ANY_NIGHTFARER)
        self.assertEqual(dialog.nightfarer.itemText(0), "Any Nightfarer")

        dialog.close()

    def test_streak_goal_can_be_set_to_zero(self) -> None:
        config = _window_config()
        parent = QWidget()
        dialog = ChallengeManagerDialog(
            config, (), ["executor"], parent, language="en"
        )

        dialog.type.setCurrentIndex(
            dialog.type.findData(ChallengeType.WINNING_STREAK.value)
        )
        dialog.target.setValue(0)
        dialog._store_selected()

        self.assertEqual(dialog.target.minimum(), 0)
        self.assertEqual(dialog.config["challenges"][0]["target"], 0)

        dialog.close()

    def test_initial_streak_values_are_saved_and_best_tracks_current_minimum(self) -> None:
        config = _window_config()
        parent = QWidget()
        dialog = ChallengeManagerDialog(
            config, (), ["executor"], parent, language="en"
        )

        self.assertTrue(dialog.initial_current_streak.isEnabled())
        self.assertTrue(dialog.initial_best_streak.isEnabled())
        dialog.initial_current_streak.setValue(5)
        self.assertEqual(dialog.initial_best_streak.minimum(), 5)
        dialog.initial_best_streak.setValue(12)
        dialog._store_selected()

        self.assertEqual(
            dialog.config["challenges"][0]["initial_current_streak"], 5
        )
        self.assertEqual(dialog.config["challenges"][0]["initial_best_streak"], 12)

        dialog.type.setCurrentIndex(
            dialog.type.findData(ChallengeType.NORMAL.value)
        )
        self.assertFalse(dialog.initial_current_streak.isEnabled())
        self.assertFalse(dialog.initial_best_streak.isEnabled())

        dialog.close()

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

class TrackerWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_title_sync_status_appears_after_userscript_connects(self) -> None:
        sessions = Mock(
            snapshot=HistorySnapshot(sessions=(), stats=_calculate_test_streak(()))
        )
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }
        window = TrackerWindow(
            sessions, Mock(), title_state, [], [], config=_window_config()
        )

        self.assertTrue(window.sync_label.isHidden())

        window.userscript_connected.emit()
        self.application.processEvents()

        self.assertFalse(window.sync_label.isHidden())
        window.close()

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

    def test_hud_shows_nightlord_runs_and_wins_by_variant(self) -> None:
        started_at = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
        session_ids = ("normal-win", "normal-loss", "everdark-win")
        sessions = (
            Session(
                id=session_ids[0],
                started_at=started_at,
                ended_at=started_at,
                nightlord_name="caligo",
                nightlord_variant=NightlordVariant.NORMAL,
                progress=Progress.DAY_3_VICTORY,
                status=SessionStatus.COMPLETED,
            ),
            Session(
                id=session_ids[1],
                started_at=started_at,
                ended_at=started_at,
                nightlord_name="caligo",
                nightlord_variant=NightlordVariant.NORMAL,
                progress=Progress.DAY_2,
                status=SessionStatus.COMPLETED,
            ),
            Session(
                id=session_ids[2],
                started_at=started_at,
                ended_at=started_at,
                nightlord_name="caligo",
                nightlord_variant=NightlordVariant.EVERDARK,
                progress=Progress.DAY_3_VICTORY,
                status=SessionStatus.COMPLETED,
            ),
        )
        session_service = Mock(
            snapshot=HistorySnapshot(
                sessions=sessions,
                stats=_calculate_test_streak(()),
            )
        )
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }
        config = _window_config()
        config["challenges"][0] = {
            "id": "normal",
            "name": "Normal",
            "type": "normal",
            "excluded_session_ids": [],
        }
        config["active_challenge_id"] = "normal"
        config["challenges"][0]["excluded_session_ids"] = list(session_ids)

        with tempfile.TemporaryDirectory() as directory:
            window = TrackerWindow(
                session_service,
                Mock(),
                title_state,
                [],
                [],
                defaults_config=load_default_config(ROOT),
                config=config,
                config_root=Path(directory),
                assets_root=ROOT,
            )
            window.show()
            self.application.processEvents()

            self.assertTrue(window.nightlord_stats_grid.isVisible())
            config["hud"]["show_nightlord_stats"] = False
            window.apply_live_settings(config)
            self.assertFalse(window.nightlord_stats_grid.isVisible())
            config["hud"]["show_nightlord_stats"] = True
            window.apply_live_settings(config)
            self.assertTrue(window.nightlord_stats_grid.isVisible())

            self.assertEqual(
                window.nightlord_stats_grid.heading_label.text(),
                f"{tr('en', 'hud.nightlord_stats_heading_wins_aggregated')}:",
            )
            self.assertEqual(
                [label.text() for label in window.nightlord_stats_grid.name_labels],
                ["Caligo"],
            )
            self.assertEqual(
                [label.text() for label in window.nightlord_stats_grid.stats_labels],
                [tr("en", "hud.nightlord_stats_wins_entry", wins=2)],
            )
            start_position = window.pos()
            QTest.mouseClick(
                window.nightlord_stats_grid,
                Qt.MouseButton.LeftButton,
                pos=window.nightlord_stats_grid.cell_widgets[0].geometry().center(),
            )
            self.assertEqual(window.pos(), start_position)
            self.assertEqual(
                window.nightlord_stats_grid.heading_label.text(),
                f"{tr('en', 'hud.nightlord_stats_heading_wins_total_aggregated')}:",
            )
            self.assertEqual(
                [label.text() for label in window.nightlord_stats_grid.stats_labels],
                [tr("en", "hud.nightlord_stats_total_entry", wins=2, total=3)],
            )
            saved = yaml.safe_load(
                Path(directory, "user-config.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(
                saved["hud"]["nightlord_stats_mode"], "wins_total_aggregated"
            )

            QTest.mouseClick(
                window.nightlord_stats_grid,
                Qt.MouseButton.LeftButton,
                pos=window.nightlord_stats_grid.cell_widgets[0].geometry().center(),
            )
            self.assertEqual(
                window.nightlord_stats_grid.heading_label.text(),
                f"{tr('en', 'hud.nightlord_stats_heading_wins_separated')}:",
            )
            self.assertEqual(
                [label.text() for label in window.nightlord_stats_grid.stats_labels],
                [
                    tr(
                        "en",
                        "hud.nightlord_stats_split_entry",
                        normal_wins=1,
                        everdark_wins=1,
                    )
                ],
            )
            loaded, _settings = load_project_settings(
                Path(directory), assets_root=ROOT
            )
            self.assertEqual(
                loaded["hud"]["nightlord_stats_mode"], "wins_separated"
            )

            QTest.mouseClick(
                window.nightlord_stats_grid,
                Qt.MouseButton.LeftButton,
                pos=window.nightlord_stats_grid.cell_widgets[0].geometry().center(),
            )
            self.assertEqual(
                window.nightlord_stats_grid.heading_label.text(),
                f"{tr('en', 'hud.nightlord_stats_heading_wins_aggregated')}:",
            )
            self.assertEqual(
                [label.text() for label in window.nightlord_stats_grid.stats_labels],
                [tr("en", "hud.nightlord_stats_wins_entry", wins=2)],
            )
            with (
                patch(
                    "app.nr_challenge_tracker.ui.save_user_config",
                    side_effect=ValueError("disk full"),
                ),
                patch(
                    "app.nr_challenge_tracker.ui.QMessageBox.warning"
                ) as warning,
            ):
                QTest.mouseClick(
                    window.nightlord_stats_grid,
                    Qt.MouseButton.LeftButton,
                    pos=window.nightlord_stats_grid.cell_widgets[0].geometry().center(),
                )
            self.assertEqual(
                window.nightlord_stats_grid.heading_label.text(),
                f"{tr('en', 'hud.nightlord_stats_heading_wins_aggregated')}:",
            )
            warning.assert_called_once()
            self.assertEqual(
                warning.call_args.args[2],
                tr(
                    "en",
                    "hud.nightlord_stats_save_error",
                    error=tr(
                        "en",
                        "common.error_details",
                        error="disk full",
                    ),
                ),
            )
            window.close()

    def test_winning_streak_nightlord_stats_use_only_current_eligible_runs(self) -> None:
        def make_session(
            session_id: str,
            minute: int,
            nightlord: str,
            variant: NightlordVariant,
            progress: Progress,
            nightfarer: str = ELIGIBLE_NIGHTFARER,
        ) -> Session:
            started_at = datetime(
                2026, 10, 3, 12, minute=minute, tzinfo=timezone.utc
            )
            return Session(
                id=session_id,
                started_at=started_at,
                ended_at=started_at,
                nightfarer=nightfarer,
                nightlord_name=nightlord,
                nightlord_variant=variant,
                progress=progress,
                status=SessionStatus.COMPLETED,
            )

        sessions = (
            make_session(
                "old-win",
                0,
                "caligo",
                NightlordVariant.NORMAL,
                Progress.DAY_3_VICTORY,
            ),
            make_session(
                "streak-loss",
                1,
                "adel",
                NightlordVariant.NORMAL,
                Progress.DAY_2,
            ),
            make_session(
                "excluded-win",
                2,
                "adel",
                NightlordVariant.EVERDARK,
                Progress.DAY_3_VICTORY,
            ),
            make_session(
                "current-normal",
                3,
                "caligo",
                NightlordVariant.NORMAL,
                Progress.DAY_3_VICTORY,
            ),
            make_session(
                "ineligible-win",
                4,
                "adel",
                NightlordVariant.NORMAL,
                Progress.DAY_3_VICTORY,
                nightfarer="raider",
            ),
            make_session(
                "current-everdark",
                5,
                "caligo",
                NightlordVariant.EVERDARK,
                Progress.DAY_3_VICTORY,
            ),
            make_session(
                "current-adel",
                6,
                "adel",
                NightlordVariant.NORMAL,
                Progress.DAY_3_VICTORY,
            ),
        )
        session_service = Mock(
            snapshot=HistorySnapshot(
                sessions=sessions,
                stats=_calculate_test_streak(sessions),
            )
        )
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }
        config = _window_config()
        config["challenges"][0]["excluded_session_ids"] = ["excluded-win"]
        config["hud"]["nightlord_stats_mode"] = "wins_total_aggregated"

        window = TrackerWindow(
            session_service,
            Mock(),
            title_state,
            [],
            [],
            config=config,
        )

        self.assertEqual(
            window.nightlord_stats_grid.name_labels[0].text(),
            "Adel",
        )
        self.assertEqual(
            [label.text() for label in window.nightlord_stats_grid.name_labels],
            ["Adel", "Caligo"],
        )
        self.assertEqual(
            [label.text() for label in window.nightlord_stats_grid.stats_labels],
            [
                tr("en", "hud.nightlord_stats_total_entry", wins=1, total=1),
                tr("en", "hud.nightlord_stats_total_entry", wins=2, total=2),
            ],
        )
        window.close()

    def test_nightlord_stats_follow_requested_order(self) -> None:
        nightlords = [
            "gladius",
            "adel",
            "gnoster",
            "maris",
            "libra",
            "fulghor",
            "caligo",
            "heolstor",
            "harmonia",
            "straghess",
        ]
        sessions = tuple(
            Session(
                id=f"run-{nightlord}",
                started_at=datetime(2026, 10, 3, 12, minute=index, tzinfo=timezone.utc),
                ended_at=datetime(2026, 10, 3, 12, minute=index, tzinfo=timezone.utc),
                nightfarer=ELIGIBLE_NIGHTFARER,
                nightlord_name=nightlord,
                nightlord_variant=NightlordVariant.NORMAL,
                progress=Progress.DAY_3_VICTORY,
                status=SessionStatus.COMPLETED,
            )
            for index, nightlord in enumerate(reversed(nightlords))
        )
        session_service = Mock(
            snapshot=HistorySnapshot(
                sessions=sessions,
                stats=_calculate_test_streak(sessions),
            )
        )
        title_state = Mock()
        title_state.update.return_value = {
            "sync_status": "sync.disabled",
            "sync_message": "",
        }

        window = TrackerWindow(
            session_service,
            Mock(),
            title_state,
            [],
            nightlords,
            config=_window_config(),
        )

        self.assertEqual(
            [label.text() for label in window.nightlord_stats_grid.name_labels],
            [
                "Gladius",
                "Adel",
                "Gnoster",
                "Maris",
                "Libra",
                "Fulghor",
                "Caligo",
                "Heolstor",
                "Harmonia",
                "Straghess",
            ],
        )
        window.close()

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

        current_lines = window.current_label.text().splitlines()
        self.assertEqual(len(current_lines), 2)
        self.assertTrue(all(current_lines))
        self.assertIs(snapshot.sessions[0].status, SessionStatus.ACTIVE)
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

        self.assertEqual(window.history.count(), 3)
        self.assertEqual(
            [
                window.history.item(index).data(Qt.ItemDataRole.UserRole)
                for index in range(2)
            ],
            ["session-3", "session-2"],
        )
        self.assertEqual(window.history.item(2).text(), "Showing 2 recent sessions (total 4)")
        self.assertEqual(
            window.history.item(2).flags(),
            Qt.ItemFlag.NoItemFlags,
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

        self.assertEqual(window.history.count(), 2)
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
        self.assertEqual(scroll_bar.value(), scroll_bar.minimum())
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

if __name__ == "__main__":
    unittest.main()
