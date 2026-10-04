import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.nr_challenge_tracker.runtime_paths import application_root, resource_root


class RuntimePathTests(unittest.TestCase):
    def test_source_checkout_uses_repository_root_for_resources_and_data(self) -> None:
        root = Path(__file__).resolve().parents[1]

        self.assertEqual(application_root(), root)
        self.assertEqual(resource_root(), root)

    def test_frozen_app_uses_executable_directory_for_writable_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "Nightreign Challenge Tracker.exe"
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "executable", str(executable)),
            ):
                self.assertEqual(application_root(), Path(directory))

    def test_frozen_app_uses_bundle_directory_for_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable_directory = Path(directory) / "app"
            bundle_directory = Path(directory) / "bundle"
            executable_directory.mkdir()
            bundle_directory.mkdir()
            executable = executable_directory / "Nightreign Challenge Tracker.exe"
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "executable", str(executable)),
                patch.object(sys, "_MEIPASS", str(bundle_directory), create=True),
            ):
                self.assertEqual(application_root(), executable_directory)
                self.assertEqual(resource_root(), bundle_directory)


if __name__ == "__main__":
    unittest.main()
