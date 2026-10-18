import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from app.nr_challenge_tracker import i18n


class TranslationOverrideTests(unittest.TestCase):
    def _load_catalog(
        self, directory: Path, base_catalog: dict, user_catalog: str | None = None
    ) -> dict:
        translations_path = directory / "translations.yaml"
        translations_path.write_text(
            yaml.safe_dump(base_catalog), encoding="utf-8"
        )
        user_translations_path = directory / "user-translations.yaml"
        if user_catalog is not None:
            user_translations_path.write_text(user_catalog, encoding="utf-8")

        with (
            patch.object(i18n, "_TRANSLATIONS_PATH", translations_path),
            patch.object(i18n, "_USER_TRANSLATIONS_PATH", user_translations_path),
        ):
            return i18n._load_catalog()

    def test_missing_override_keeps_bundled_catalog(self) -> None:
        base_catalog = {"common": {"save": {"en": "Save", "zh": "保存"}}}
        with tempfile.TemporaryDirectory() as temporary_directory:
            catalog = self._load_catalog(Path(temporary_directory), base_catalog)

        self.assertEqual(catalog, base_catalog)

    def test_partial_override_recursively_replaces_only_provided_values(self) -> None:
        base_catalog = {
            "common": {"save": {"en": "Save", "zh": "保存"}},
            "app": {"title": {"en": "Tracker", "zh": "追踪器"}},
        }
        user_catalog = "common:\n  save:\n    en: Store\n"
        with tempfile.TemporaryDirectory() as temporary_directory:
            catalog = self._load_catalog(
                Path(temporary_directory), base_catalog, user_catalog
            )

        self.assertEqual(
            catalog,
            {
                "common": {"save": {"en": "Store", "zh": "保存"}},
                "app": {"title": {"en": "Tracker", "zh": "追踪器"}},
            },
        )
        with patch.object(i18n, "CATALOGS", catalog):
            self.assertEqual(i18n.tr("en", "common.save"), "Store")

    def test_invalid_override_yaml_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(
                RuntimeError, "Could not load user translations"
            ):
                self._load_catalog(
                    Path(temporary_directory),
                    {"common": {"save": {"en": "Save"}}},
                    "common: [",
                )

    def test_non_mapping_override_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(
                RuntimeError, "User translation catalog must be a YAML mapping"
            ):
                self._load_catalog(
                    Path(temporary_directory),
                    {"common": {"save": {"en": "Save"}}},
                    "- not a mapping\n",
                )
