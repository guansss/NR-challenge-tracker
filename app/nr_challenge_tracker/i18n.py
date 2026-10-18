"""Language selection and UI messages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import QLocale

from .runtime_paths import application_root, resource_root

SUPPORTED_LANGUAGES = frozenset({"en", "zh"})

_TRANSLATIONS_PATH = (
    resource_root() / "assets" / "translations.yaml"
)
_USER_TRANSLATIONS_PATH = application_root() / "user-translations.yaml"


def _load_catalog() -> dict[str, Any]:
    try:
        catalog = yaml.safe_load(_TRANSLATIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RuntimeError(f"Could not load translations: {error}") from error
    if not isinstance(catalog, dict):
        raise RuntimeError("Translation catalog must be a YAML mapping")

    try:
        user_catalog = yaml.safe_load(
            _USER_TRANSLATIONS_PATH.read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return catalog
    except (OSError, yaml.YAMLError) as error:
        raise RuntimeError(f"Could not load user translations: {error}") from error
    if not isinstance(user_catalog, dict):
        raise RuntimeError("User translation catalog must be a YAML mapping")
    return _merge_catalogs(catalog, user_catalog)


def _merge_catalogs(
    catalog: dict[str, Any], user_catalog: dict[str, Any]
) -> dict[str, Any]:
    merged = catalog.copy()
    for key, value in user_catalog.items():
        current_value = merged.get(key)
        if isinstance(current_value, dict) and isinstance(value, dict):
            merged[key] = _merge_catalogs(current_value, value)
        else:
            merged[key] = value
    return merged


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
