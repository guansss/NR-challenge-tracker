import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.nr_challenge_tracker.recognition import RecognitionEngine
from tools.project_config import load_config


class RecognitionScreenTests(unittest.TestCase):
    def test_ambiguous_progress_does_not_end_active_session_as_result(self) -> None:
        engine = object.__new__(RecognitionEngine)
        progress = {"day": "unknown", "day_confidence": 0.95}
        preparation = {"screen": "unknown"}

        with (
            patch.object(RecognitionEngine, "_result_progress", return_value=progress),
            patch.object(RecognitionEngine, "_result_nightlord") as result_nightlord,
            patch.object(RecognitionEngine, "_preparation", return_value=preparation),
        ):
            recognized = engine.recognize(object())

        self.assertEqual(recognized, preparation)
        result_nightlord.assert_not_called()


class RecognitionNightlordTests(unittest.TestCase):
    def test_result_identity_below_result_threshold_is_rejected(self) -> None:
        engine = object.__new__(RecognitionEngine)
        engine.result_search_roi = (0.0, 0.0, 1.0, 1.0)
        engine.result_templates = {"straghess": {"normal": np.zeros((2, 2, 3))}}
        engine.min_result_template_score = 0.56
        engine.min_identity_margin = 0.04
        engine.min_variant_score_margin = 0.004
        image = np.zeros((10, 10, 3))

        with (
            patch.object(engine, "_normalized_crop", return_value=image),
            patch.object(engine, "_template_for_frame", return_value=image),
            patch.object(RecognitionEngine, "_best_match", return_value=(0.554, image)),
        ):
            result = engine._result_nightlord(image)

        self.assertIsNone(result["nightlord"])
        self.assertEqual(result["variant"], "unknown")


class RecognitionCounterexampleTests(unittest.TestCase):
    def test_gameplay_screenshot_is_not_mislabeled_as_straghess_result(self) -> None:
        root = Path(__file__).resolve().parents[1]
        image_path = (
            root
            / "assets"
            / "dataset"
            / "counterexamples"
            / "0003_result_straghess_normal_unknown.jpg"
        )
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            self.fail(f"Could not load counterexample image: {image_path}")

        engine = RecognitionEngine(root, load_config(root))
        identity = engine._result_nightlord(image)
        recognized = engine.recognize(image)

        self.assertIsNone(identity["nightlord"])
        self.assertEqual(recognized["screen"], "unknown")
        self.assertIsNone(recognized.get("nightlord"))


class RecognitionDebugImageTests(unittest.TestCase):
    def test_render_debug_image_outlines_recognized_preparation_rois(self) -> None:
        engine = object.__new__(RecognitionEngine)
        engine.preparation_roi = (0.1, 0.1, 0.2, 0.2)
        engine.nightfarer_templates = [("executor", None)]
        engine.grid_x = (10, 20, 30, 40, 50)
        engine.grid_y = (10, 20)
        engine.reference_width = 100
        engine.reference_height = 50
        engine.selection_marker_box = (2, 3, 44, 44)
        marker = np.zeros((10, 12, 3), dtype=np.uint8)
        engine.templates = {"marker:selected": marker}
        source = np.zeros((50, 100, 3), dtype=np.uint8)

        with patch.object(engine, "_template_for_frame", return_value=marker):
            annotated = engine.render_debug_image(
                source,
                {"screen": "preparation", "nightfarer": "executor"},
            )

        self.assertFalse(np.array_equal(source, annotated))
        self.assertEqual(tuple(annotated[5, 10]), (70, 220, 70))
        self.assertEqual(tuple(annotated[13, 12]), (220, 180, 30))
        self.assertTrue(np.all(source == 0))

    def test_render_debug_image_outlines_result_rois(self) -> None:
        engine = object.__new__(RecognitionEngine)
        engine.progress_roi = (0.2, 0.2, 0.1, 0.1)
        engine.result_search_roi = (0.5, 0.2, 0.2, 0.3)
        source = np.zeros((50, 100, 3), dtype=np.uint8)

        annotated = engine.render_debug_image(source, {"screen": "result"})

        self.assertEqual(tuple(annotated[10, 20]), (0, 210, 255))
        self.assertEqual(tuple(annotated[10, 50]), (220, 50, 220))


if __name__ == "__main__":
    unittest.main()