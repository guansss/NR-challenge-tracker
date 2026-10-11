"""Adaptive, bounded capture-to-recognition monitor."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any

import cv2

from .capture import WindowsWindowCapture, find_window_by_title, window_is_capturable
from .models import NightlordVariant, Progress, Session, SessionStatus
from .recognition import RecognitionEngine
from .runtime_paths import application_root
from .sessions import ACTIVE_STATUSES, SessionService, SessionTransitionError


class ScreenDebouncer:
    def __init__(self, confirmations: int = 3) -> None:
        if confirmations < 1:
            raise ValueError("Screen confirmations must be positive")
        self.confirmations = confirmations
        self._candidate: tuple[str, object] | None = None
        self._count = 0
        self._emitted: str | None = None
        self._emitted_candidate: tuple[str, object] | None = None

    def observe(self, screen: str, identity: object = None) -> str | None:
        if screen not in {"preparation", "result"}:
            self._candidate = None
            self._count = 0
            self._emitted = None
            self._emitted_candidate = None
            return None
        candidate = (screen, identity)
        if candidate != self._candidate:
            self._candidate = candidate
            self._count = 1
        else:
            self._count += 1
        if self._count < self.confirmations or self._emitted_candidate == candidate:
            return None
        self._emitted = screen
        self._emitted_candidate = candidate
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
        debug_dir: Path | None = None,
        debug_screenshots_enabled: bool = False,
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
        self._status = "monitor.stopped"
        self._status_values: dict[str, str] = {}
        self._window_handle: int | None = None
        self._window_unavailable = False
        self._capture_ended = threading.Event()
        self._capture_error_detail = ""
        self._preparation_active = False
        self.debug_dir = (
            Path(debug_dir)
            if debug_dir is not None
            else application_root() / "debug" / "screenshots"
        )
        self.debug_screenshots_enabled = debug_screenshots_enabled
        self._debug_saved_paths: set[Path] = set()
        self._result_active = False
        self._pending_result: dict[str, Any] = {}
        self._result_session_id: str | None = None
        self._persisted_result: dict[str, Any] | None = None
        self._result_ended_at: datetime | None = None

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
        self._reset_screen_state()
        self._publish("monitor.paused")

    def resume(self) -> None:
        self._paused.clear()
        self._last_sample = 0.0
        self._drain_frames()
        self._reset_screen_state()
        self._publish("monitor.active")

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
        self._publish("monitor.stopped")

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                if self._capture is None:
                    target = find_window_by_title(self.target_window)
                    if target is None:
                        self._interrupt_active_session()
                        if not self._window_unavailable:
                            self._window_unavailable = True
                            self._publish("monitor.window_unavailable")
                        self._stop.wait(1.0)
                        continue
                    hwnd, title = target
                    self._window_handle = hwnd
                    self._capture_ended.clear()
                    self._capture_error_detail = ""
                    self._drain_frames()
                    self._reset_screen_state()
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
                    self._publish(
                        "monitor.monitoring_window", status_values={"title": title}
                    )

                if self._capture_ended.is_set():
                    self._interrupt_active_session()
                    self._capture.stop()
                    self._capture = None
                    self._window_handle = None
                    self._drain_frames()
                    if self._capture_error_detail:
                        self._publish(
                            "monitor.capture_error",
                            status_values={"detail": self._capture_error_detail},
                        )
                    else:
                        self._publish("monitor.window_unavailable")
                    self._stop.wait(1.0)
                    continue

                if self._window_handle is not None and not window_is_capturable(
                    self._window_handle
                ):
                    if not self._window_unavailable:
                        self._window_unavailable = True
                        self._interrupt_active_session()
                        self._drain_frames()
                        self._reset_screen_state()
                        self._publish("monitor.window_unavailable")
                    self._stop.wait(0.25)
                    continue
                if self._window_unavailable:
                    self._window_unavailable = False
                    self._publish("monitor.window_restored")
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
            self._publish(
                "monitor.capture_error", status_values={"detail": str(error)}
            )
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
        identity = None
        if screen == "result":
            identity = (
                result.get("nightlord"),
                result.get("variant"),
                result.get("outcome"),
            )
        recognized_session = None
        screen_entry = None
        if screen == "preparation":
            if self._result_active:
                recognized_session = self._finish_result()
            if self._preparation_active:
                recognized_session = self._handle_preparation(result)
            elif self.debouncer.observe(screen) == "preparation":
                screen_entry = screen
                self._preparation_active = True
                recognized_session = self._handle_preparation(result)
        elif screen == "result":
            self._preparation_active = False
            if self._result_active:
                self._remember_result(result)
                recognized_session = self._persist_complete_result()
            elif self.debouncer.observe(screen, identity) == "result":
                screen_entry = screen
                self._result_active = True
                self._pending_result = {}
                active_session = self._active_session()
                self._result_session_id = (
                    active_session.id if active_session is not None else None
                )
                self._persisted_result = None
                self._result_ended_at = None
                self._remember_result(result)
                recognized_session = self._persist_complete_result()
        else:
            self._preparation_active = False
            if self._result_active:
                recognized_session = self._finish_result()
            self.debouncer.observe(screen, identity)
        if (
            self.debouncer._emitted == screen
            and screen != "preparation"
            and not (screen == "result" and self._result_active)
        ):
            interval = self.idle_interval_ms
        self._sample_interval_ms = interval
        debug_error = (
            self._save_debug_screenshot(image, result, recognized_session)
            if recognized_session is not None
            else None
        )
        self._publish(
            "monitor.debug_screenshot_error" if debug_error else self.status,
            result,
            status_values={"detail": debug_error} if debug_error else None,
            screen_entry=screen_entry,
        )

    def _reset_screen_state(self) -> None:
        self.debouncer = ScreenDebouncer(self.debouncer.confirmations)
        self._preparation_active = False
        self._result_active = False
        self._pending_result = {}
        self._result_session_id = None
        self._persisted_result = None
        self._result_ended_at = None

    def _handle_preparation(self, result: dict[str, Any]) -> Session | None:
        nightfarer_id = result.get("nightfarer")
        nightlord_id = result.get("nightlord")
        hidden = nightlord_id == "hidden"
        if not nightfarer_id or (not hidden and not nightlord_id):
            return None
        pending = next(
            (
                session
                for session in reversed(self.sessions.snapshot.sessions)
                if session.status in ACTIVE_STATUSES
            ),
            None,
        )
        if pending is not None:
            same_character = (pending.nightfarer or "").casefold() == nightfarer_id.casefold()
            same_nightlord = pending.nightlord_hidden == hidden and (
                hidden
                or (pending.nightlord_name or "").casefold()
                == nightlord_id.casefold()
            )
            if (
                pending.status is SessionStatus.INTERRUPTED
                and same_character
                and same_nightlord
            ):
                return self.sessions.resume_interrupted(pending.id)
            elif pending.status is not SessionStatus.INTERRUPTED:
                return self.sessions.update_preparation(
                    pending.id,
                    nightfarer=nightfarer_id,
                    nightlord_name=None if hidden else nightlord_id,
                    hidden_nightlord=hidden,
                )
            return None
        session = self.sessions.start_session(
            nightfarer=nightfarer_id,
            nightlord_name=None if hidden else nightlord_id,
            hidden_nightlord=hidden,
            started_at=datetime.now().astimezone(),
        )
        self._publish("monitor.session_started", result)
        return session

    def _remember_result(self, result: dict[str, Any]) -> None:
        for field in ("nightlord", "variant", "outcome"):
            value = result.get(field)
            if field == "nightlord":
                if (
                    not isinstance(value, str)
                    or not value.strip()
                    or value.strip().casefold() == "unknown"
                ):
                    continue
            elif field == "variant":
                if (
                    not isinstance(value, str)
                    or _variant_from_value(value) is NightlordVariant.UNKNOWN
                ):
                    continue
            elif (
                not isinstance(value, str)
                or _progress_from_value(value)
                not in {
                    Progress.DAY_1,
                    Progress.DAY_2,
                    Progress.DAY_3,
                    Progress.DAY_3_VICTORY,
                }
            ):
                continue
            self._pending_result[field] = value

    def _result_is_complete(self) -> bool:
        nightlord = self._pending_result.get("nightlord")
        return (
            isinstance(nightlord, str)
            and bool(nightlord.strip())
            and _variant_from_value(self._pending_result.get("variant"))
            is not NightlordVariant.UNKNOWN
            and _progress_from_value(self._pending_result.get("outcome"))
            in {
                Progress.DAY_1,
                Progress.DAY_2,
                Progress.DAY_3,
                Progress.DAY_3_VICTORY,
            }
        )

    def _active_session(self) -> Session | None:
        return next(
            (
                entry
                for entry in reversed(self.sessions.snapshot.sessions)
                if entry.status in ACTIVE_STATUSES
            ),
            None,
        )

    def _finish_result(self) -> Session | None:
        recognized_session = self._persist_result()
        self._result_active = False
        self._pending_result = {}
        self._result_session_id = None
        self._persisted_result = None
        self._result_ended_at = None
        return recognized_session

    def _persist_complete_result(self) -> Session | None:
        if not self._result_is_complete():
            return self._active_session()
        return self._persist_result()

    def _persist_result(self) -> Session | None:
        session_id = self._result_session_id
        result = self._pending_result
        if (
            session_id is None
            or result == self._persisted_result
        ):
            return None
        if self._result_ended_at is None:
            self._result_ended_at = datetime.now(timezone.utc).astimezone()
        save_result = (
            self.sessions.finalize_result
            if self._persisted_result is None
            else self.sessions.update_result
        )
        saved = save_result(
            session_id,
            progress=_progress_from_value(result.get("outcome")),
            ended_at=self._result_ended_at,
            nightlord_name=result.get("nightlord"),
            variant=_variant_from_value(result.get("variant")),
        )
        self._persisted_result = result.copy()
        self._publish("monitor.result_recorded", result)
        return saved

    def _save_debug_screenshot(
        self, image: Any, result: dict[str, Any], session: Session
    ) -> str | None:
        if (
            not self.debug_screenshots_enabled
            or image is None
            or self.debug_dir is None
        ):
            return None
        screen = result.get("screen")
        if screen == "preparation":
            identity = (
                result.get("nightfarer"),
                result.get("nightlord"),
            )
        elif screen == "result":
            identity = (
                result.get("nightlord"),
                result.get("variant"),
                result.get("outcome"),
            )
        else:
            return None

        session_number = self._session_ordinal(session.id)
        if session_number is None:
            return None
        identity_text = "_".join(self._filename_part(value) for value in identity)
        path = self.debug_dir / f"{session_number:04d}_{screen}_{identity_text}.png"
        if path in self._debug_saved_paths:
            return None

        created_path = False
        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            if path.exists():
                self._debug_saved_paths.add(path)
                return None
            annotated = self.engine.render_debug_image(image, result)
            encoded, buffer = cv2.imencode(".png", annotated)
            if not encoded:
                return "Could not encode the annotated frame"
            try:
                with path.open("xb") as screenshot_file:
                    created_path = True
                    screenshot_file.write(buffer.tobytes())
            except FileExistsError:
                self._debug_saved_paths.add(path)
                return None
            self._debug_saved_paths.add(path)
        except Exception as error:
            if created_path:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            return str(error)
        return None

    def _session_ordinal(self, session_id: str) -> int | None:
        for ordinal, session in enumerate(self.sessions.snapshot.sessions, start=1):
            if session.id == session_id:
                return ordinal
        return None

    @staticmethod
    def _filename_part(value: Any) -> str:
        normalized = re.sub(r"[^a-z0-9_-]+", "-", str(value or "unknown").casefold())
        return normalized.strip("-_") or "unknown"

    def _capture_closed(self) -> None:
        self._capture_ended.set()

    def _capture_error(self, error: Exception) -> None:
        self._capture_error_detail = str(error)
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

    def _publish(
        self,
        status_key: str,
        recognition: dict[str, Any] | None = None,
        *,
        status_values: dict[str, str] | None = None,
        screen_entry: str | None = None,
    ) -> None:
        with self._state_lock:
            if status_key != self._status or status_values is not None:
                self._status_values = status_values or {}
            self._status = status_key
            published_status_values = self._status_values.copy()
        self.on_update(
            {
                "snapshot": self.sessions.snapshot,
                "recognition": recognition,
                "status_values": published_status_values,
                "screen_entry": screen_entry,
            },
            status_key,
        )


def _progress_from_value(value: str | None) -> Progress | None:
    try:
        return Progress(value) if value is not None else None
    except ValueError:
        return Progress.UNKNOWN


def _variant_from_value(value: str | None) -> NightlordVariant:
    try:
        return (
            NightlordVariant(value) if value is not None else NightlordVariant.UNKNOWN
        )
    except ValueError:
        return NightlordVariant.UNKNOWN
