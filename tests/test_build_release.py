from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.build_release import (
    ROOT,
    create_archive,
    read_version,
    validate_release_tag,
    write_pyinstaller_spec,
)


class BuildReleaseTests(unittest.TestCase):
    def test_reads_version_from_project_metadata(self) -> None:
        self.assertEqual(read_version(), "0.1.0")

    def test_rejects_tag_that_does_not_match_project_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected v0.1.0"):
            validate_release_tag("0.1.0", "v0.2.0")

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

            archive_path = create_archive(dist_dir, "0.1.0")

            self.assertEqual(
                archive_path.name,
                "Nightreign-Challenge-Tracker-v0.1.0-windows.zip",
            )
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(
                    archive.namelist(),
                    ["Nightreign Challenge Tracker.exe", "config.yaml"],
                )


if __name__ == "__main__":
    unittest.main()
