from __future__ import annotations

import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

from tools.build_release import (
    ROOT,
    create_archive,
    read_version,
    stage_userscript,
    validate_release_tag,
    write_pyinstaller_spec,
)


class BuildReleaseTests(unittest.TestCase):
    def test_reads_version_from_project_metadata(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(read_version(), project["project"]["version"])

    def test_rejects_tag_that_does_not_match_project_version(self) -> None:
        version = read_version()
        with self.assertRaisesRegex(ValueError, f"expected v{version}"):
            validate_release_tag(version, f"v{version}-mismatch")

    def test_generates_one_file_pyinstaller_spec(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            spec_path = write_pyinstaller_spec(Path(temporary_directory) / "main.spec")

            spec = spec_path.read_text(encoding="utf-8")
            self.assertIn(f"ROOT = Path({str(ROOT)!r})", spec)
            self.assertIn("name='Nightreign Challenge Tracker'", spec)
            self.assertIn("pyz,\n    a.scripts,\n    a.binaries,\n    a.datas,", spec)
            self.assertNotIn("COLLECT(", spec)
            self.assertIn("assets/templates", spec)

    def test_archive_contains_executable_and_editable_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            dist_dir = Path(temporary_directory)
            (dist_dir / "Nightreign Challenge Tracker.exe").write_bytes(b"exe")
            (dist_dir / "config.yaml").write_text("schema_version: 1\n", encoding="utf-8")

            version = read_version()
            archive_path = create_archive(dist_dir, version)

            self.assertEqual(
                archive_path.name,
                f"Nightreign-Challenge-Tracker-v{version}-windows.zip",
            )
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(
                    archive.namelist(),
                    ["Nightreign Challenge Tracker.exe", "config.yaml"],
                )

    def test_stages_versioned_bilibili_userscript(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            dist_dir = Path(temporary_directory)
            version = read_version()

            userscript_path = stage_userscript(dist_dir, version)

            self.assertEqual(userscript_path.name, f"bilibili-{version}.user.js")
            self.assertEqual(
                userscript_path.read_bytes(),
                (ROOT / "app" / "integrations" / "bilibili.user.js").read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
