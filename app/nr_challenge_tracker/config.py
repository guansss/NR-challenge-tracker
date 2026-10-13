"""Validated application settings loaded from the project config file."""

from __future__ import annotations

import copy
import ipaddress
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from .challenges import Challenge, ChallengeType
from .models import ANY_NIGHTFARER


NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _ConfigSection(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)


class _SamplingConfig(_ConfigSection):
    idle_ms: int = Field(gt=0)
    preparation_ms: int = Field(gt=0)
    gameplay_ms: int = Field(gt=0)
    result_ms: int = Field(gt=0)


class _RecognitionThresholds(_ConfigSection):
    template_score: float = Field(default=0.50, ge=0, le=1)
    result_template_score: float = Field(default=0.56, ge=0, le=1)
    identity_margin: float = Field(default=0.04, ge=0, le=1)
    variant_score_margin: float = Field(default=0.004, ge=0, le=1)
    progress_margin: float = Field(default=0.015, ge=0, le=1)
    victory_margin: float = Field(default=0.015, ge=0, le=1)


class _RecognitionConfig(_ConfigSection):
    consecutive_confirmations: int = Field(gt=0)
    sampling: _SamplingConfig
    thresholds: _RecognitionThresholds = Field(
        default_factory=_RecognitionThresholds
    )


_RECOGNITION_THRESHOLD_FIELDS = (
    "template_score",
    "result_template_score",
    "identity_margin",
    "variant_score_margin",
    "progress_margin",
    "victory_margin",
)


EDITABLE_CONFIG_PATHS = (
    ("language",),
    ("recognition", "consecutive_confirmations"),
    ("recognition", "sampling", "idle_ms"),
    ("recognition", "sampling", "preparation_ms"),
    ("recognition", "sampling", "gameplay_ms"),
    ("recognition", "sampling", "result_ms"),
    *(("recognition", "thresholds", key) for key in _RECOGNITION_THRESHOLD_FIELDS),
    ("capture", "target_window"),
    ("api", "enabled"),
    ("api", "host"),
    ("api", "port"),
    ("bilibili", "title_template"),
    ("bilibili", "polling_interval_seconds"),
    ("hud", "opacity"),
    ("hud", "font_size"),
    ("hud", "recent_sessions"),
    ("hud", "always_on_top"),
    ("debug", "save_screenshots"),
)


_EDITABLE_CONFIG_PATH_SET = frozenset(EDITABLE_CONFIG_PATHS)


class _CaptureConfig(_ConfigSection):
    target_window: NonEmptyString


class _ApiConfig(_ConfigSection):
    enabled: bool = True
    host: NonEmptyString
    port: int = Field(ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as error:
            raise ValueError("API host must be a loopback IP address") from error
        if not address.is_loopback:
            raise ValueError("API host must be a loopback IP address")
        return value


class _BilibiliConfig(_ConfigSection):
    title_template: NonEmptyString
    polling_interval_seconds: int = Field(gt=0)

    @field_validator("title_template")
    @classmethod
    def validate_title_template(cls, value: str) -> str:
        try:
            value.format(wins=0, total=0, streak=0, goal=0)
        except (IndexError, KeyError, ValueError) as error:
            raise ValueError(f"invalid title template: {error}") from error
        return value


class _HudConfig(_ConfigSection):
    opacity: float = Field(ge=0.1, le=1.0)
    font_size: int = Field(gt=0)
    recent_sessions: int = Field(gt=0)
    always_on_top: bool = True


class _DebugConfig(_ConfigSection):
    save_screenshots: bool = False


class _ProjectConfig(_ConfigSection):
    schema_version: Literal[1]
    language: Literal["auto", "en", "zh"] = "auto"
    paths: dict[str, str]
    recognition: _RecognitionConfig
    capture: _CaptureConfig
    api: _ApiConfig
    bilibili: _BilibiliConfig
    hud: _HudConfig
    debug: _DebugConfig = Field(default_factory=_DebugConfig)

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
    idle_interval_ms: int
    preparation_interval_ms: int
    gameplay_interval_ms: int
    result_interval_ms: int
    consecutive_confirmations: int
    api_enabled: bool
    api_host: str
    api_port: int
    title_template: str
    polling_interval_seconds: int
    hud_opacity: float
    hud_font_size: int
    hud_recent_sessions: int
    hud_always_on_top: bool
    debug_save_screenshots: bool


def load_project_settings(
    root: Path, *, assets_root: Path | None = None
) -> tuple[dict[str, Any], AppSettings]:
    config_root = assets_root or root
    defaults = load_default_config(config_root)
    user_config_path = root / "user-config.yaml"
    overrides: dict[str, Any] = {}
    should_persist_challenges = True
    if user_config_path.exists():
        try:
            overrides = yaml.safe_load(user_config_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise ValueError(f"Could not load user configuration: {error}") from error
        if not isinstance(overrides, dict):
            raise ValueError("Invalid user configuration: root must be a mapping")
        _validate_user_override_paths(overrides)
        if "challenges" not in overrides and "streak" in overrides:
            legacy_streak = overrides.pop("streak")
            overrides["challenges"], overrides["active_challenge_id"] = (
                _legacy_streak_challenge(defaults, legacy_streak, assets_root or root)
            )
            should_persist_challenges = True
        else:
            should_persist_challenges = "challenges" not in overrides
    else:
        legacy_config_path = root / "config.yaml"
        if (
            legacy_config_path.is_file()
            and legacy_config_path.resolve() != (config_root / "config.yaml").resolve()
        ):
            overrides = _migrate_legacy_config(
                root, legacy_config_path, defaults, assets_root or root
            )
        should_persist_challenges = "challenges" not in overrides

    data = merge_config(defaults, overrides)
    data["challenges"], data["active_challenge_id"] = _load_challenges(
        overrides.get("challenges"), overrides.get("active_challenge_id")
    )
    validated, settings = validate_project_config(data, assets_root=assets_root or root)
    if should_persist_challenges:
        save_user_config(root, defaults, validated)
    return validated, settings


def load_default_config(config_root: Path) -> dict[str, Any]:
    default_path = config_root / "config.yaml"
    try:
        defaults = yaml.safe_load(default_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"Could not load application configuration: {error}") from error
    if not isinstance(defaults, dict):
        raise ValueError("Invalid application configuration: root must be a mapping")
    return defaults


def validate_project_config(
    data: dict[str, Any], *, assets_root: Path
) -> tuple[dict[str, Any], AppSettings]:
    try:
        config = _ProjectConfig.model_validate(data)
    except ValidationError as error:
        raise ValueError(f"Invalid application configuration: {error}") from error
    available_nightfarers = _load_available_nightfarers(assets_root, config.paths)
    if data.get("challenges"):
        for challenge in challenges_from_config(data):
            if (
                challenge.type is ChallengeType.WINNING_STREAK
                and challenge.eligible_nightfarer != ANY_NIGHTFARER
                and challenge.eligible_nightfarer not in available_nightfarers
            ):
                raise ValueError(
                    "Invalid application configuration: eligible_nightfarer "
                    f"{challenge.eligible_nightfarer!r} in Challenge {challenge.name!r} "
                    "is not an available Nightfarer key"
                )
    settings = AppSettings(
        language=config.language,
        target_window=config.capture.target_window,
        idle_interval_ms=config.recognition.sampling.idle_ms,
        preparation_interval_ms=config.recognition.sampling.preparation_ms,
        gameplay_interval_ms=config.recognition.sampling.gameplay_ms,
        result_interval_ms=config.recognition.sampling.result_ms,
        consecutive_confirmations=config.recognition.consecutive_confirmations,
        api_enabled=config.api.enabled,
        api_host=config.api.host,
        api_port=config.api.port,
        title_template=config.bilibili.title_template,
        polling_interval_seconds=config.bilibili.polling_interval_seconds,
        hud_opacity=config.hud.opacity,
        hud_font_size=config.hud.font_size,
        hud_recent_sessions=config.hud.recent_sessions,
        hud_always_on_top=config.hud.always_on_top,
        debug_save_screenshots=config.debug.save_screenshots,
    )
    return copy.deepcopy(config.model_dump()), settings


def merge_config(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_config(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def build_user_overrides(
    defaults: dict[str, Any], effective_config: dict[str, Any]
) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for path in EDITABLE_CONFIG_PATHS:
        current_value = _get_config_value(effective_config, path)
        try:
            default_value = _get_config_value(defaults, path)
        except ValueError:
            # Optional fields introduced after an older bundled config should
            # use their validated default rather than creating an override.
            default_value = current_value
        if current_value != default_value:
            _set_config_value(overrides, path, current_value)
    for key in ("challenges", "active_challenge_id"):
        if key in effective_config:
            overrides[key] = copy.deepcopy(effective_config[key])
    return overrides


def save_user_config(
    root: Path, defaults: dict[str, Any], effective_config: dict[str, Any]
) -> dict[str, Any]:
    overrides = build_user_overrides(defaults, effective_config)
    path = root / "user-config.yaml"
    temporary_path: Path | None = None
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=root,
            prefix=".user-config-",
            suffix=".yaml",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            yaml.safe_dump(
                overrides,
                temporary_file,
                sort_keys=False,
                allow_unicode=True,
            )
        os.replace(temporary_path, path)
    except OSError as error:
        cleanup_error: OSError | None = None
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as failure:
                cleanup_error = failure
        message = f"Could not save user configuration: {error}"
        if cleanup_error is not None:
            message += f"; temporary file cleanup failed: {cleanup_error}"
        raise ValueError(message) from error
    return overrides


def _migrate_legacy_config(
    root: Path,
    legacy_path: Path,
    defaults: dict[str, Any],
    assets_root: Path,
) -> dict[str, Any]:
    try:
        legacy_config = yaml.safe_load(legacy_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"Could not load legacy configuration: {error}") from error
    if not isinstance(legacy_config, dict):
        raise ValueError("Invalid legacy configuration: root must be a mapping")
    if legacy_config.get("schema_version") != defaults.get("schema_version"):
        raise ValueError("Invalid legacy configuration: unsupported schema version")

    migrated = copy.deepcopy(defaults)
    for path in EDITABLE_CONFIG_PATHS:
        try:
            value = _get_config_value(legacy_config, path)
        except ValueError:
            continue
        _set_config_value(migrated, path, value)
    if "streak" in legacy_config:
        migrated["challenges"], migrated["active_challenge_id"] = (
            _legacy_streak_challenge(
                defaults, legacy_config["streak"], assets_root
            )
        )
    validated, _settings = validate_project_config(migrated, assets_root=assets_root)
    return save_user_config(root, defaults, validated)


def _validate_user_override_paths(overrides: dict[str, Any]) -> None:
    def visit(value: Any, prefix: tuple[str, ...]) -> None:
        for key, child in value.items():
            if not prefix and key in {"challenges", "active_challenge_id"}:
                continue
            if not prefix and key == "streak":
                # The loader migrates this retired section into a Challenge.
                continue
            if not isinstance(key, str):
                raise ValueError("Invalid user configuration: keys must be strings")
            path = (*prefix, key)
            if path in _EDITABLE_CONFIG_PATH_SET:
                if isinstance(child, dict):
                    raise ValueError(
                        "Invalid user configuration: expected a value for "
                        + ".".join(path)
                    )
            elif isinstance(child, dict) and any(
                editable_path[: len(path)] == path
                for editable_path in EDITABLE_CONFIG_PATHS
            ):
                visit(child, path)
            else:
                raise ValueError(
                    "Invalid user configuration: field is not editable: "
                    + ".".join(path)
                )

    visit(overrides, ())


def _load_challenges(
    raw_challenges: Any, active_challenge_id: Any
) -> tuple[list[dict[str, Any]], str]:
    if raw_challenges is None:
        challenge = Challenge("normal", "All Sessions", ChallengeType.NORMAL)
        return [_challenge_to_config(challenge)], challenge.id
    if not isinstance(raw_challenges, list) or not raw_challenges:
        raise ValueError("Invalid user configuration: challenges must be a non-empty list")
    challenges = tuple(_challenge_from_config(item) for item in raw_challenges)
    if len({challenge.id for challenge in challenges}) != len(challenges):
        raise ValueError("Invalid user configuration: Challenge ids must be unique")
    if not isinstance(active_challenge_id, str) or active_challenge_id not in {
        challenge.id for challenge in challenges
    }:
        raise ValueError("Invalid user configuration: active_challenge_id must select a Challenge")
    return [_challenge_to_config(challenge) for challenge in challenges], active_challenge_id


def _legacy_streak_challenge(
    defaults: dict[str, Any], raw_streak: Any, assets_root: Path
) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(raw_streak, dict):
        raise ValueError("Invalid legacy configuration: streak must be a mapping")
    legacy_nightfarer = raw_streak.get("eligible_nightfarer", "executor")
    if not isinstance(legacy_nightfarer, str):
        raise ValueError(
            "Invalid legacy configuration: streak eligible_nightfarer must be a string"
        )

    available_nightfarers = _load_available_nightfarers(
        assets_root, defaults["paths"]
    )
    nightfarer_by_casefold = {
        nightfarer.casefold(): nightfarer for nightfarer in available_nightfarers
    }
    eligible_nightfarer = (
        ANY_NIGHTFARER
        if legacy_nightfarer.strip().casefold() == ANY_NIGHTFARER
        else nightfarer_by_casefold.get(legacy_nightfarer.strip().casefold())
    )
    if eligible_nightfarer is None:
        raise ValueError(
            "Invalid legacy configuration: streak eligible_nightfarer "
            f"{legacy_nightfarer!r} is not an available Nightfarer key"
        )

    challenge = Challenge(
        id="legacy-streak",
        name="Legacy streak",
        type=ChallengeType.WINNING_STREAK,
        eligible_nightfarer=eligible_nightfarer,
        target=raw_streak.get("target", 100),
    )
    return [_challenge_to_config(challenge)], challenge.id


def _challenge_from_config(raw: Any) -> Challenge:
    if not isinstance(raw, dict):
        raise ValueError("Invalid user configuration: each Challenge must be a mapping")
    try:
        excluded = raw.get("excluded_session_ids", [])
        if not isinstance(excluded, list):
            raise ValueError("excluded_session_ids must be a list")
        return Challenge(
            id=raw["id"],
            name=raw["name"],
            type=ChallengeType(raw["type"]),
            excluded_session_ids=frozenset(excluded),
            eligible_nightfarer=raw.get("eligible_nightfarer"),
            target=raw.get("target"),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid user configuration: Challenge: {error}") from error


def challenges_from_config(config: dict[str, Any]) -> tuple[Challenge, ...]:
    return tuple(_challenge_from_config(item) for item in config["challenges"])


def _challenge_to_config(challenge: Challenge) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": challenge.id,
        "name": challenge.name,
        "type": challenge.type.value,
        "excluded_session_ids": sorted(challenge.excluded_session_ids),
    }
    if challenge.type is ChallengeType.WINNING_STREAK:
        result["eligible_nightfarer"] = challenge.eligible_nightfarer
        result["target"] = challenge.target
    return result


def _get_config_value(config: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = config
    for part in path:
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"Missing configuration field: {'.'.join(path)}")
        value = value[part]
    return value


def _set_config_value(
    config: dict[str, Any], path: tuple[str, ...], value: Any
) -> None:
    section = config
    for part in path[:-1]:
        section = section.setdefault(part, {})
    section[path[-1]] = copy.deepcopy(value)


def _load_available_nightfarers(root: Path, paths: dict[str, str]) -> set[str]:
    manifest_path = paths.get("template_manifest")
    if not manifest_path:
        raise ValueError("Invalid application configuration: missing template_manifest path")
    try:
        manifest = yaml.safe_load((root / manifest_path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"Could not load Nightfarers from {manifest_path}: {error}") from error
    if not isinstance(manifest, dict) or not isinstance(
        manifest.get("nightfarers"), list
    ):
        raise ValueError(f"Template manifest has no available Nightfarers: {manifest_path}")

    nightfarer_ids = [
        nightfarer.get("id")
        for nightfarer in manifest["nightfarers"]
        if isinstance(nightfarer, dict)
    ]
    if len(nightfarer_ids) != len(manifest["nightfarers"]) or any(
        not isinstance(nightfarer_id, str) for nightfarer_id in nightfarer_ids
    ):
        raise ValueError(f"Template manifest has invalid Nightfarer keys: {manifest_path}")
    return set(nightfarer_ids)