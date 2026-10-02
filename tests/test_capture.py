import threading
import unittest
from unittest.mock import patch

from app.nr_challenge_tracker.capture import WindowsWindowCapture


class WindowsWindowCaptureTests(unittest.TestCase):
    def test_stop_does_not_block_on_native_wait(self) -> None:
        wait_finished = threading.Event()

        class Control:
            stopped = False

            def stop(self) -> None:
                self.stopped = True

            def wait(self) -> None:
                wait_finished.wait()

        capture = WindowsWindowCapture(1, lambda _frame: None, lambda: None, lambda _error: None, lambda: True)
        control = Control()
        capture._control = control
        stop_thread = threading.Thread(target=capture.stop, daemon=True)

        with patch(
            "app.nr_challenge_tracker.capture._CAPTURE_STOP_TIMEOUT_SECONDS", 0.01
        ):
            stop_thread.start()
            stop_thread.join(timeout=0.5)

        stopped_without_hanging = not stop_thread.is_alive()
        wait_finished.set()
        self.assertTrue(stopped_without_hanging)
        self.assertTrue(control.stopped)
        self.assertIsNone(capture._control)


if __name__ == "__main__":
    unittest.main()