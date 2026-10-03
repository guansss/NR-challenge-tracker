"""Validated application settings loaded from the project config file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)
import yaml


NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _ConfigSection(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)


class _SamplingConfig(_ConfigSection):
    idle_ms: int = Field(gt=0)
    preparation_ms: int = Field(gt=0)
    gameplay_ms: int = Field(gt=0)
    result_ms: int = Field(gt=0)


class _RecognitionConfig(_ConfigSection):
    consecutive_confirmations: int = Field(gt=0)
    sampling: _SamplingConfig


class _CaptureConfig(_ConfigSection):
    target_window: NonEmptyString


class _StreakConfig(_ConfigSection):
    target: int = Field(gt=0)
    eligible_nightfarer: Literal["Executor"]
    failure_rule: Literal["all_nonvictories"]
    cap_at_target: bool


class _ApiConfig(_ConfigSection):
    host: NonEmptyString
    port: int = Field(ge=1, le=65535)


class _BilibiliConfig(_ConfigSection):
    enabled: bool
    room_id: int | None = None
    title_template: NonEmptyString
    title_max_characters: int = Field(gt=0)
    polling_interval_seconds: int = Field(gt=0)


class _HudConfig(_ConfigSection):
    enabled: bool
    opacity: float = Field(ge=0.1, le=1.0)
    font_size: int = Field(gt=0)
    width: int = Field(gt=0)
    recent_sessions: int = Field(gt=0)
    show_recent_sessions: bool


class _ProjectConfig(_ConfigSection):
    schema_version: Literal[1]
    language: Literal["auto", "en", "zh"] = "auto"
    paths: dict[str, str]
    recognition: _RecognitionConfig
    capture: _CaptureConfig
    streak: _StreakConfig
    api: _ApiConfig
    bilibili: _BilibiliConfig
    hud: _HudConfig

    @field_validator("language", mode="before")
    @classmethod
    def validate_language(cls, value: Any) -> Any:
        if not isinstance(value, str) or value not in {"auto", "en", "zh"}:
            raise ValueError("language must be one of: auto, en, zh")
        return value


@dataclass(frozen=True, slots=True)
class AppSettings:
    language: str
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
    hud_recent_sessions: int


def load_project_settings(root: Path) -> tuple[dict[str, Any], AppSettings]:
    path = root / "config.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"Could not load application configuration: {error}") from error
    try:
        config = _ProjectConfig.model_validate(data)
    except ValidationError as error:
        raise ValueError(f"Invalid application configuration: {error}") from error

    settings = AppSettings(
        language=config.language,
        target_window=config.capture.target_window,
        target=config.streak.target,
        idle_interval_ms=config.recognition.sampling.idle_ms,
        preparation_interval_ms=config.recognition.sampling.preparation_ms,
        gameplay_interval_ms=config.recognition.sampling.gameplay_ms,
        result_interval_ms=config.recognition.sampling.result_ms,
        consecutive_confirmations=config.recognition.consecutive_confirmations,
        api_host=config.api.host,
        api_port=config.api.port,
        bilibili_enabled=config.bilibili.enabled,
        room_id=config.bilibili.room_id,
        title_template=config.bilibili.title_template,
        title_max_characters=config.bilibili.title_max_characters,
        polling_interval_seconds=config.bilibili.polling_interval_seconds,
        hud_opacity=config.hud.opacity,
        hud_font_size=config.hud.font_size,
        hud_width=config.hud.width,
        hud_recent_sessions=config.hud.recent_sessions,
    )
    return data, settings