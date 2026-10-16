from pathlib import Path
from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch

import yaml

from app.nr_challenge_tracker.config import (
    load_default_config,
    load_project_settings,
    save_user_config,
)
from app.nr_challenge_tracker.i18n import CATALOGS, resolve_language, tr


ROOT = Path(__file__).resolve().parents[1]


def _use_workspace_manifest(config: dict) -> None:
    config["paths"]["template_manifest"] = str(
        ROOT / config["paths"]["template_manifest"]
    )


class LanguageConfigTests(unittest.TestCase):
    def _load_with_language(self, language: str | None):
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        if language is None:
            config.pop("language", None)
        else:
            config["language"] = language
        _use_workspace_manifest(config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump(config), encoding="utf-8")
            return load_project_settings(Path(directory))[1]

    def test_debug_screenshots_default_to_disabled(self) -> None:
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        config.pop("debug")
        _use_workspace_manifest(config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump(config), encoding="utf-8")

            settings = load_project_settings(Path(directory))[1]

        self.assertFalse(settings.debug_save_screenshots)

    def test_debug_screenshots_can_be_enabled(self) -> None:
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        config["debug"]["save_screenshots"] = True
        _use_workspace_manifest(config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump(config), encoding="utf-8")

            settings = load_project_settings(Path(directory))[1]

        self.assertTrue(settings.debug_save_screenshots)

    def test_api_server_defaults_to_enabled_and_can_be_disabled(self) -> None:
        for enabled, expected in ((None, True), (False, False)):
            with self.subTest(enabled=enabled):
                config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
                if enabled is None:
                    config["api"].pop("enabled")
                else:
                    config["api"]["enabled"] = enabled
                _use_workspace_manifest(config)
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "config.yaml"
                    path.write_text(yaml.safe_dump(config), encoding="utf-8")

                    settings = load_project_settings(Path(directory))[1]

                self.assertEqual(settings.api_enabled, expected)

    def test_hud_always_on_top_defaults_to_enabled(self) -> None:
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        _use_workspace_manifest(config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump(config), encoding="utf-8")

            settings = load_project_settings(Path(directory))[1]

        self.assertTrue(settings.hud_always_on_top)

    def test_hud_always_on_top_can_be_disabled(self) -> None:
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        config["hud"]["always_on_top"] = False
        _use_workspace_manifest(config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump(config), encoding="utf-8")

            settings = load_project_settings(Path(directory))[1]

        self.assertFalse(settings.hud_always_on_top)

    def test_hud_nightlord_stats_visibility_defaults_to_enabled(self) -> None:
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        config["hud"].pop("show_nightlord_stats")
        _use_workspace_manifest(config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump(config), encoding="utf-8")

            loaded, settings = load_project_settings(
                Path(directory), assets_root=ROOT
            )

        self.assertTrue(loaded["hud"]["show_nightlord_stats"])
        self.assertTrue(settings.hud_show_nightlord_stats)

    def test_hud_nightlord_stats_visibility_can_be_disabled(self) -> None:
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        config["hud"]["show_nightlord_stats"] = False
        _use_workspace_manifest(config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump(config), encoding="utf-8")

            _loaded, settings = load_project_settings(
                Path(directory), assets_root=ROOT
            )

        self.assertFalse(settings.hud_show_nightlord_stats)

    def test_hud_nightlord_stats_mode_defaults_to_aggregated_wins(self) -> None:
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        config["hud"].pop("nightlord_stats_mode")
        _use_workspace_manifest(config)
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "config.yaml").write_text(
                yaml.safe_dump(config), encoding="utf-8"
            )

            loaded, _settings = load_project_settings(
                Path(directory), assets_root=ROOT
            )

        self.assertEqual(loaded["hud"]["nightlord_stats_mode"], "wins_aggregated")

    def test_hud_nightlord_stats_mode_is_saved_as_user_override(self) -> None:
        defaults = load_default_config(ROOT)
        effective = deepcopy(defaults)
        effective["hud"]["nightlord_stats_mode"] = "wins_separated"

        with tempfile.TemporaryDirectory() as directory:
            save_user_config(Path(directory), defaults, effective)
            saved = yaml.safe_load(
                Path(directory, "user-config.yaml").read_text(encoding="utf-8")
            )

        self.assertEqual(
            saved["hud"]["nightlord_stats_mode"], "wins_separated"
        )

    def test_hud_nightlord_stats_mode_rejects_unknown_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "user-config.yaml").write_text(
                yaml.safe_dump(
                    {"hud": {"nightlord_stats_mode": "invalid_mode"}}
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "nightlord_stats_mode"):
                load_project_settings(Path(directory), assets_root=ROOT)

    def test_language_defaults_to_auto_for_old_config(self) -> None:
        self.assertEqual(self._load_with_language(None).language, "auto")

    def test_supported_language_values_are_accepted(self) -> None:
        for language in ("auto", "en", "zh"):
            with self.subTest(language=language):
                self.assertEqual(self._load_with_language(language).language, language)

    def test_manifest_can_be_loaded_from_separate_asset_root(self) -> None:
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump(config), encoding="utf-8")

            settings = load_project_settings(Path(directory), assets_root=ROOT)[1]

        self.assertEqual(settings.target_window, "ELDEN RING NIGHTREIGN")

    def test_unsupported_language_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "language must be one of"):
            self._load_with_language("fr")

    def test_title_template_accepts_new_placeholders_and_rejects_old_ones(self) -> None:
        for template in (
            "{wins}/{total}/{streak}/{goal}",
            "normal: {wins}/{total}",
            "streak: {streak}/{goal}",
        ):
            with self.subTest(template=template), tempfile.TemporaryDirectory() as directory:
                config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
                config["bilibili"]["title_template"] = template
                _use_workspace_manifest(config)
                Path(directory, "config.yaml").write_text(
                    yaml.safe_dump(config), encoding="utf-8"
                )

                loaded = load_project_settings(Path(directory))[1]

                self.assertEqual(loaded.title_template, template)

        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        config["bilibili"]["title_template"] = "{current_streak}/{target}"
        _use_workspace_manifest(config)
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "config.yaml").write_text(
                yaml.safe_dump(config), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "title_template"):
                load_project_settings(Path(directory))

    def test_user_config_loads_challenges_and_other_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "user-config.yaml").write_text(
                yaml.safe_dump(
                    {
                        "challenges": [{
                            "id": "wins",
                            "name": "Executor wins",
                            "type": "winning_streak",
                            "eligible_nightfarer": "executor",
                            "target": 75,
                            "excluded_session_ids": [],
                        }],
                        "active_challenge_id": "wins",
                        "hud": {"opacity": 0.55},
                    }
                ),
                encoding="utf-8",
            )

            config, settings = load_project_settings(root, assets_root=ROOT)

        self.assertEqual(config["challenges"][0]["target"], 75)
        self.assertEqual(config["hud"]["opacity"], 0.55)
        self.assertEqual(config["recognition"]["sampling"]["idle_ms"], 1000)

    def test_user_config_accepts_zero_streak_goal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "user-config.yaml").write_text(
                yaml.safe_dump(
                    {
                        "challenges": [{
                            "id": "wins",
                            "name": "Executor wins",
                            "type": "winning_streak",
                            "eligible_nightfarer": "executor",
                            "target": 0,
                            "excluded_session_ids": [],
                        }],
                        "active_challenge_id": "wins",
                    }
                ),
                encoding="utf-8",
            )

            config, _settings = load_project_settings(root, assets_root=ROOT)

        self.assertEqual(config["challenges"][0]["target"], 0)

    def test_user_config_accepts_any_as_eligible_nightfarer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "user-config.yaml").write_text(
                yaml.safe_dump(
                    {
                        "challenges": [{
                            "id": "wins",
                            "name": "Any Nightfarer wins",
                            "type": "winning_streak",
                            "eligible_nightfarer": "any",
                            "target": 75,
                            "excluded_session_ids": [],
                        }],
                        "active_challenge_id": "wins",
                    }
                ),
                encoding="utf-8",
            )

            config, _settings = load_project_settings(root, assets_root=ROOT)

        self.assertEqual(
            config["challenges"][0]["eligible_nightfarer"], "any"
        )

    def test_user_config_rejects_unavailable_challenge_nightfarer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "user-config.yaml").write_text(
                yaml.safe_dump(
                    {
                        "challenges": [{
                            "id": "wins",
                            "name": "Executor wins",
                            "type": "winning_streak",
                            "eligible_nightfarer": "missing",
                            "target": 75,
                            "excluded_session_ids": [],
                        }],
                        "active_challenge_id": "wins",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "eligible_nightfarer"):
                load_project_settings(root, assets_root=ROOT)

    def test_saved_user_config_contains_settings_and_challenges(self) -> None:
        defaults = load_default_config(ROOT)
        effective = deepcopy(defaults)
        effective["hud"]["opacity"] = 0.55
        effective["challenges"] = [
            {
                "id": "all",
                "name": "All",
                "type": "normal",
                "excluded_session_ids": [],
            }
        ]
        effective["active_challenge_id"] = "all"
        effective["paths"]["template_manifest"] = "ignored"

        with tempfile.TemporaryDirectory() as directory:
            save_user_config(Path(directory), defaults, effective)
            saved = yaml.safe_load(
                (Path(directory) / "user-config.yaml").read_text(encoding="utf-8")
            )

        self.assertEqual(
            saved,
            {
                "hud": {"opacity": 0.55},
                "challenges": effective["challenges"],
                "active_challenge_id": "all",
            },
        )

    def test_legacy_config_is_migrated_to_sparse_user_config(self) -> None:
        legacy = load_default_config(ROOT)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.yaml").write_text(
                yaml.safe_dump(legacy), encoding="utf-8"
            )

            config, settings = load_project_settings(root, assets_root=ROOT)
            migrated = yaml.safe_load(
                (root / "user-config.yaml").read_text(encoding="utf-8")
            )

        self.assertEqual(config["challenges"][0]["type"], "normal")
        self.assertEqual(migrated["challenges"][0]["type"], "normal")

    def test_legacy_streak_config_is_migrated_to_a_challenge(self) -> None:
        legacy = load_default_config(ROOT)
        legacy["streak"] = {
            "target": 75,
            "eligible_nightfarer": "Executor",
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Path(root, "config.yaml").write_text(
                yaml.safe_dump(legacy), encoding="utf-8"
            )

            config, _settings = load_project_settings(root, assets_root=ROOT)
            migrated = yaml.safe_load(
                (root / "user-config.yaml").read_text(encoding="utf-8")
            )

        self.assertEqual(config["active_challenge_id"], "legacy-streak")
        self.assertEqual(
            config["challenges"][0],
            {
                "id": "legacy-streak",
                "name": "Legacy streak",
                "type": "winning_streak",
                "excluded_session_ids": [],
                "eligible_nightfarer": "executor",
                "target": 75,
            },
        )
        self.assertEqual(migrated["challenges"], config["challenges"])

    def test_legacy_streak_config_accepts_any_nightfarer(self) -> None:
        legacy = load_default_config(ROOT)
        legacy["streak"] = {
            "target": 75,
            "eligible_nightfarer": "any",
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Path(root, "config.yaml").write_text(
                yaml.safe_dump(legacy), encoding="utf-8"
            )

            config, _settings = load_project_settings(root, assets_root=ROOT)

        self.assertEqual(
            config["challenges"][0]["eligible_nightfarer"], "any"
        )

    def test_legacy_user_config_streak_is_migrated_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Path(root, "user-config.yaml").write_text(
                yaml.safe_dump(
                    {"streak": {"target": 50, "eligible_nightfarer": "recluse"}}
                ),
                encoding="utf-8",
            )

            config, _settings = load_project_settings(root, assets_root=ROOT)
            migrated = yaml.safe_load(
                (root / "user-config.yaml").read_text(encoding="utf-8")
            )

        self.assertEqual(config["active_challenge_id"], "legacy-streak")
        self.assertEqual(config["challenges"][0]["eligible_nightfarer"], "recluse")
        self.assertEqual(config["challenges"][0]["target"], 50)
        self.assertNotIn("streak", migrated)
        self.assertEqual(migrated["challenges"], config["challenges"])

    def test_user_config_cannot_override_paths_or_recognition_geometry(self) -> None:
        for override in (
            {"paths": {"template_manifest": "elsewhere.yaml"}},
            {"recognition": {"preparation_nightlord_roi": [0, 0, 1, 1]}},
        ):
            with self.subTest(override=override), tempfile.TemporaryDirectory() as directory:
                Path(directory, "user-config.yaml").write_text(
                    yaml.safe_dump(override), encoding="utf-8"
                )

                with self.assertRaisesRegex(ValueError, "field is not editable"):
                    load_project_settings(Path(directory), assets_root=ROOT)

    def test_auto_uses_chinese_only_for_chinese_locales(self) -> None:
        self.assertEqual(resolve_language("auto", ["zh-CN"]), "zh")
        self.assertEqual(resolve_language("auto", ["zh-TW"]), "zh")
        self.assertEqual(resolve_language("auto", ["en-US"]), "en")
        self.assertEqual(resolve_language("auto", ["fr-FR"]), "en")

    def test_auto_uses_first_supported_ui_language(self) -> None:
        self.assertEqual(
            resolve_language("auto", ["fr-FR", "zh-CN", "en-US"]), "zh"
        )
        self.assertEqual(resolve_language("auto", ["zh-CN", "en-US"]), "zh")

    def test_auto_reads_qt_ui_languages(self) -> None:
        with patch("app.nr_challenge_tracker.i18n.QLocale.system") as system_locale:
            system_locale.return_value.uiLanguages.return_value = ["zh-Hans-CN"]

            self.assertEqual(resolve_language("auto"), "zh")

            system_locale.assert_called_once_with()
            system_locale.return_value.uiLanguages.assert_called_once_with()

    def test_explicit_language_overrides_system_locale(self) -> None:
        self.assertEqual(resolve_language("en", ["zh-CN"]), "en")
        self.assertEqual(resolve_language("zh", ["en-US"]), "zh")

    def test_catalogs_are_indexed_by_message_key_then_language(self) -> None:
        self.assertEqual(CATALOGS["actions"]["pause"]["en"], "Pause")
        self.assertEqual(CATALOGS["actions"]["pause"]["zh"], "暂停")
        self.assertEqual(tr("en", "actions.pause"), "Pause")
        self.assertEqual(tr("zh", "actions.pause"), "暂停")
        self.assertEqual(tr("fr", "actions.pause"), "Pause")


if __name__ == "__main__":
    unittest.main()