"""Language selection and UI messages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import QLocale

SUPPORTED_LANGUAGES = frozenset({"en", "zh"})

_TRANSLATIONS_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "translations.yaml"
)


def _load_catalog() -> dict[str, Any]:
    try:
        catalog = yaml.safe_load(_TRANSLATIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RuntimeError(f"Could not load translations: {error}") from error
    if not isinstance(catalog, dict):
        raise RuntimeError("Translation catalog must be a YAML mapping")
    return catalog


CATALOGS = _load_catalog()


def resolve_language(
    language: str, ui_languages: list[str] | None = None
) -> str:
    if language != "auto":
        return language if language in SUPPORTED_LANGUAGES else "en"
    preferred_languages = (
        ui_languages if ui_languages is not None else QLocale.system().uiLanguages()
    )
    for locale_name in preferred_languages:
        locale_language = locale_name.replace("_", "-").split("-", 1)[0].lower()
        if locale_language in SUPPORTED_LANGUAGES:
            return locale_language
    return "en"


def tr(language: str, key: str, **values: Any) -> str:
    messages: Any = CATALOGS
    for part in key.split("."):
        if not isinstance(messages, dict):
            raise KeyError(f"Unknown translation key: {key}")
        messages = messages[part]
    if not isinstance(messages, dict) or "en" not in messages:
        raise KeyError(f"Unknown translation key: {key}")
    message = messages.get(language, messages["en"])
    return message.format(**values) if values else message


def localized_name(language: str, group: str, name: str) -> str:
    key = name.casefold().replace(" ", "_")
    try:
        return tr(language, f"{group}.{key}")
    except KeyError:
        return name
