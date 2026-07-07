"""Record gameplay taps per level from WGC progress + real mouse clicks."""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from avd_runner.capture import WindowCapture, _window_rect
from avd_runner.device import DEFAULT_DEVICE_SIZE
from avd_runner.levels import (
    LEVEL_END_MIN,
    LEVEL_START_MAX,
    TRACE_VERSION,
    load_marker,
    read_progress,
)

PROGRESS_SAMPLE_MAX_GAP = 0.25
POLL_INTERVAL = 0.01
STABLE_LOW_FRAMES = 3
VK_LBUTTON = 0x01

_user32 = ctypes.windll.user32


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def cursor_position() -> tuple[int, int]:
    point = POINT()
    _user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def left_button_down() -> bool:
    return bool(_user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)


def device_point_from_cursor(capture: WindowCapture, x: int, y: int) -> tuple[int, int] | None:
    """Map a Windows cursor position to emulator device coordinates."""
    ren_left, ren_top, ren_right, ren_bottom = _window_rect(capture._render_hwnd)
    if not (ren_left <= x < ren_right and ren_top <= y < ren_bottom):
        return None

    device_width, device_height = capture._device_size or (
        ren_right - ren_left,
        ren_bottom - ren_top,
    )
    dx = round((x - ren_left) * device_width / max(1, ren_right - ren_left))
    dy = round((y - ren_top) * device_height / max(1, ren_bottom - ren_top))
    return dx, dy


def progress_at_time(
    samples: list[tuple[float, float]], tap_time: float
) -> float | None:
    """Interpolate marker progress at a tap, rejecting stale observations."""
    before = next((sample for sample in reversed(samples) if sample[0] <= tap_time), None)
    after = next((sample for sample in samples if sample[0] >= tap_time), None)
    if before is None or after is None:
        nearest = before or after
        if nearest is None or abs(nearest[0] - tap_time) > PROGRESS_SAMPLE_MAX_GAP:
            return None
        return nearest[1]
    if after[0] == before[0]:
        return before[1]
    if (
        tap_time - before[0] > PROGRESS_SAMPLE_MAX_GAP
        or after[0] - tap_time > PROGRESS_SAMPLE_MAX_GAP
    ):
        return None
    fraction = (tap_time - before[0]) / (after[0] - before[0])
    return before[1] + fraction * (after[1] - before[1])


def save_level(
    episode_dir: Path,
    level: int,
    t0: float,
    taps: list[dict],
    samples: list[tuple[float, float]],
    until: float,
) -> None:
    """Save taps keyed to interpolated progress at finger-down time."""
    level_samples = [(t, p) for t, p in samples if t0 <= t <= until]

    steps = []
    for tap in taps:
        if not (t0 < tap["t"] <= until):
            continue
        progress = progress_at_time(level_samples, tap["t"])
        steps.append({
            "t": round(tap["t"] - t0, 3),
            "progress": None if progress is None else round(progress, 5),
            "x": tap["x"],
            "y": tap["y"],
            "duration": round(tap["duration"], 3),
        })
    episode_dir.mkdir(parents=True, exist_ok=True)
    path = episode_dir / f"level_{level:02d}.json"
    path.write_text(
        json.dumps(
            {
                "version": TRACE_VERSION,
                "level": level,
                "taps": steps,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Saved level {level}: {len(steps)} taps -> {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Record gameplay taps per level.")
    parser.add_argument(
        "--episode",
        required=True,
        help="Episode id; becomes the folder under recordings/levels/.",
    )
    parser.add_argument("--level", type=int, default=1, help="Number of the first level that will start.")
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "recordings" / "levels",
        help="Root output directory.",
    )
    args = parser.parse_args()

    episode_dir = args.out / args.episode
    marker = load_marker(REPO_ROOT / "assets")
    capture = WindowCapture(device_size=DEFAULT_DEVICE_SIZE)

    level = args.level
    level_t0: float | None = None
    in_level = False
    stable_low = 0
    max_progress = 0.0
    taps: list[dict] = []
    samples: list[tuple[float, float]] = []
    active_tap: dict | None = None
    was_down = left_button_down()

    print("Recording. Click/play manually in LDPlayer. Press Ctrl+C to stop.")
    print(f"Output -> {episode_dir}")

    try:
        while True:
            now = time.perf_counter()
            frame = capture.grab()
            progress = read_progress(frame, marker)
            if progress is not None:
                samples.append((now, progress))

            is_down = left_button_down()
            if is_down and not was_down:
                point = device_point_from_cursor(capture, *cursor_position())
                if point is not None:
                    active_tap = {"t": now, "x": point[0], "y": point[1]}
            elif not is_down and was_down and active_tap is not None:
                active_tap["duration"] = max(0.0, now - active_tap["t"])
                taps.append(active_tap)
                active_tap = None
            was_down = is_down

            if progress is not None:
                if not in_level:
                    stable_low = stable_low + 1 if progress < LEVEL_START_MAX else 0
                    if stable_low >= STABLE_LOW_FRAMES:
                        level_t0 = now
                        in_level = True
                        max_progress = 0.0
                        stable_low = 0
                        print(f"Level {level} recording started.")
                else:
                    max_progress = max(max_progress, progress)
                    if max_progress > LEVEL_END_MIN and progress < LEVEL_START_MAX:
                        assert level_t0 is not None
                        save_level(episode_dir, level, level_t0, taps, samples, now)
                        level += 1
                        level_t0 = now
                        max_progress = 0.0
                        print(f"Level {level} recording started.")

            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        now = time.perf_counter()
        if in_level and level_t0 is not None:
            save_level(episode_dir, level, level_t0, taps, samples, now)
        print("Stopped recording.")
    finally:
        capture.close()


if __name__ == "__main__":
    main()
