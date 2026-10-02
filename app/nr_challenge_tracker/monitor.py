"""Adaptive, bounded capture-to-recognition monitor."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from queue import Empty, Full, Queue
import threading
import time
from typing import Any

from .capture import WindowsWindowCapture, find_window_by_title, window_is_capturable
from .models import NightlordVariant, Progress, Session, SessionStatus
from .recognition import RecognitionEngine
from .sessions import ACTIVE_STATUSES, SessionService, SessionTransitionError


class ScreenDebouncer:
    def __init__(self, confirmations: int = 3) -> None:
        if confirmations < 1:
            raise ValueError("Screen confirmations must be positive")
        self.confirmations = confirmations
        self._candidate: tuple[str, object] | None = None
        self._count = 0
        self._emitted: str | None = None

    def observe(self, screen: str, identity: object = None) -> str | None:
        if screen not in {"preparation", "result"}:
            self._candidate = None
            self._count = 0
            self._emitted = None
            return None
        candidate = (screen, identity)
        if candidate != self._candidate:
            self._candidate = candidate
            self._count = 1
        else:
            self._count += 1
        if self._count < self.confirmations or self._emitted == screen:
            return None
        self._emitted = screen
        return screen


class RecognitionMonitor:
    def __init__(
        self,
        engine: RecognitionEngine,
        sessions: SessionService,
        target_window: str,
        on_update: Callable[[dict[str, Any], str], None],
        *,
        idle_interval_ms: int = 1000,
        preparation_interval_ms: int = 200,
        gameplay_interval_ms: int = 1000,
        result_interval_ms: int = 200,
        confirmations: int = 3,
    ) -> None:
        self.engine = engine
        self.sessions = sessions
        self.target_window = target_window
        self.on_update = on_update
        self.idle_interval_ms = idle_interval_ms
        self.preparation_interval_ms = preparation_interval_ms
        self.gameplay_interval_ms = gameplay_interval_ms
        self.result_interval_ms = result_interval_ms
        self.debouncer = ScreenDebouncer(confirmations)
        self._frames: Queue[Any] = Queue(maxsize=1)
        self._thread: threading.Thread | None = None
        self._capture: WindowsWindowCapture | None = None
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._state_lock = threading.Lock()
        self._sample_interval_ms = idle_interval_ms
        self._last_sample = 0.0
        self._status = "Stopped"
        self._window_handle: int | None = None
        self._window_unavailable = False
        self._capture_ended = threading.Event()
        self._capture_error_message = ""
        self._nightfarer_names = {
            entry["id"]: entry["display_name"]
            for entry in engine.manifest["nightfarers"]
        }
        self._nightlord_names = {
            entry["id"]: entry["display_name"]
            for entry in engine.manifest["nightlords"]
        }

    @property
    def status(self) -> str:
        with self._state_lock:
            return self._status

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._paused.clear()
        self._thread = threading.Thread(
            target=self._run, name="nightreign-recognition", daemon=True
        )
        self._thread.start()

    def pause(self) -> None:
        self._paused.set()
        self._drain_frames()
        self.debouncer = ScreenDebouncer(self.debouncer.confirmations)
        self._publish("Monitoring paused")

    def resume(self) -> None:
        self._paused.clear()
        self._last_sample = 0.0
        self._drain_frames()
        self.debouncer = ScreenDebouncer(self.debouncer.confirmations)
        self._publish("Monitoring active")

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def stop(self) -> None:
        self._stop.set()
        if self._capture:
            self._capture.stop()
            self._capture = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._interrupt_active_session()
        self._publish("Stopped")

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                if self._capture is None:
                    target = find_window_by_title(self.target_window)
                    if target is None:
                        self._interrupt_active_session()
                        if not self._window_unavailable:
                            self._window_unavailable = True
                            self._publish("Game window unavailable")
                        self._stop.wait(1.0)
                        continue
                    hwnd, title = target
                    self._window_handle = hwnd
                    self._capture_ended.clear()
                    self._capture_error_message = ""
                    self._drain_frames()
                    self.debouncer = ScreenDebouncer(self.debouncer.confirmations)
                    self._capture = WindowsWindowCapture(
                        hwnd,
                        self._accept_frame,
                        self._capture_closed,
                        self._capture_error,
                        self._should_sample,
                        update_interval_ms=min(
                            self.preparation_interval_ms, self.result_interval_ms
                        ),
                    )
                    self._capture.start()
                    self._window_unavailable = False
                    self._publish(f"Monitoring {title}")

                if self._capture_ended.is_set():
                    self._interrupt_active_session()
                    self._capture.stop()
                    self._capture = None
                    self._window_handle = None
                    self._drain_frames()
                    self._publish(
                        self._capture_error_message or "Game window unavailable"
                    )
                    self._stop.wait(1.0)
                    continue

                if self._window_handle is not None and not window_is_capturable(
                    self._window_handle
                ):
                    if not self._window_unavailable:
                        self._window_unavailable = True
                        self._interrupt_active_session()
                        self._drain_frames()
                        self.debouncer = ScreenDebouncer(self.debouncer.confirmations)
                        self._publish("Game window unavailable")
                    self._stop.wait(0.25)
                    continue
                if self._window_unavailable:
                    self._window_unavailable = False
                    self._publish("Game window restored")
                try:
                    image = self._frames.get(timeout=0.5)
                except Empty:
                    continue
                if image is None:
                    continue
                if self._paused.is_set():
                    continue
                self._process(image)
        except Exception as error:
            self._stop.set()
            self._interrupt_active_session()
            self._publish(f"Capture error: {error}")
        finally:
            if self._capture:
                self._capture.stop()
                self._capture = None

    def _accept_frame(self, image: Any) -> None:
        try:
            self._frames.put_nowait(image)
        except Full:
            try:
                self._frames.get_nowait()
            except Empty:
                pass
            try:
                self._frames.put_nowait(image)
            except Full:
                pass

    def _should_sample(self) -> bool:
        if self._stop.is_set() or self._paused.is_set():
            return False
        now = time.monotonic()
        if (now - self._last_sample) * 1000 < self._sample_interval_ms:
            return False
        self._last_sample = now
        return True

    def _process(self, image: Any) -> None:
        result = self.engine.recognize(image)
        screen = result.get("screen", "unknown")
        interval = (
            self.preparation_interval_ms
            if screen == "preparation"
            else self.result_interval_ms
            if screen == "result"
            else self.gameplay_interval_ms
        )
        if self.debouncer._emitted == screen:
            interval = self.idle_interval_ms
        self._sample_interval_ms = interval

        identity = None
        if screen == "preparation":
            identity = (result.get("nightfarer"), result.get("nightlord"))
        elif screen == "result":
            identity = (
                result.get("nightlord"),
                result.get("variant"),
                result.get("outcome"),
            )
        confirmed = self.debouncer.observe(screen, identity)
        if confirmed == "preparation":
            self._handle_preparation(result)
        elif confirmed == "result":
            self._handle_result(result)
        self._publish(self.status, result)

    def _handle_preparation(self, result: dict[str, Any]) -> None:
        nightfarer_id = result.get("nightfarer")
        nightlord_id = result.get("nightlord")
        hidden = nightlord_id == "hidden"
        if not nightfarer_id or (not hidden and not nightlord_id):
            return
        pending = next(
            (
                session
                for session in reversed(self.sessions.snapshot.sessions)
                if session.status in ACTIVE_STATUSES
            ),
            None,
        )
        if pending is not None:
            same_character = (pending.nightfarer or "").casefold() == (
                self._nightfarer_names.get(nightfarer_id, nightfarer_id) or ""
            ).casefold()
            same_nightlord = pending.nightlord_hidden == hidden and (
                hidden
                or (pending.nightlord_name or "").casefold()
                == (self._nightlord_names.get(nightlord_id, nightlord_id) or "").casefold()
            )
            if pending.status is SessionStatus.INTERRUPTED and same_character and same_nightlord:
                self.sessions.resume_interrupted(pending.id)
            return
        self.sessions.start_session(
            nightfarer=self._nightfarer_names.get(nightfarer_id, nightfarer_id),
            nightlord_name=(
                None if hidden else self._nightlord_names.get(nightlord_id, nightlord_id)
            ),
            hidden_nightlord=hidden,
            started_at=datetime.now().astimezone(),
        )
        self._publish("Session started", result)

    def _handle_result(self, result: dict[str, Any]) -> None:
        session = next(
            (
                entry
                for entry in reversed(self.sessions.snapshot.sessions)
                if entry.status in ACTIVE_STATUSES
            ),
            None,
        )
        if session is None:
            return
        progress = _progress_from_value(result.get("outcome"))
        nightlord_id = result.get("nightlord")
        self.sessions.finalize_result(
            session.id,
            progress=progress,
            ended_at=datetime.now(timezone.utc).astimezone(),
            nightlord_name=(
                self._nightlord_names.get(nightlord_id, nightlord_id)
                if nightlord_id
                else None
            ),
            variant=_variant_from_value(result.get("variant")),
        )
        self._publish("Result recorded", result)

    def _capture_closed(self) -> None:
        self._capture_ended.set()

    def _capture_error(self, error: Exception) -> None:
        self._capture_error_message = f"Capture error: {error}"
        self._capture_ended.set()

    def _interrupt_active_session(self) -> None:
        try:
            self.sessions.interrupt_active_sessions()
        except SessionTransitionError:
            pass

    def _drain_frames(self) -> None:
        while True:
            try:
                self._frames.get_nowait()
            except Empty:
                return

    def _publish(self, status: str, recognition: dict[str, Any] | None = None) -> None:
        with self._state_lock:
            self._status = status
        self.on_update(
            {"snapshot": self.sessions.snapshot, "recognition": recognition}, status
        )


def _progress_from_value(value: str | None) -> Progress | None:
    try:
        return Progress(value) if value is not None else None
    except ValueError:
        return Progress.UNKNOWN


def _variant_from_value(value: str | None) -> NightlordVariant:
    try:
        return NightlordVariant(value) if value is not None else NightlordVariant.UNKNOWN
    except ValueError:
        return NightlordVariant.UNKNOWN