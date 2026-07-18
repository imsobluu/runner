"""Record gameplay taps per level from WGC progress + Android touch events."""
from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from avd_runner.capture import WindowCapture
from avd_runner.device import AvdDevice
from avd_runner.levels import (
    LEVEL_END_MIN,
    LEVEL_START_MAX,
    ProgressTracker,
    TRACE_VERSION,
    locate_marker_with_details,
    load_marker,
)
from avd_runner.recording import (
    _parse_getevent_line,
    find_touch_event_device,
    scale_touch_axis,
    touch_axis_ranges,
)

PROGRESS_SAMPLE_MAX_GAP = 0.25
PROGRESS_ESTIMATE_MAX_GAP = 1.5
PROGRESS_EXTRAPOLATE_MAX_GAP = 0.5
POLL_INTERVAL = 0.01
STABLE_LOW_FRAMES = 3
LEVEL_END_LOW_FRAMES = 8
MIN_LEVEL_SECONDS = 15.0


def level_dir_name(level: int) -> str:
    return f"level_{level:02d}"


def next_level_recording_path(episode_dir: Path, level: int) -> Path:
    level_name = level_dir_name(level)
    level_dir = episode_dir / "levels" / level_name
    existing = sorted(level_dir.glob(f"{level_name}_*.json")) if level_dir.exists() else []
    max_index = 0
    for path in existing:
        suffix = path.stem.removeprefix(f"{level_name}_")
        if suffix.isdigit():
            max_index = max(max_index, int(suffix))
    return level_dir / f"{level_name}_{max_index + 1:03d}.json"


def level_end_detected(
    max_progress: float,
    progress: float,
    elapsed: float,
    stable_low: int,
) -> tuple[bool, int]:
    if (
        max_progress <= LEVEL_END_MIN
        or elapsed < MIN_LEVEL_SECONDS
        or progress >= LEVEL_START_MAX
    ):
        return False, 0
    stable_low += 1
    return stable_low >= LEVEL_END_LOW_FRAMES, stable_low


def watch_taps(
    device: AvdDevice,
    taps: list[dict],
    stop: threading.Event,
) -> None:
    """Append {'t', 'x', 'y', 'duration'} for every Android touch release."""
    width, height = device.screen_size()
    command = device.command("shell", "getevent", "-lt")
    event_device = find_touch_event_device(device)
    if event_device:
        command.append(event_device)
        print(f"Using touch input: {event_device}")
    else:
        print("Using all getevent devices; no dedicated touch device was detected.")
    axis_ranges = (
        touch_axis_ranges(device, event_device)
        if event_device is not None
        else {}
    )

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    lines: queue.Queue[str | None] = queue.Queue()

    def read_lines() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read_lines, daemon=True).start()

    latest_x: int | None = None
    latest_y: int | None = None
    down_time: float | None = None
    while not stop.is_set():
        try:
            line = lines.get(timeout=0.1)
        except queue.Empty:
            continue
        if line is None:
            break
        event = _parse_getevent_line(line)
        if event is None:
            continue

        name, value = event
        if name == "ABS_MT_POSITION_X":
            latest_x = scale_touch_axis(
                value,
                width,
                axis_ranges.get("ABS_MT_POSITION_X"),
            )
        elif name == "ABS_MT_POSITION_Y":
            latest_y = scale_touch_axis(
                value,
                height,
                axis_ranges.get("ABS_MT_POSITION_Y"),
            )
        elif name in ("BTN_TOUCH", "ABS_MT_TRACKING_ID"):
            pressed = (name == "BTN_TOUCH" and value != 0) or (
                name == "ABS_MT_TRACKING_ID" and value != -1
            )
            now = time.perf_counter()
            if pressed:
                down_time = now
            elif down_time is not None and latest_x is not None and latest_y is not None:
                taps.append(
                    {
                        "t": down_time,
                        "x": latest_x,
                        "y": latest_y,
                        "duration": now - down_time,
                    }
                )
                down_time = None

    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()


def progress_at_time(
    samples: list[tuple[float, float]], tap_time: float
) -> float | None:
    """Estimate marker progress at a tap, rejecting stale/ambiguous observations."""
    before = next((sample for sample in reversed(samples) if sample[0] <= tap_time), None)
    after = next((sample for sample in samples if sample[0] >= tap_time), None)
    if before is None or after is None:
        nearest = before or after
        if nearest is None:
            return None
        if abs(nearest[0] - tap_time) <= PROGRESS_SAMPLE_MAX_GAP:
            return nearest[1]
        return _extrapolated_progress(samples, tap_time)
    if after[0] == before[0]:
        return before[1]
    if (
        tap_time - before[0] > PROGRESS_SAMPLE_MAX_GAP
        or after[0] - tap_time > PROGRESS_SAMPLE_MAX_GAP
    ):
        if after[0] - before[0] > PROGRESS_ESTIMATE_MAX_GAP or after[1] < before[1]:
            return None
    fraction = (tap_time - before[0]) / (after[0] - before[0])
    return before[1] + fraction * (after[1] - before[1])


def _extrapolated_progress(
    samples: list[tuple[float, float]], tap_time: float
) -> float | None:
    if len(samples) < 2:
        return None
    if tap_time > samples[-1][0]:
        first, second = samples[-2], samples[-1]
    elif tap_time < samples[0][0]:
        first, second = samples[0], samples[1]
    else:
        return None

    if second[0] == first[0]:
        return None
    if abs(tap_time - second[0]) > PROGRESS_EXTRAPOLATE_MAX_GAP:
        return None
    if second[0] - first[0] > PROGRESS_ESTIMATE_MAX_GAP or second[1] < first[1]:
        return None

    slope = (second[1] - first[1]) / (second[0] - first[0])
    estimate = second[1] + slope * (tap_time - second[0])
    if estimate < 0.0 or estimate > 1.0:
        return None
    return estimate


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
    null_progress = 0
    for tap in taps:
        if not (t0 < tap["t"] <= until):
            continue
        progress = progress_at_time(level_samples, tap["t"])
        if progress is None:
            null_progress += 1
        steps.append({
            "t": round(tap["t"] - t0, 3),
            "progress": None if progress is None else round(progress, 5),
            "x": tap["x"],
            "y": tap["y"],
            "duration": round(tap["duration"], 3),
        })
    path = next_level_recording_path(episode_dir, level)
    path.parent.mkdir(parents=True, exist_ok=True)
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
    detail = f", {null_progress} without progress" if null_progress else ""
    print(f"Saved level {level}: {len(steps)} taps{detail} -> {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Record gameplay taps per level.")
    parser.add_argument(
        "--episode",
        required=True,
        help="Episode id; becomes the folder under recordings/episodes/.",
    )
    parser.add_argument("--level", type=int, default=1, help="Number of the first level that will start.")
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "recordings" / "episodes",
        help="Root output directory.",
    )
    args = parser.parse_args()

    episode_dir = args.out / args.episode
    marker = load_marker(REPO_ROOT / "assets")
    device = AvdDevice.from_env()
    capture = WindowCapture(device_size=device.screen_size())
    tracker = ProgressTracker()

    level = args.level
    level_t0: float | None = None
    in_level = False
    stable_low = 0
    max_progress = 0.0
    taps: list[dict] = []
    samples: list[tuple[float, float]] = []
    stop = threading.Event()
    tap_thread = threading.Thread(target=watch_taps, args=(device, taps, stop), daemon=True)
    tap_thread.start()

    print("Recording. Play manually in LDPlayer. Press Ctrl+C to stop.")
    print(f"Output -> {episode_dir}")

    try:
        while True:
            now = time.perf_counter()
            frame = capture.grab()
            detection = locate_marker_with_details(frame, marker)
            tracked = tracker.update(
                now,
                detection.progress if detection is not None else None,
            )
            progress = tracked.progress
            if progress is not None:
                samples.append((now, progress))

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
                    assert level_t0 is not None
                    ended, stable_low = level_end_detected(
                        max_progress,
                        progress,
                        now - level_t0,
                        stable_low,
                    )
                    if ended:
                        assert level_t0 is not None
                        save_level(episode_dir, level, level_t0, taps, samples, now)
                        level += 1
                        level_t0 = now
                        max_progress = 0.0
                        stable_low = 0
                        print(f"Level {level} recording started.")

            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        now = time.perf_counter()
        if in_level and level_t0 is not None:
            save_level(episode_dir, level, level_t0, taps, samples, now)
        print("Stopped recording.")
    finally:
        stop.set()
        tap_thread.join(timeout=2)
        capture.close()


if __name__ == "__main__":
    main()
