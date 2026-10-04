from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from app.nr_challenge_tracker.config import load_project_settings
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