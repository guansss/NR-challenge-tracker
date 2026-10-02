"""Validated application settings loaded from the project config file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class AppSettings:
    target_window: str
    target: int
    idle_interval_ms: int
    preparation_interval_ms: int
    gameplay_interval_ms: int
    result_interval_ms: int
    consecutive_confirmations: int
    api_host: str
    api_port: int
    bilibili_enabled: bool
    room_id: int | None
    title_template: str
    title_max_characters: int
    polling_interval_seconds: int
    hud_opacity: float
    hud_font_size: int
    hud_width: int


def load_project_settings(root: Path) -> tuple[dict[str, Any], AppSettings]:
    path = root / "config.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"Could not load application configuration: {error}") from error
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported or invalid application configuration")

    try:
        capture = data["capture"]
        recognition = data["recognition"]
        sampling = recognition["sampling"]
        streak = data["streak"]
        api = data["api"]
        bilibili = data["bilibili"]
        hud = data["hud"]
        target = _positive_int(streak["target"], "streak.target")
        room_id = bilibili.get("room_id")
        if room_id is not None:
            room_id = _positive_int(room_id, "bilibili.room_id")
        settings = AppSettings(
            target_window=_nonempty_string(capture["target_window"], "capture.target_window"),
            target=target,
            idle_interval_ms=_positive_int(sampling["idle_ms"], "sampling.idle_ms"),
            preparation_interval_ms=_positive_int(
                sampling["preparation_ms"], "sampling.preparation_ms"
            ),
            gameplay_interval_ms=_positive_int(
                sampling["gameplay_ms"], "sampling.gameplay_ms"
            ),
            result_interval_ms=_positive_int(
                sampling["result_ms"], "sampling.result_ms"
            ),
            consecutive_confirmations=_positive_int(
                recognition["consecutive_confirmations"],
                "recognition.consecutive_confirmations",
            ),
            api_host=_nonempty_string(api["host"], "api.host"),
            api_port=_bounded_int(api["port"], 1, 65535, "api.port"),
            bilibili_enabled=_boolean(bilibili["enabled"], "bilibili.enabled"),
            room_id=room_id,
            title_template=_nonempty_string(
                bilibili["title_template"], "bilibili.title_template"
            ),
            title_max_characters=_positive_int(
                bilibili["title_max_characters"], "bilibili.title_max_characters"
            ),
            polling_interval_seconds=_positive_int(
                bilibili["polling_interval_seconds"],
                "bilibili.polling_interval_seconds",
            ),
            hud_opacity=_bounded_number(hud["opacity"], 0.1, 1.0, "hud.opacity"),
            hud_font_size=_positive_int(hud["font_size"], "hud.font_size"),
            hud_width=_positive_int(hud["width"], "hud.width"),
        )
    except (KeyError, TypeError) as error:
        raise ValueError(f"Missing or invalid application setting: {error}") from error

    if streak.get("eligible_nightfarer") != "Executor":
        raise ValueError("Only Executor is supported as the eligible Nightfarer")
    if streak.get("failure_rule") != "all_nonvictories":
        raise ValueError("Unsupported streak failure rule")
    if not isinstance(data.get("paths"), dict) or not isinstance(recognition, dict):
        raise ValueError("Configuration is missing paths or recognition settings")
    return data, settings


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _bounded_int(value: Any, minimum: int, maximum: int, name: str) -> int:
    number = _positive_int(value, name)
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def _nonempty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _bounded_number(value: Any, minimum: float, maximum: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number