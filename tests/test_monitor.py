import unittest

from app.nr_challenge_tracker.monitor import ScreenDebouncer


class ScreenDebouncerTests(unittest.TestCase):
    def test_candidate_requires_consistent_confirmations(self) -> None:
        debouncer = ScreenDebouncer(confirmations=3)

        self.assertIsNone(debouncer.observe("preparation"))
        self.assertIsNone(debouncer.observe("preparation"))
        self.assertEqual(debouncer.observe("preparation"), "preparation")
        self.assertIsNone(debouncer.observe("preparation"))

    def test_unknown_screen_resets_candidate(self) -> None:
        debouncer = ScreenDebouncer(confirmations=2)

        self.assertIsNone(debouncer.observe("result"))
        self.assertIsNone(debouncer.observe("unknown"))
        self.assertIsNone(debouncer.observe("result"))
        self.assertEqual(debouncer.observe("result"), "result")

    def test_changed_identity_restarts_screen_confirmation(self) -> None:
        debouncer = ScreenDebouncer(confirmations=2)

        self.assertIsNone(debouncer.observe("preparation", ("executor", "adel")))
        self.assertIsNone(debouncer.observe("preparation", ("executor", "libra")))
        self.assertEqual(
            debouncer.observe("preparation", ("executor", "libra")),
            "preparation",
        )


if __name__ == "__main__":
    unittest.main()