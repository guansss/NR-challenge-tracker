"""Resolve bundled resources and writable application files."""

from __future__ import annotations

from pathlib import Path
import sys


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        bundle_directory = getattr(sys, "_MEIPASS", None)
        if bundle_directory is not None:
            return Path(bundle_directory).resolve()
    return application_root()
