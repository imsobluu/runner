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
from typing import NamedTuple

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
MARKER_MASK_MIN = 8
MARKER_EDGE_THRESHOLD = 0.55

# The marker can be unreadable for seconds around a level transition and
# reappear a few percent in (up to ~7% observed).
LEVEL_START_MAX = 0.3
LEVEL_END_MIN = 0.85
LEVEL_END_LOW_FRAMES = 8
MIN_LEVEL_SECONDS = 15.0
# The marker RESTS at ~0% during the level intro before it starts walking;
# positions below this carry no useful progress-clock timing signal.
MOVING_MIN = 0.02
_MARKER_MASK_CACHE: dict[int, np.ndarray] = {}
_MARKER_EDGE_CACHE: dict[int, np.ndarray] = {}


class MarkerDetection(NamedTuple):
    progress: float
    box: tuple[int, int, int, int]
    score: float
    method: str


class TrackedProgress(NamedTuple):
    progress: float | None
    source: str
    reason: str
    rate: float | None


MAX_PREDICTION_SECONDS = 2.0
MAX_FORWARD_RATE = 0.08
MAX_BACKWARD_STEP = 0.03
RATE_ALPHA = 0.15
INITIAL_PROGRESS_RATE = 0.018
WRAP_HIGH = 0.85
WRAP_LOW = 0.15


class ProgressTracker:
    """Temporal filter for raw progress detections.

    Accepts smooth progress and real wraps, predicts through short missing
    spans, and rejects implausible one-frame jumps.
    """

    def __init__(self):
        self._last_progress: float | None = None
        self._last_time: float | None = None
        self._rate: float | None = None

    def update(self, now: float, raw_progress: float | None) -> TrackedProgress:
        predicted = self._predict(now)
        if raw_progress is None:
            if predicted is None:
                return TrackedProgress(None, "unknown", "missing_no_prediction", self._rate)
            self._last_progress = predicted
            self._last_time = now
            return TrackedProgress(predicted, "predicted", "missing", self._rate)

        if self._last_progress is None or self._last_time is None:
            self._accept(now, raw_progress)
            return TrackedProgress(raw_progress, "raw", "first", self._rate)

        dt = max(1e-6, now - self._last_time)
        delta = raw_progress - self._last_progress
        if self._last_progress >= WRAP_HIGH and raw_progress <= WRAP_LOW:
            self._accept(now, raw_progress, reset_rate=True)
            return TrackedProgress(raw_progress, "raw", "accepted_wrap", self._rate)
        if delta < -MAX_BACKWARD_STEP:
            if predicted is None:
                return TrackedProgress(None, "unknown", "rejected_backward_no_prediction", self._rate)
            self._last_progress = predicted
            self._last_time = now
            return TrackedProgress(predicted, "predicted", "rejected_backward", self._rate)

        rate = delta / dt
        if rate > MAX_FORWARD_RATE:
            if predicted is None:
                return TrackedProgress(None, "unknown", "rejected_too_fast_no_prediction", self._rate)
            self._last_progress = predicted
            self._last_time = now
            return TrackedProgress(predicted, "predicted", "rejected_too_fast", self._rate)

        self._accept(now, raw_progress)
        return TrackedProgress(raw_progress, "raw", "accepted", self._rate)

    def _accept(self, now: float, progress: float, *, reset_rate: bool = False) -> None:
        if reset_rate:
            self._rate = INITIAL_PROGRESS_RATE
        elif self._last_progress is not None and self._last_time is not None:
            dt = max(1e-6, now - self._last_time)
            measured = max(0.0, min(MAX_FORWARD_RATE, (progress - self._last_progress) / dt))
            if self._rate is None:
                self._rate = measured
            else:
                self._rate = (1.0 - RATE_ALPHA) * self._rate + RATE_ALPHA * measured
        elif self._rate is None:
            self._rate = INITIAL_PROGRESS_RATE
        self._last_progress = progress
        self._last_time = now

    def _predict(self, now: float) -> float | None:
        if self._last_progress is None or self._last_time is None:
            return None
        dt = now - self._last_time
        if dt < 0 or dt > MAX_PREDICTION_SECONDS:
            return None
        rate = self._rate if self._rate is not None else INITIAL_PROGRESS_RATE
        return max(0.0, min(1.05, self._last_progress + rate * dt))


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


def marker_mask(marker: np.ndarray) -> np.ndarray:
    """Shape mask for the cookie marker; excludes most mutable background pixels."""
    key = id(marker)
    mask = _MARKER_MASK_CACHE.get(key)
    if mask is None:
        gray = cv2.cvtColor(marker, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 40, 120)
        mask = cv2.dilate(edges, np.ones((3, 3), dtype=np.uint8), iterations=1)
        if np.count_nonzero(mask) < 20:
            mask = np.where(np.any(marker > MARKER_MASK_MIN, axis=2), 255, 0).astype("uint8")
        _MARKER_MASK_CACHE[key] = mask
    return mask


def marker_edges(marker: np.ndarray) -> np.ndarray:
    key = id(marker)
    edges = _MARKER_EDGE_CACHE.get(key)
    if edges is None:
        gray = cv2.cvtColor(marker, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 40, 120)
        _MARKER_EDGE_CACHE[key] = edges
    return edges


def locate_marker(
    frame: np.ndarray, marker: np.ndarray
) -> tuple[float, tuple[int, int, int, int]] | None:
    detected = locate_marker_with_details(frame, marker)
    if detected is None:
        return None
    return detected.progress, detected.box


def locate_marker_with_details(
    frame: np.ndarray, marker: np.ndarray
) -> MarkerDetection | None:
    """(progress in [0..1], marker box in device px), or None when off screen.

    Subpixel: a parabola through the match scores around the peak recovers
    the marker's fractional position (~0.1px).
    """
    strip = frame[STRIP_Y1:STRIP_Y2, STRIP_X1:STRIP_X2]
    result = cv2.matchTemplate(strip, marker, cv2.TM_CCOEFF_NORMED, mask=marker_mask(marker))
    result = np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)
    _, score, _, loc = cv2.minMaxLoc(result)
    if score < MARKER_THRESHOLD:
        strip_edges = cv2.Canny(cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY), 40, 120)
        edge_result = cv2.matchTemplate(strip_edges, marker_edges(marker), cv2.TM_CCORR_NORMED)
        edge_result = np.nan_to_num(edge_result, nan=0.0, posinf=0.0, neginf=0.0)
        _, edge_score, _, edge_loc = cv2.minMaxLoc(edge_result)
        if edge_score < MARKER_EDGE_THRESHOLD:
            return None
        result = edge_result
        x, y = edge_loc
        score = edge_score
        method = "edge"
    else:
        x, y = loc
        method = "color"
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
    return MarkerDetection(progress=progress, box=box, score=float(score), method=method)


def read_progress(frame: np.ndarray, marker: np.ndarray) -> float | None:
    """Level progress in [0..1], or None when the bar is not on screen."""
    located = locate_marker(frame, marker)
    return located[0] if located is not None else None


def load_levels(levels_dir: Path) -> dict[int, list[dict]]:
    """Map of level number to one or more progress-keyed tap trace variants."""
    levels: dict[int, list[dict]] = {}
    root = Path(levels_dir)
    paths = sorted(root.glob("levels/level_*/level_*.json"))
    for path in paths:
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
        levels.setdefault(data["level"], []).append({"taps": taps, "path": path})
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
    replay_enabled: bool = True
    relay_handled: bool = False
    fast_start_handled: bool = False
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
        relay_template: Path | None = None,
        fast_start_template: Path | None = None,
        on_tap=None,  # on_tap(name, frame, x, y): debug hook for handshake taps
        debug_view=None,  # DebugView; draws marker box and taps live
    ):
        self._device = device
        self._capture = capture
        self._marker = load_marker(assets_dir)
        self._levels = load_levels(levels_dir)
        self._exit_template = exit_template
        self._relay_template = relay_template
        self._fast_start_template = fast_start_template
        self._on_tap = on_tap
        self._debug_view = debug_view
        if not self._levels:
            raise ValueError(f"No level recordings in {levels_dir}")

    def _tap(
        self,
        shell,
        x: int,
        y: int,
        duration: float,
        *,
        background: bool = True,
        label: str | None = None,
    ) -> None:
        # Jitter position, duration, and add a few px of down->up drift;
        # identical zero-travel replays run after run look robotic.
        x += random.randint(-8, 8)
        y += random.randint(-8, 8)
        x2 = x + random.randint(-3, 3)
        y2 = y + random.randint(-3, 3)
        ms = max(30, round(duration * 1000 * random.uniform(0.95, 1.05)))
        shell.swipe(
            x,
            y,
            x2,
            y2,
            ms,
            background=background,
            label=label or ("jump" if x < 640 else "slide"),
        )

    def _start_level(self, state: ReplayState) -> None:
        variants = self._levels.get(state.level)
        state.recorded = random.choice(variants) if state.replay_enabled and variants else None
        state.level_t0 = time.perf_counter()
        state.tap_index = 0
        if not state.replay_enabled:
            print(f"Level {state.level}: recorded replay disabled; watching only.")
        elif state.recorded is None:
            print(f"No recording for level {state.level}; watching only.")
        else:
            print(
                f"Level {state.level}: progress-driven replay of "
                f"{len(state.recorded['taps'])} taps from {state.recorded['path'].name}."
            )
        state.in_level = True
        state.max_progress = 0.0
        state.stable_low = 0

    def _play_due_taps(self, state: ReplayState, shell, progress: float | None, now: float) -> None:
        if not state.replay_enabled or state.recorded is None:
            return
        taps = state.recorded["taps"]
        while state.tap_index < len(taps):
            tap = taps[state.tap_index]
            due = tap_is_due(tap, progress, now - state.level_t0)
            if not due:
                break
            self._tap(shell, tap["x"], tap["y"], tap["duration"])
            state.tap_index += 1

    def _check_exit_or_relay(self, frame, state: ReplayState, shell) -> bool:
        if find_template(frame, self._exit_template, threshold=0.85):
            print("Result screen detected; replay finished.")
            return True

        if not state.fast_start_handled and self._fast_start_template is not None:
            match = find_template(frame, self._fast_start_template, threshold=0.85)
            if match:
                self._tap(
                    shell,
                    match.center_x,
                    match.center_y,
                    0.08,
                    background=False,
                    label="fast_start",
                )
                state.fast_start_handled = True
                print("Tapped Activate Fast Start; recorded replay continues.")

        if not state.relay_handled and self._relay_template is not None:
            match = find_template(frame, self._relay_template, threshold=0.85)
            if match:
                self._tap(
                    shell,
                    match.center_x,
                    match.center_y,
                    0.08,
                    background=False,
                    label="relay",
                )
                state.relay_handled = True
                state.replay_enabled = False
                state.recorded = None
                print("Tapped Activate Cookie Relay; recorded replay disabled.")
        return False

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

                if state.frame_count % 15 == 0 and self._check_exit_or_relay(frame, state, shell):
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

                elapsed = time.perf_counter() - state.level_t0
                if (
                    state.max_progress > LEVEL_END_MIN
                    and elapsed >= MIN_LEVEL_SECONDS
                    and progress < LEVEL_START_MAX
                ):
                    state.stable_low += 1
                    if state.stable_low < LEVEL_END_LOW_FRAMES:
                        continue
                    print(f"Level {state.level} finished.")
                    state.level += 1
                    self._start_level(state)
                    continue
                if progress >= LEVEL_START_MAX:
                    state.stable_low = 0

                state.max_progress = max(state.max_progress, progress)

            print("Level replay timed out without reaching the result screen.")
            return False
