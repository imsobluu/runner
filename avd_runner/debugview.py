"""Live OpenCV overlay window for debugging detection and taps.

Self-pumping AND self-sourcing: a dedicated thread owns the window, pulls its
own live frames from a WindowCapture (~30fps), and draws the overlays the main
thread hands over. Because the frame source is independent of the main thread,
the window stays live during multi-second poll loops (scanning, verify-gone,
captcha). Callers only provide data - detection boxes via update() and tap/drag
gestures via mark_tap()/mark_swipe() - and never touch OpenCV, keeping all GUI
calls on the one thread.

If constructed without a capture, it falls back to displaying whatever frame
update() last provided (choppy, bounded by the caller's screenshot rate).
"""
from __future__ import annotations

import threading
import time

import cv2
import numpy as np

# (x1, y1, x2, y2, label, BGR color)
Box = tuple[int, int, int, int, str, tuple[int, int, int]]


class DebugView:
    def __init__(
        self,
        title: str = "avd-runner debug",
        tap_seconds: float = 0.8,
        fps: int = 30,
        capture=None,  # WindowCapture; when given, the pump grabs its own frames
    ):
        self._title = title
        self._tap_seconds = tap_seconds
        self._frame_interval = 1.0 / fps
        self._capture = capture
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None  # fallback frame when no capture
        self._boxes: tuple[Box, ...] = ()
        self._taps: list[list] = []  # [x, y, label, expiry_monotonic]
        self._swipes: list[list] = []  # [x1, y1, x2, y2, start, end, label]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def update(self, frame: np.ndarray, boxes: list[Box] | tuple[Box, ...] = ()) -> None:
        """Set the detection boxes to draw. With a capture, `frame` is ignored
        in favor of the live grab; without one, it is the frame to display."""
        with self._lock:
            if self._capture is None:
                self._frame = frame
            self._boxes = tuple(boxes)

    def mark_tap(self, x: int, y: int, label: str = "") -> None:
        """Record a tap to draw for the next tap_seconds."""
        with self._lock:
            self._taps.append([int(x), int(y), label, time.monotonic() + self._tap_seconds])

    def mark_swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int,
        label: str = "",
    ) -> None:
        """Animate a down/move/up gesture over its real duration."""
        now = time.monotonic()
        duration = max(0.04, duration_ms / 1000)
        with self._lock:
            self._swipes.append([
                int(x1),
                int(y1),
                int(x2),
                int(y2),
                now,
                now + duration,
                label,
            ])

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                boxes = self._boxes
                now = time.monotonic()
                self._taps = [t for t in self._taps if t[3] > now]
                taps = list(self._taps)
                hold_until = now - self._tap_seconds
                self._swipes = [s for s in self._swipes if s[5] > hold_until]
                swipes = list(self._swipes)
                fallback = None if self._capture is not None else (
                    self._frame.copy() if self._frame is not None else None
                )

            frame = fallback
            if self._capture is not None:
                try:
                    frame = self._capture.grab().copy()
                except Exception:
                    frame = None  # window minimized/gone; try again next tick

            if frame is None:
                time.sleep(self._frame_interval)
                continue

            for x1, y1, x2, y2, label, color in boxes:
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                if label:
                    cv2.putText(frame, label, (x1, max(12, y1 - 6)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            for x, y, label, _ in taps:
                cv2.circle(frame, (x, y), 11, (0, 0, 255), 2)
                cv2.drawMarker(frame, (x, y), (0, 0, 255), cv2.MARKER_CROSS, 10, 1)
                if label:
                    cv2.putText(frame, label, (x + 14, y + 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            for x1, y1, x2, y2, start, end, label in swipes:
                duration = max(1e-6, end - start)
                progress = min(1.0, max(0.0, (time.monotonic() - start) / duration))
                x = round(x1 + (x2 - x1) * progress)
                y = round(y1 + (y2 - y1) * progress)
                cv2.line(frame, (x1, y1), (x2, y2), (0, 0, 160), 2)
                cv2.circle(frame, (x1, y1), 6, (0, 0, 120), 1)
                cv2.circle(frame, (x2, y2), 6, (0, 0, 120), 1)
                trail_steps = max(2, round(12 * progress))
                for i in range(trail_steps):
                    t = progress * i / max(1, trail_steps - 1)
                    tx = round(x1 + (x2 - x1) * t)
                    ty = round(y1 + (y2 - y1) * t)
                    cv2.circle(frame, (tx, ty), 3, (0, 0, 220), -1)
                cv2.circle(frame, (x, y), 13, (0, 0, 255), 2)
                cv2.circle(frame, (x, y), 4, (0, 0, 255), -1)
                if label:
                    cv2.putText(frame, label, (x + 14, y + 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

            cv2.imshow(self._title, frame)
            cv2.waitKey(max(1, round(self._frame_interval * 1000)))

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        try:
            cv2.destroyWindow(self._title)
            cv2.waitKey(1)
        except cv2.error:
            pass
