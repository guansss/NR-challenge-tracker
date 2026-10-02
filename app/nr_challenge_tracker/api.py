"""Loopback-only streak API and restricted userscript status reporting."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import threading
from typing import Any, Callable

from .title_state import SYNC_STATES


class StreakApiServer:
    def __init__(
        self,
        host: str,
        port: int,
        get_state: Callable[[], dict[str, Any]],
        report_sync: Callable[[str, int, str], bool],
    ) -> None:
        try:
            address = ipaddress.ip_address(host)
        except ValueError as error:
            raise ValueError("API host must be a loopback IP address") from error
        if not address.is_loopback:
            raise ValueError("API must bind to a loopback IP address")
        self.get_state = get_state
        self.report_sync = report_sync
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path != "/api/streak":
                    self._send(404, {"error": "not_found"})
                    return
                try:
                    payload = owner.get_state()
                except Exception:
                    self._send(503, {"error": "state_unavailable"})
                    return
                self._send(200, payload)

            def do_POST(self) -> None:
                if self.path != "/api/sync-status":
                    self._send(404, {"error": "not_found"})
                    return
                if self.headers.get_content_type() != "application/json":
                    self._send(415, {"error": "content_type_must_be_json"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 2048:
                        raise ValueError("invalid_content_length")
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError("body_must_be_object")
                    status = payload.get("status")
                    revision = payload.get("revision")
                    message = payload.get("message", "")
                    if not isinstance(status, str) or status not in SYNC_STATES:
                        raise ValueError("invalid_status")
                    if isinstance(revision, bool) or not isinstance(revision, int):
                        raise ValueError("invalid_revision")
                    if not isinstance(message, str) or len(message) > 200:
                        raise ValueError("invalid_message")
                except (ValueError, json.JSONDecodeError) as error:
                    self._send(400, {"error": str(error)})
                    return
                accepted = owner.report_sync(status, revision, message)
                self._send(200 if accepted else 409, {"accepted": accepted})

            def _send(self, status: int, payload: dict[str, Any]) -> None:
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, _format: str, *_args: Any) -> None:
                return

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="streak-api", daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)