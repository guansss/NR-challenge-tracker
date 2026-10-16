import io
import json
from pathlib import Path
import tempfile
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
        self.connection_notifications = 0

        def get_state() -> dict[str, Any]:
            if self.state_unavailable:
                raise ValueError("state invalid")
            return self.state

        def report(status: str, revision: int, message: str) -> bool:
            self.reports.append((status, revision, message))
            return revision == self.state["revision"]

        def notify_connected() -> None:
            self.connection_notifications += 1

        self.userscript_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.userscript_directory.cleanup)
        self.userscript_path = (
            Path(self.userscript_directory.name) / "bilibili.user.js"
        )
        self.server = TrackerApiServer(
            "127.0.0.1",
            0,
            get_state,
            report,
            self.userscript_path,
            notify_connected,
        )
        self.userscript_path.write_text(
            "// ==UserScript==\nconst API_BASE = \"__LOCAL_API_BASE__\";\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.server.close()

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
    ) -> tuple[int, dict[str, Any]]:
        status, _headers, response_body = self.request_raw(method, path, payload)
        return status, json.loads(response_body)

    def request_raw(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
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
        headers = {
            key.decode("ascii").lower(): value.decode("ascii").strip()
            for line in response_headers.split(b"\r\n")[1:]
            if b":" in line
            for key, value in [line.split(b":", 1)]
        }
        return status, headers, response_body

    def test_state_endpoint_returns_current_state(self) -> None:
        status, payload = self.request("GET", "/api/state")

        self.assertEqual(status, 200)
        self.assertEqual(payload["desired_title"], "Challenge (W:0/0 S:3/100)")
        self.assertEqual(
            {key: payload[key] for key in ("wins", "total", "streak", "goal")},
            {"wins": 0, "total": 0, "streak": 3, "goal": 100},
        )
        self.assertEqual(self.connection_notifications, 1)

    def test_state_poll_notifies_only_once_after_success(self) -> None:
        self.state_unavailable = True
        status, _payload = self.request("GET", "/api/state")
        self.assertEqual(status, 503)
        self.assertEqual(self.connection_notifications, 0)

        self.state_unavailable = False
        self.request("GET", "/api/state")
        self.request("GET", "/api/state")
        self.assertEqual(self.connection_notifications, 1)

    def test_userscript_endpoint_serves_installable_script_with_bound_api_url(self) -> None:
        status, headers, content = self.request_raw("GET", "/bilibili.user.js")

        self.assertEqual(status, 200)
        self.assertEqual(
            headers["content-type"], "application/javascript; charset=utf-8"
        )
        self.assertIn(b"// ==UserScript==", content)
        self.assertIn(
            f'const API_BASE = "http://127.0.0.1:{self.server.port}";'.encode(),
            content,
        )
        self.assertNotIn(b"__LOCAL_API_BASE__", content)
        self.assertEqual(
            self.server.userscript_url,
            f"http://127.0.0.1:{self.server.port}/bilibili.user.js",
        )
        self.userscript_path.write_text("changed after first read", encoding="utf-8")
        _status, _headers, cached_content = self.request_raw(
            "GET", "/bilibili.user.js"
        )
        self.assertEqual(cached_content, content)

    def test_userscript_is_loaded_lazily_and_load_errors_are_reported(self) -> None:
        self.userscript_path.unlink()

        with self.assertLogs("app.nr_challenge_tracker.api", level="ERROR"):
            status, payload = self.request("GET", "/bilibili.user.js")

        self.assertEqual(status, 500)
        self.assertEqual(payload, {"error": "userscript_unavailable"})

        self.userscript_path.write_text(
            "// ==UserScript==\nconst API_BASE = \"__LOCAL_API_BASE__\";\n",
            encoding="utf-8",
        )
        status, _headers, content = self.request_raw("GET", "/bilibili.user.js")

        self.assertEqual(status, 200)
        self.assertIn(
            f'const API_BASE = "http://127.0.0.1:{self.server.port}";'.encode(),
            content,
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
            TrackerApiServer(
                "0.0.0.0",
                5678,
                lambda: {},
                lambda *_args: True,
                Path("unused.user.js"),
            )

    def test_state_error_returns_structured_service_unavailable(self) -> None:
        self.state_unavailable = True
        status, payload = self.request("GET", "/api/state")

        self.assertEqual(status, 503)
        self.assertEqual(payload, {"error": "state_unavailable"})


if __name__ == "__main__":
    unittest.main()