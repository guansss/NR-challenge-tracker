from http.client import HTTPConnection
import json
import threading
import unittest

from app.nr_challenge_tracker.api import StreakApiServer


class StreakApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {
            "schema_version": 1,
            "current_streak": 3,
            "target": 100,
            "desired_title": "Challenge (3/100)",
            "revision": 4,
        }
        self.reports: list[tuple[str, int, str]] = []

        def report(status: str, revision: int, message: str) -> bool:
            self.reports.append((status, revision, message))
            return revision == self.state["revision"]

        self.server = StreakApiServer(
            "127.0.0.1", 0, lambda: self.state, report
        )
        self.server.start()

    def tearDown(self) -> None:
        self.server.close()

    def request(self, method: str, path: str, payload: dict | None = None):
        connection = HTTPConnection("127.0.0.1", self.server.port, timeout=2)
        body = json.dumps(payload) if payload is not None else None
        headers = {"Content-Type": "application/json"} if body else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def test_streak_endpoint_returns_current_state(self) -> None:
        status, payload = self.request("GET", "/api/streak")

        self.assertEqual(status, 200)
        self.assertEqual(payload["desired_title"], "Challenge (3/100)")

    def test_only_valid_current_revision_status_is_accepted(self) -> None:
        status, payload = self.request(
            "POST",
            "/api/sync-status",
            {"status": "Synced", "revision": 4, "message": ""},
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["accepted"])
        self.assertEqual(self.reports, [("Synced", 4, "")])

        stale_status, stale_payload = self.request(
            "POST",
            "/api/sync-status",
            {"status": "Synced", "revision": 3},
        )
        self.assertEqual(stale_status, 409)
        self.assertFalse(stale_payload["accepted"])

    def test_status_endpoint_rejects_arbitrary_title_mutation(self) -> None:
        status, _payload = self.request(
            "POST", "/api/title", {"title": "arbitrary"}
        )

        self.assertEqual(status, 404)

    def test_status_endpoint_rejects_non_string_state(self) -> None:
        status, payload = self.request(
            "POST",
            "/api/sync-status",
            {"status": ["Synced"], "revision": 4},
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_status")

    def test_non_loopback_bind_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            StreakApiServer("0.0.0.0", 5678, lambda: {}, lambda *_args: True)

    def test_state_error_returns_structured_service_unavailable(self) -> None:
        server = StreakApiServer(
            "127.0.0.1",
            0,
            lambda: (_ for _ in ()).throw(ValueError("state invalid")),
            lambda *_args: True,
        )
        server.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.port, timeout=2)
            connection.request("GET", "/api/streak")
            response = connection.getresponse()
            payload = json.loads(response.read())
            connection.close()
            self.assertEqual(response.status, 503)
            self.assertEqual(payload, {"error": "state_unavailable"})
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()