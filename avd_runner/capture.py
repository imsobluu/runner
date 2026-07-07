"""Fast frame capture of the emulator window via Windows Graphics Capture.

Frames come back as BGR numpy arrays in device coordinates, ready for
find_template.

WGC captures the window's own surface, so other windows may cover the
emulator freely. It cannot be *minimized*, though: Windows stops rendering
minimized windows and frames stop arriving.

Import this module directly (`from avd_runner.capture import WindowCapture`);
it is not re-exported from the package so the rest of avd_runner keeps
working without windows-capture installed.
"""
from __future__ import annotations

import atexit
import ctypes
import threading
from ctypes import wintypes

import cv2
import numpy as np
from windows_capture import WindowsCapture

# Without DPI awareness, window rects come back virtualized on scaled
# displays and the crop drifts off the render area.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except OSError:
    pass

_user32 = ctypes.windll.user32
_dwmapi = ctypes.windll.dwmapi
_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

RENDER_WINDOW_CLASS = "RenderWindow"  # LDPlayer's game surface child window
DWMWA_EXTENDED_FRAME_BOUNDS = 9
GA_ROOT = 2
SW_RESTORE = 9


class CaptureError(RuntimeError):
    pass


def find_render_window(title_substring: str = "LDPlayer") -> int:
    """Find the emulator's render child window (game surface, no chrome).

    Falls back to the top-level window when no RenderWindow child exists.
    """
    found: list[int] = []

    def on_child(child: int, _lparam: int) -> bool:
        buf = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(child, buf, 256)
        if buf.value == RENDER_WINDOW_CLASS:
            found.append(child)
            return False
        return True

    def on_top(hwnd: int, _lparam: int) -> bool:
        buf = ctypes.create_unicode_buffer(256)
        _user32.GetWindowTextW(hwnd, buf, 256)
        if not _user32.IsWindowVisible(hwnd) or title_substring not in buf.value:
            return True
        _user32.EnumChildWindows(hwnd, _EnumProc(on_child), 0)
        if not found:
            found.append(hwnd)
        return False

    _user32.EnumWindows(_EnumProc(on_top), 0)
    if not found:
        raise CaptureError(f"No visible window with {title_substring!r} in its title")
    return found[0]


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise CaptureError("Emulator window is gone")
    return (rect.left, rect.top, rect.right, rect.bottom)


def _visible_bounds(hwnd: int) -> tuple[int, int, int, int]:
    """DWM extended frame bounds: what WGC actually captures (no invisible
    resize borders, unlike GetWindowRect)."""
    rect = wintypes.RECT()
    if _dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd),
        DWMWA_EXTENDED_FRAME_BOUNDS,
        ctypes.byref(rect),
        ctypes.sizeof(rect),
    ):
        return _window_rect(hwnd)  # non-zero HRESULT: fall back
    return (rect.left, rect.top, rect.right, rect.bottom)


class WindowCapture:
    """Grabs frames of the emulator render window as BGR device-space arrays."""

    def __init__(
        self,
        title_substring: str = "LDPlayer",
        device_size: tuple[int, int] | None = None,
        first_frame_timeout: float = 5.0,
    ):
        self._render_hwnd = find_render_window(title_substring)
        self._root_hwnd = _user32.GetAncestor(self._render_hwnd, GA_ROOT)
        if _user32.IsIconic(self._root_hwnd):
            _user32.ShowWindow(self._root_hwnd, SW_RESTORE)  # WGC needs it unminimized
        self._device_size = device_size
        self._lock = threading.Lock()
        self._latest: np.ndarray | None = None
        self._first_frame = threading.Event()
        self._closed = False

        capture = WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            window_hwnd=self._root_hwnd,
        )

        @capture.event
        def on_frame_arrived(frame, capture_control):
            # The buffer is reused by the native side; copy before keeping.
            with self._lock:
                self._latest = frame.frame_buffer.copy()
            self._first_frame.set()

        @capture.event
        def on_closed():
            self._closed = True
            self._first_frame.set()  # unblock a grab() waiting on the first frame

        self._control = capture.start_free_threaded()
        # Stop the native capture thread even if the caller forgets close();
        # a live thread at interpreter shutdown is a fatal error.
        atexit.register(self.close)
        if not self._first_frame.wait(timeout=first_frame_timeout) or self._closed:
            self.close()
            raise CaptureError("No frame from the emulator window (minimized or closed?)")

    def grab(self) -> np.ndarray:
        """Latest frame in device coordinates.

        WGC only delivers *changed* frames; on a static screen this returns
        the previous frame rather than blocking.
        """
        if self._closed:
            raise CaptureError("Emulator window was closed")
        with self._lock:
            frame = self._latest

        # Crop the render area out of the whole-window frame. Rects are
        # re-queried every grab so a moved/resized window stays aligned.
        win_left, win_top, win_right, win_bottom = _visible_bounds(self._root_hwnd)
        ren_left, ren_top, ren_right, ren_bottom = _window_rect(self._render_hwnd)
        height, width = frame.shape[:2]
        # Scale in case the captured frame differs from the DWM rect (DPI).
        scale_x = width / max(1, win_right - win_left)
        scale_y = height / max(1, win_bottom - win_top)
        x1 = max(0, round((ren_left - win_left) * scale_x))
        y1 = max(0, round((ren_top - win_top) * scale_y))
        x2 = min(width, round((ren_right - win_left) * scale_x))
        y2 = min(height, round((ren_bottom - win_top) * scale_y))
        if x2 <= x1 or y2 <= y1:
            raise CaptureError("Render window is outside the captured frame")

        frame = frame[y1:y2, x1:x2, :3]  # drop alpha: BGRA -> BGR
        if self._device_size is not None and (frame.shape[1], frame.shape[0]) != self._device_size:
            frame = cv2.resize(frame, self._device_size)
        return np.ascontiguousarray(frame)

    def close(self) -> None:
        self._control.stop()

    def __enter__(self) -> "WindowCapture":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
