import io
import json
import unittest
from typing import Any

from app.nr_challenge_tracker.api import TrackerApiServer


class _MemorySocket:
    def __init__(self, request: bytes) -> None:
        self._reader = io.BytesIO(request)
        self.response = bytearray()

    def makefile(self, mode: str, _buffering: int | None = None) -> io.BytesIO:
        if mode != "rb":
            raise ValueError(f"Unsupported socket mode: {mode}")
        return self._reader

    def sendall(self, data: bytes) -> None:
        self.response.extend(data)


class TrackerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {
            "schema_version": 2,
            "wins": 0,
            "total": 0,
            "streak": 3,
            "goal": 100,
            "desired_title": "Challenge (W:0/0 S:3/100)",
            "revision": 4,
            "polling_interval_seconds": 5,
            "challenge_type": "winning_streak",
        }
        self.state_unavailable = False
        self.reports: list[tuple[str, int, str]] = []

        def get_state() -> dict[str, Any]:
            if self.state_unavailable:
                raise ValueError("state invalid")
            return self.state

        def report(status: str, revision: int, message: str) -> bool:
            self.reports.append((status, revision, message))
            return revision == self.state["revision"]

        self.server = TrackerApiServer(
            "127.0.0.1", 0, get_state, report
        )

    def tearDown(self) -> None:
        self.server.close()

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
    ) -> tuple[int, dict[str, Any]]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = []
        if body is not None:
            headers.extend(
                (
                    "Content-Type: application/json",
                    f"Content-Length: {len(body)}",
                )
            )
        request = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n"
        request += "".join(f"{header}\r\n" for header in headers) + "\r\n"
        request_bytes = request.encode("ascii") + (body or b"")

        memory_socket = _MemorySocket(request_bytes)
        handler = self.server._server.RequestHandlerClass
        handler(memory_socket, ("127.0.0.1", 12345), self.server._server)

        response_headers, response_body = bytes(memory_socket.response).split(
            b"\r\n\r\n", 1
        )
        status = int(response_headers.split(b"\r\n", 1)[0].split()[1])
        return status, json.loads(response_body)

    def test_state_endpoint_returns_current_state(self) -> None:
        status, payload = self.request("GET", "/api/state")

        self.assertEqual(status, 200)
        self.assertEqual(payload["desired_title"], "Challenge (W:0/0 S:3/100)")
        self.assertEqual(
            {key: payload[key] for key in ("wins", "total", "streak", "goal")},
            {"wins": 0, "total": 0, "streak": 3, "goal": 100},
        )

    def test_old_streak_endpoint_is_not_available(self) -> None:
        status, payload = self.request("GET", "/api/streak")

        self.assertEqual(status, 404)
        self.assertEqual(payload, {"error": "not_found"})

    def test_only_valid_current_revision_status_is_accepted(self) -> None:
        status, payload = self.request(
            "POST",
            "/api/sync-status",
            {"status": "sync.synced", "revision": 4, "message": ""},
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["accepted"])
        self.assertEqual(self.reports, [("sync.synced", 4, "")])

        stale_status, stale_payload = self.request(
            "POST",
            "/api/sync-status",
            {"status": "sync.synced", "revision": 3},
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
            TrackerApiServer("0.0.0.0", 5678, lambda: {}, lambda *_args: True)

    def test_state_error_returns_structured_service_unavailable(self) -> None:
        self.state_unavailable = True
        status, payload = self.request("GET", "/api/state")

        self.assertEqual(status, 503)
        self.assertEqual(payload, {"error": "state_unavailable"})


if __name__ == "__main__":
    unittest.main()