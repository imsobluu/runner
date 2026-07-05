"""Per-level gameplay replay, synchronized by a symmetric pause handshake.

Recording and playback perform the IDENTICAL sequence at every level start:
detect the level on the progress bar, tap pause, tap Continue, and take t=0
from the frame where the pause menu disappears. Because both sides interact
with the game the same way, every latency and game side-effect of pausing
appears on both sides and cancels. This symmetry is what made the original
implementation work; do not break it.

The one asymmetry left is WHERE in the level the freeze lands (detection can
be late by a variable amount when a transition hides the marker). Both sides
therefore measure the marker's exact position while frozen - it is static
and readable behind the pause menu - and the replayer shifts its schedule by
(p_replay - p_record) / marker_speed, a purely local correction that is zero
when the freeze points match.
"""
from __future__ import annotations

import json
import random
import subprocess
import threading
import time
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
TRACE_VERSION = 4

# Progress bar geometry (device px, 1280x720): the gingerbread marker walks
# a fixed track; its center maps to progress via the calibrated start/end x.
STRIP_Y1, STRIP_Y2, STRIP_X1, STRIP_X2 = 100, 140, 120, 355
PROGRESS_START_X, PROGRESS_END_X = 139, 325
MARKER_THRESHOLD = 0.7

# The marker can be unreadable for seconds around a level transition and
# reappear a few percent in (up to ~7% observed); the freeze-position
# compensation absorbs the difference.
LEVEL_START_MAX = 0.3
LEVEL_END_MIN = 0.85
# The marker RESTS at ~0% during the level intro before it starts walking;
# positions below this carry no timing signal (compensation is skipped, as
# resting freezes are the same game state on both sides).
MOVING_MIN = 0.02
MOVING_MAX = 0.95
FREEZE_SAMPLES = 5      # frames averaged to read the frozen marker position
STALE_TAP_LIMIT = 0.75  # taps already this late at start are skipped


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


def read_progress(frame: np.ndarray, marker: np.ndarray) -> float | None:
    """Level progress in [0..1], or None when the bar is not on screen.

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
    center = STRIP_X1 + x + dx + marker.shape[1] / 2
    return (center - PROGRESS_START_X) / (PROGRESS_END_X - PROGRESS_START_X)


def fit_progress_slope(times: list[float], progresses: list[float]) -> float:
    """Least-squares slope of progress vs time (fraction of level per second)."""
    if len(times) < 10:
        raise ValueError(f"Too few progress samples to fit marker speed ({len(times)})")
    slope, _ = np.polyfit(times, progresses, 1)
    if slope <= 0:
        raise ValueError("Progress did not advance; cannot fit marker speed")
    return float(slope)


def load_levels(levels_dir: Path) -> dict[int, dict]:
    """Map of level number -> {'taps', 'p_freeze', 'slope'}."""
    levels = {}
    for path in sorted(Path(levels_dir).glob("level_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != TRACE_VERSION:
            raise ValueError(
                f"{path} is trace format v{data.get('version')}; this build needs "
                f"v{TRACE_VERSION}. Re-record it with scripts/record_levels.py."
            )
        levels[data["level"]] = {
            "taps": data["taps"],
            "p_freeze": data["p_freeze"],
            "slope": data["slope"],
        }
    return levels


class LevelReplayer:
    """Replays per-level tap traces via the same pause handshake as recording."""

    def __init__(
        self,
        device: AvdDevice,
        capture,  # WindowCapture; untyped so this module imports without it
        assets_dir: Path,
        levels_dir: Path,
        exit_template: Path,
    ):
        self._device = device
        self._capture = capture
        self._marker = load_marker(assets_dir)
        self._continue_template = continue_template(assets_dir)
        self._levels = load_levels(levels_dir)
        self._exit_template = exit_template
        if not self._levels:
            raise ValueError(f"No level recordings in {levels_dir}")

    def _tap(self, shell: subprocess.Popen, x: int, y: int, duration: float) -> None:
        # Small jitter; identical replays run after run look robotic.
        x += random.randint(-8, 8)
        y += random.randint(-8, 8)
        ms = max(30, round(duration * 1000 * random.uniform(0.95, 1.05)))
        assert shell.stdin is not None
        # '&' lets a long slide-hold overlap the next tap instead of queueing it.
        shell.stdin.write(f"input swipe {x} {y} {x} {y} {ms} &\n")
        shell.stdin.flush()

    def _play_trace(
        self,
        shell: subprocess.Popen,
        taps: list[dict],
        t0: float,
        stop: threading.Event,
    ) -> None:
        for tap in taps:
            delay = t0 + tap["t"] - time.perf_counter()
            if delay < -STALE_TAP_LIMIT:
                print(f"  skipped stale tap at t={tap['t']:.2f}s ({-delay:.2f}s late)")
                continue
            if delay > 0 and stop.wait(delay):
                return
            if stop.is_set():
                return
            self._tap(shell, tap["x"], tap["y"], tap["duration"])

    def _read_frozen_progress(self) -> float | None:
        """Average the (static) marker position over a few pause-menu frames."""
        readings = []
        for _ in range(FREEZE_SAMPLES):
            progress = read_progress(self._capture.grab(), self._marker)
            if progress is not None:
                readings.append(progress)
            time.sleep(0.05)
        return float(np.mean(readings)) if readings else None

    def _pause_and_continue(self) -> tuple[float | None, float]:
        """Pause, read the frozen marker, tap Continue; t0 = menu-gone frame.

        Mirrors the recorder exactly (same taps, same screen-event anchors),
        so latencies and any game side-effects of pausing cancel out.
        """
        p_freeze = None
        menu_up = False
        for _ in range(15):  # an intro animation can swallow the pause; retry
            self._device.tap(*PAUSE_XY)
            deadline = time.perf_counter() + 1.0
            while time.perf_counter() < deadline:
                frame = self._capture.grab()
                match = find_template(frame, self._continue_template, threshold=0.85)
                if match:
                    menu_up = True
                    break
                time.sleep(0.05)
            if menu_up:
                p_freeze = self._read_frozen_progress()
                self._device.tap(match.center_x, match.center_y)
                break
        if not menu_up:
            print("WARNING: pause menu never appeared; playing without the handshake.")
            return None, time.perf_counter()

        deadline = time.perf_counter() + 10.0
        while time.perf_counter() < deadline:
            frame = self._capture.grab()
            now = time.perf_counter()
            if not find_template(frame, self._continue_template, threshold=0.85):
                return p_freeze, now
            time.sleep(0.05)
        print("WARNING: never saw the pause menu close; timing may be off.")
        return p_freeze, time.perf_counter()

    def run(self, max_seconds: float = 1200.0) -> bool:
        """Replay levels until the result screen appears. False on timeout."""
        shell = subprocess.Popen(
            self._device.command("shell"), stdin=subprocess.PIPE, text=True, bufsize=1
        )
        deadline = time.perf_counter() + max_seconds
        level = min(self._levels)
        in_level = False
        max_progress = 0.0
        stable_low = 0
        frame_count = 0
        trace_stop = threading.Event()

        def start_level() -> None:
            nonlocal in_level, max_progress
            recorded = self._levels.get(level)
            p_freeze, t0 = self._pause_and_continue()
            if recorded is None:
                print(f"No recording for level {level}; watching only.")
            else:
                # Shift the schedule by how much further into the level this
                # freeze landed compared to the recording's freeze.
                offset = 0.0
                if (
                    p_freeze is not None
                    and recorded["slope"]
                    and p_freeze >= MOVING_MIN
                    and recorded["p_freeze"] >= MOVING_MIN
                ):
                    offset = (p_freeze - recorded["p_freeze"]) / recorded["slope"]
                print(
                    f"Level {level}: frozen at "
                    f"{'?' if p_freeze is None else f'{p_freeze:.1%}'} vs recorded "
                    f"{(recorded.get('p_freeze') or 0.0):.1%}; offset {offset:+.2f}s; "
                    f"replaying {len(recorded['taps'])} taps."
                )
                trace_stop.clear()
                threading.Thread(
                    target=self._play_trace,
                    args=(shell, recorded["taps"], t0 - offset, trace_stop),
                    daemon=True,
                ).start()
            in_level = True
            max_progress = 0.0

        try:
            while time.perf_counter() < deadline:
                frame = self._capture.grab()
                frame_count += 1
                time.sleep(0.02)

                if frame_count % 30 == 0 and find_template(frame, self._exit_template, threshold=0.85):
                    print("Result screen detected; replay finished.")
                    return True

                progress = read_progress(frame, self._marker)
                if progress is None:
                    continue

                if not in_level:
                    stable_low = stable_low + 1 if progress < LEVEL_START_MAX else 0
                    if stable_low >= 3:
                        stable_low = 0
                        start_level()
                    continue

                if max_progress > LEVEL_END_MIN and progress < LEVEL_START_MAX:
                    trace_stop.set()
                    print(f"Level {level} finished.")
                    level += 1
                    start_level()
                    continue

                max_progress = max(max_progress, progress)

            print("Level replay timed out without reaching the result screen.")
            return False
        finally:
            trace_stop.set()
            if shell.stdin:
                shell.stdin.close()
            try:
                shell.wait(timeout=2)
            except subprocess.TimeoutExpired:
                shell.terminate()
