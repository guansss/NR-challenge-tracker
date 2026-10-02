"""Window discovery and Windows Graphics Capture adapter."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
from typing import Any, Callable


def find_window_by_title(title_part: str) -> tuple[int, str] | None:
    if not title_part.strip():
        raise ValueError("Target window title cannot be empty")
    if not hasattr(ctypes, "windll"):
        raise RuntimeError("Window capture is available only on Windows")

    user32 = ctypes.windll.user32
    matches: list[tuple[int, str]] = []
    enum_windows_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    @enum_windows_proc
    def visit(hwnd: int, _parameter: int) -> bool:
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        title_buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, length + 1)
        window_title = title_buffer.value
        if title_part.casefold() in window_title.casefold():
            matches.append((int(hwnd), window_title))
        return True

    if not user32.EnumWindows(visit, 0):
        return None
    return matches[0] if matches else None


def window_is_capturable(hwnd: int) -> bool:
    if not hasattr(ctypes, "windll"):
        return False
    user32 = ctypes.windll.user32
    return bool(
        user32.IsWindow(hwnd)
        and user32.IsWindowVisible(hwnd)
        and not user32.IsIconic(hwnd)
    )


class WindowsWindowCapture:
    """Capture one selected top-level window and forward copied BGR frames."""

    def __init__(
        self,
        hwnd: int,
        on_frame: Callable[[Any], None],
        on_closed: Callable[[], None],
        on_error: Callable[[Exception], None],
        should_sample: Callable[[], bool],
        update_interval_ms: int = 200,
    ) -> None:
        self.hwnd = hwnd
        self.on_frame = on_frame
        self.on_closed = on_closed
        self.on_error = on_error
        self.should_sample = should_sample
        self.update_interval_ms = update_interval_ms
        self._capture: Any | None = None
        self._control: Any | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        from windows_capture import WindowsCapture

        capture = WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            minimum_update_interval=self.update_interval_ms,
            window_hwnd=self.hwnd,
        )

        @capture.event
        def on_frame_arrived(frame: Any, _capture_control: Any) -> None:
            if not self.should_sample():
                return
            try:
                image = frame.convert_to_bgr().frame_buffer.copy()
                self.on_frame(image)
            except Exception as error:
                self.on_error(error)

        @capture.event
        def on_closed() -> None:
            self.on_closed()

        self._capture = capture
        self._control = capture.start_free_threaded()

    def stop(self) -> None:
        with self._lock:
            control = self._control
            self._control = None
        if control is not None:
            control.stop()
            control.wait()