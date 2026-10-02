"""Load the repository's shared tool configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_config(root: Path) -> dict[str, Any]:
    config_path = root / "config.yaml"
    if not config_path.is_file():
        raise ValueError(f"Missing project configuration: {config_path}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Project configuration must be a YAML mapping")
    if config.get("schema_version") != 1:
        raise ValueError("Unsupported project configuration schema")
    if not isinstance(config.get("paths"), dict) or not isinstance(
        config.get("recognition"), dict
    ):
        raise ValueError("Project configuration is missing paths or recognition settings")
    return config