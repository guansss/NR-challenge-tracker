"""Build the portable, versioned Windows release archive."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_FILE = ROOT / "pyproject.toml"
DIST_DIR = ROOT / "dist"
EXECUTABLE_NAME = "Nightreign Challenge Tracker.exe"
SPEC_CONTENT = """# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

ROOT = Path(__PROJECT_ROOT__)

a = Analysis(
    [str(ROOT / 'app' / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'config.yaml'), '.'),
        (str(ROOT / 'assets' / 'templates'), 'assets/templates'),
        (str(ROOT / 'assets' / 'translations.yaml'), 'assets'),
        (str(ROOT / 'assets' / 'sound'), 'assets/sound'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Nightreign Challenge Tracker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
"""


def read_version(project_file: Path = PROJECT_FILE) -> str:
    metadata = tomllib.loads(project_file.read_text(encoding="utf-8"))
    project = metadata.get("project")
    version = project.get("version") if isinstance(project, dict) else None
    if not isinstance(version, str) or not re.fullmatch(
        r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version
    ):
        raise ValueError("pyproject.toml must define a semantic project version")
    return version


def validate_release_tag(version: str, tag: str | None) -> None:
    if tag is not None and tag != f"v{version}":
        raise ValueError(
            f"Release tag {tag!r} does not match pyproject.toml version; "
            f"expected v{version}"
        )


def write_pyinstaller_spec(spec_path: Path) -> Path:
    spec_path.write_text(
        SPEC_CONTENT.replace("__PROJECT_ROOT__", repr(str(ROOT))),
        encoding="utf-8",
    )
    return spec_path


def build_executable() -> None:
    DIST_DIR.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nr-challenge-tracker-") as temporary_directory:
        spec_path = write_pyinstaller_spec(Path(temporary_directory) / "main.spec")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                str(DIST_DIR),
                "--workpath",
                str(ROOT / "build"),
                str(spec_path),
            ],
            cwd=ROOT,
            check=True,
        )


def create_archive(dist_dir: Path, version: str) -> Path:
    executable = dist_dir / EXECUTABLE_NAME
    config = dist_dir / "config.yaml"
    if not executable.is_file():
        raise FileNotFoundError(f"PyInstaller output not found: {executable}")
    if not config.is_file():
        raise FileNotFoundError(f"Portable config not found: {config}")

    archive_path = dist_dir / f"Nightreign-Challenge-Tracker-v{version}-windows.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(executable, executable.name)
        archive.write(config, config.name)
    return archive_path


def stage_userscript(dist_dir: Path, version: str) -> Path:
    source = ROOT / "app" / "integrations" / "bilibili.user.js"
    if not source.is_file():
        raise FileNotFoundError(f"Bilibili userscript not found: {source}")

    userscript_path = dist_dir / f"bilibili-{version}.user.js"
    shutil.copy2(source, userscript_path)
    return userscript_path


def main() -> int:
    version = read_version()
    validate_release_tag(version, os.environ.get("GITHUB_REF_NAME"))
    build_executable()
    shutil.copy2(ROOT / "config.yaml", DIST_DIR / "config.yaml")
    archive_path = create_archive(DIST_DIR, version)
    userscript_path = stage_userscript(DIST_DIR, version)
    print(f"Created {archive_path}")
    print(f"Created {userscript_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
