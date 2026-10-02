import unittest
from unittest.mock import patch

import numpy as np

from app.nr_challenge_tracker.recognition import RecognitionEngine


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