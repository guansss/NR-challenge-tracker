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

    def test_language_defaults_to_auto_for_old_config(self) -> None:
        self.assertEqual(self._load_with_language(None).language, "auto")

    def test_supported_language_values_are_accepted(self) -> None:
        for language in ("auto", "en", "zh"):
            with self.subTest(language=language):
                self.assertEqual(self._load_with_language(language).language, language)

    def test_eligible_nightfarer_is_loaded_from_config(self) -> None:
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        config["streak"]["eligible_nightfarer"] = "recluse"
        _use_workspace_manifest(config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump(config), encoding="utf-8")

            settings = load_project_settings(Path(directory))[1]

        self.assertEqual(settings.eligible_nightfarer, "recluse")

    def test_manifest_can_be_loaded_from_separate_asset_root(self) -> None:
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump(config), encoding="utf-8")

            settings = load_project_settings(Path(directory), assets_root=ROOT)[1]

        self.assertEqual(settings.eligible_nightfarer, "executor")

    def test_eligible_nightfarer_rejects_display_names(self) -> None:
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        config["streak"]["eligible_nightfarer"] = "Recluse"
        _use_workspace_manifest(config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump(config), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "eligible_nightfarer"):
                load_project_settings(Path(directory))

    def test_unsupported_language_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "language must be one of"):
            self._load_with_language("fr")

    def test_boolean_is_rejected_for_integer_settings(self) -> None:
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        config["streak"]["target"] = True
        _use_workspace_manifest(config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump(config), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "streak.target"):
                load_project_settings(Path(directory))

    def test_user_config_recursively_overrides_bundled_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "user-config.yaml").write_text(
                yaml.safe_dump(
                    {"streak": {"target": 75}, "hud": {"opacity": 0.55}}
                ),
                encoding="utf-8",
            )

            config, settings = load_project_settings(root, assets_root=ROOT)

        self.assertEqual(config["streak"]["target"], 75)
        self.assertEqual(config["hud"]["opacity"], 0.55)
        self.assertEqual(config["recognition"]["sampling"]["idle_ms"], 1000)
        self.assertEqual(settings.target, 75)

    def test_saved_user_config_contains_only_changed_editable_fields(self) -> None:
        defaults = load_default_config(ROOT)
        effective = deepcopy(defaults)
        effective["streak"]["target"] = 75
        effective["hud"]["opacity"] = 0.55
        effective["paths"]["template_manifest"] = "ignored"

        with tempfile.TemporaryDirectory() as directory:
            save_user_config(Path(directory), defaults, effective)
            saved = yaml.safe_load(
                (Path(directory) / "user-config.yaml").read_text(encoding="utf-8")
            )

        self.assertEqual(saved, {"streak": {"target": 75}, "hud": {"opacity": 0.55}})

    def test_legacy_config_is_migrated_to_sparse_user_config(self) -> None:
        legacy = load_default_config(ROOT)
        legacy["streak"]["target"] = 65

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.yaml").write_text(
                yaml.safe_dump(legacy), encoding="utf-8"
            )

            config, settings = load_project_settings(root, assets_root=ROOT)
            migrated = yaml.safe_load(
                (root / "user-config.yaml").read_text(encoding="utf-8")
            )

        self.assertEqual(config["streak"]["target"], 65)
        self.assertEqual(settings.target, 65)
        self.assertEqual(migrated, {"streak": {"target": 65}})

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