"""Per-level gameplay replay driven continuously by observed level progress.

Each moving-phase tap is stored at the progress-marker position observed when
the player made it. Playback fires that tap when the live marker reaches the
same position, continuously correcting for start delay and speed variation.
Wall time is retained only for taps made while the marker is stationary or
temporarily unavailable.
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .device import AvdDevice
from .vision import find_template

PAUSE_XY = (1194, 37)
# v1: t=0 at the Continue tap, no freeze compensation (worked, but desynced
#     when detection lateness differed between record and replay).
# v2/v3: progress-bar-as-linear-clock, replay without pausing (asymmetric;
#     desynced badly - kept only as a cautionary tale).
# v4: v1 symmetric handshake + frozen-marker position compensation.
# v5: each tap is keyed to live level progress; wall time is only a fallback
#     while the marker is stationary or unavailable.
TRACE_VERSION = 5

# Progress bar geometry (device px, 1280x720): the gingerbread marker walks
# a fixed track; its center maps to progress via the calibrated start/end x.
STRIP_Y1, STRIP_Y2, STRIP_X1, STRIP_X2 = 100, 140, 120, 355
PROGRESS_START_X, PROGRESS_END_X = 139, 325
MARKER_THRESHOLD = 0.7

# The marker can be unreadable for seconds around a level transition and
# reappear a few percent in (up to ~7% observed).
LEVEL_START_MAX = 0.3
LEVEL_END_MIN = 0.85
# The marker RESTS at ~0% during the level intro before it starts walking;
# positions below this carry no useful progress-clock timing signal.
MOVING_MIN = 0.02


def load_marker(assets_dir: Path) -> np.ndarray:
    marker = cv2.imread(str(assets_dir / "level_banners" / "progress_marker.png"))
    if marker is None:
        raise ValueError(f"Missing progress marker template in {assets_dir}")
    return marker


def continue_template(assets_dir: Path) -> Path:
    path = assets_dir / "level_banners" / "continue_button.png"
    if not path.exists():
        raise ValueError(f"Missing Continue button template: {path}")
    return path


def locate_marker(
    frame: np.ndarray, marker: np.ndarray
) -> tuple[float, tuple[int, int, int, int]] | None:
    """(progress in [0..1], marker box in device px), or None when off screen.

    Subpixel: a parabola through the match scores around the peak recovers
    the marker's fractional position (~0.1px).
    """
    strip = frame[STRIP_Y1:STRIP_Y2, STRIP_X1:STRIP_X2]
    result = cv2.matchTemplate(strip, marker, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(result)
    if score < MARKER_THRESHOLD:
        return None
    x, y = loc
    dx = 0.0
    if 0 < x < result.shape[1] - 1:
        r = result[y, x - 1 : x + 2].astype(np.float64)
        denom = r[0] - 2 * r[1] + r[2]
        if denom != 0:
            dx = float(np.clip(0.5 * (r[0] - r[2]) / denom, -1, 1))
    mh, mw = marker.shape[:2]
    center = STRIP_X1 + x + dx + mw / 2
    progress = (center - PROGRESS_START_X) / (PROGRESS_END_X - PROGRESS_START_X)
    box = (STRIP_X1 + x, STRIP_Y1 + y, STRIP_X1 + x + mw, STRIP_Y1 + y + mh)
    return progress, box


def read_progress(frame: np.ndarray, marker: np.ndarray) -> float | None:
    """Level progress in [0..1], or None when the bar is not on screen."""
    located = locate_marker(frame, marker)
    return located[0] if located is not None else None


def load_levels(levels_dir: Path) -> dict[int, dict]:
    """Map of level number to its progress-keyed tap trace."""
    levels = {}
    for path in sorted(Path(levels_dir).glob("level_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != TRACE_VERSION:
            raise ValueError(
                f"{path} is trace format v{data.get('version')}; this build needs "
                f"v{TRACE_VERSION}. Re-record it with scripts/record_levels.py."
            )
        taps = data["taps"]
        for tap in taps:
            if "progress" not in tap:
                raise ValueError(f"{path} has a tap without recorded progress")
        levels[data["level"]] = {"taps": taps}
    return levels


def tap_is_due(tap: dict, progress: float | None, elapsed: float) -> bool:
    """Whether a recorded tap is due on the progress clock or time fallback."""
    recorded_progress = tap["progress"]
    if recorded_progress is not None and recorded_progress >= MOVING_MIN:
        return progress is not None and progress >= recorded_progress
    return elapsed >= tap["t"]


@dataclass
class ReplayState:
    level: int
    in_level: bool = False
    max_progress: float = 0.0
    stable_low: int = 0
    frame_count: int = 0
    recorded: dict | None = None
    tap_index: int = 0
    level_t0: float = 0.0


class LevelReplayer:
    """Replays per-level taps against the live progress marker."""

    def __init__(
        self,
        device: AvdDevice,
        capture,  # WindowCapture; untyped so this module imports without it
        assets_dir: Path,
        levels_dir: Path,
        exit_template: Path,
        on_tap=None,  # on_tap(name, frame, x, y): debug hook for handshake taps
        debug_view=None,  # DebugView; draws marker box and taps live
    ):
        self._device = device
        self._capture = capture
        self._marker = load_marker(assets_dir)
        self._levels = load_levels(levels_dir)
        self._exit_template = exit_template
        self._on_tap = on_tap
        self._debug_view = debug_view
        if not self._levels:
            raise ValueError(f"No level recordings in {levels_dir}")

    def _tap(self, shell, x: int, y: int, duration: float) -> None:
        # Jitter position, duration, and add a few px of down->up drift;
        # identical zero-travel replays run after run look robotic.
        x += random.randint(-8, 8)
        y += random.randint(-8, 8)
        x2 = x + random.randint(-3, 3)
        y2 = y + random.randint(-3, 3)
        ms = max(30, round(duration * 1000 * random.uniform(0.95, 1.05)))
        shell.swipe(x, y, x2, y2, ms, background=True, label="jump" if x < 640 else "slide")

    def _start_level(self, state: ReplayState) -> None:
        state.recorded = self._levels.get(state.level)
        state.level_t0 = time.perf_counter()
        state.tap_index = 0
        if state.recorded is None:
            print(f"No recording for level {state.level}; watching only.")
        else:
            print(
                f"Level {state.level}: progress-driven replay of "
                f"{len(state.recorded['taps'])} taps."
            )
        state.in_level = True
        state.max_progress = 0.0

    def _play_due_taps(self, state: ReplayState, shell, progress: float | None, now: float) -> None:
        if state.recorded is None:
            return
        taps = state.recorded["taps"]
        while state.tap_index < len(taps):
            tap = taps[state.tap_index]
            due = tap_is_due(tap, progress, now - state.level_t0)
            if not due:
                break
            self._tap(shell, tap["x"], tap["y"], tap["duration"])
            state.tap_index += 1

    def _frame_progress(self, frame) -> tuple[float | None, tuple[int, int, int, int] | None]:
        located = locate_marker(frame, self._marker)
        if located is None:
            return None, None
        return located

    def _update_debug_view(
        self,
        frame,
        progress: float | None,
        marker_box: tuple[int, int, int, int] | None,
    ) -> None:
        if self._debug_view is None:
            return
        boxes = []
        if progress is not None and marker_box is not None:
            boxes.append((*marker_box, f"progress {progress:.0%}", (0, 255, 0)))
        self._debug_view.update(frame, boxes)

    def run(self, max_seconds: float = 1200.0) -> bool:
        """Replay levels until the result screen appears. False on timeout."""
        deadline = time.perf_counter() + max_seconds
        state = ReplayState(level=min(self._levels))

        with self._device.input_shell() as shell:
            while time.perf_counter() < deadline:
                frame = self._capture.grab()
                state.frame_count += 1
                time.sleep(0.02)

                if state.frame_count % 30 == 0 and find_template(frame, self._exit_template, threshold=0.85):
                    print("Result screen detected; replay finished.")
                    return True

                progress, marker_box = self._frame_progress(frame)
                self._play_due_taps(state, shell, progress, time.perf_counter())
                self._update_debug_view(frame, progress, marker_box)

                if progress is None:
                    continue

                if not state.in_level:
                    state.stable_low = state.stable_low + 1 if progress < LEVEL_START_MAX else 0
                    if state.stable_low >= 3:
                        state.stable_low = 0
                        self._start_level(state)
                    continue

                if state.max_progress > LEVEL_END_MIN and progress < LEVEL_START_MAX:
                    print(f"Level {state.level} finished.")
                    state.level += 1
                    self._start_level(state)
                    continue

                state.max_progress = max(state.max_progress, progress)

            print("Level replay timed out without reaching the result screen.")
            return False
