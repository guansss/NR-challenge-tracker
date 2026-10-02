import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()