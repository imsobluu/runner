"""Record gameplay taps per level, anchored by the symmetric pause handshake.

The game is organized into episodes, each made of several levels. At each
level start this tool:

  1. taps the in-game pause button and beeps (retrying if an intro
     animation swallows the pause),
  2. reads the frozen progress-bar marker position (it stays readable
     behind the pause menu) - the replayer uses it to correct for the
     freeze landing at a slightly different point into the level,
  3. asks in the console whether to record this level,
  4. tells you to tap the game's Continue button; t=0 for the level is the
     frame where the pause menu disappears (the replayer anchors on the
     same screen event, so the handshake is symmetric and its latencies
     cancel),
  5. records your taps until the marker resets (level done) or the result
     screen appears (run over).

Recordings land in recordings/levels/<episode>/level_NN.json (format v4).
Boundary and pause-menu screenshots are kept in captures/ for reference.

    python -u scripts/record_levels.py --episode ep01
"""
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

import cv2
import numpy as np

from avd_runner import AvdDevice, find_template
from avd_runner.capture import WindowCapture
from avd_runner.levels import (
    FREEZE_SAMPLES,
    LEVEL_END_MIN,
    LEVEL_START_MAX,
    MOVING_MAX,
    MOVING_MIN,
    PAUSE_XY,
    TRACE_VERSION,
    continue_template,
    fit_progress_slope,
    load_marker,
    read_progress,
)
from avd_runner.recording import _parse_getevent_line, find_touch_event_device

ASSETS = REPO_ROOT / "assets"
RESULT_OK_TEMPLATE = ASSETS / "result_ok_button.png"
LEVELS_DIR = REPO_ROOT / "recordings" / "levels"

# The marker speed for freeze compensation is measured just past the freeze
# point; a short window avoids assuming the whole level runs at one speed.
SLOPE_WINDOW = 0.10


def beep() -> None:
    try:
        import winsound

        winsound.Beep(1200, 350)
    except Exception:
        print("\a", end="", flush=True)


def watch_taps(device: AvdDevice, screen_size, taps: list, stop: threading.Event) -> None:
    """Append {'t', 'x', 'y', 'duration'} for every physical tap (t = finger down)."""
    width, height = screen_size
    command = device.command("shell", "getevent", "-lt")
    event_device = find_touch_event_device(device)
    if event_device:
        command.append(event_device)
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1
    )
    lines: queue.Queue[str | None] = queue.Queue()

    def read_lines() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read_lines, daemon=True).start()

    latest_x = latest_y = None
    down_time = None
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
            latest_x = max(0, min(width - 1, value))
        elif name == "ABS_MT_POSITION_Y":
            latest_y = max(0, min(height - 1, value))
        elif name in ("BTN_TOUCH", "ABS_MT_TRACKING_ID"):
            pressed = (name == "BTN_TOUCH" and value != 0) or (
                name == "ABS_MT_TRACKING_ID" and value != -1
            )
            now = time.perf_counter()
            if pressed:
                down_time = now
            elif down_time is not None and latest_x is not None and latest_y is not None:
                taps.append(
                    {"t": down_time, "x": latest_x, "y": latest_y, "duration": now - down_time}
                )
                down_time = None
    process.terminate()


def save_level(
    episode_dir: Path,
    level: int,
    t0: float,
    p_freeze: float | None,
    taps: list[dict],
    samples: list[tuple[float, float]],
    until: float,
) -> None:
    """Save the level's taps (relative to t0) plus the freeze-compensation data."""
    # Marker speed just past the freeze point, from post-resume samples.
    slope = None
    window_lo = max(MOVING_MIN, p_freeze if p_freeze is not None else 0.0)
    window_hi = min(MOVING_MAX, window_lo + SLOPE_WINDOW)
    slope_samples = [
        (t, p) for t, p in samples if t > t0 and window_lo <= p <= window_hi
    ]
    try:
        slope = fit_progress_slope(
            [t for t, _ in slope_samples], [p for _, p in slope_samples]
        )
    except ValueError as exc:
        print(f"NOTE: no marker speed for level {level} ({exc}); "
              "replay will skip freeze compensation.")

    steps = [
        {
            "t": round(tap["t"] - t0, 3),
            "x": tap["x"],
            "y": tap["y"],
            "duration": round(tap["duration"], 3),
        }
        for tap in taps
        if t0 < tap["t"] <= until
    ]
    episode_dir.mkdir(parents=True, exist_ok=True)
    path = episode_dir / f"level_{level:02d}.json"
    path.write_text(
        json.dumps(
            {
                "version": TRACE_VERSION,
                "level": level,
                "p_freeze": None if p_freeze is None else round(p_freeze, 5),
                "slope": None if slope is None else round(slope, 6),
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
        help="Episode id; becomes the folder under recordings/levels/. Prompted if omitted.",
    )
    parser.add_argument("--level", type=int, default=1, help="Number of the first level that will start.")
    args = parser.parse_args()

    episode = args.episode or input("Episode id (e.g. ep01): ").strip()
    if not episode:
        raise SystemExit("An episode id is required.")
    episode_dir = LEVELS_DIR / episode
    existing = sorted(p.name for p in episode_dir.glob("level_*.json"))
    if existing:
        print(f"Episode {episode!r} already has {len(existing)} recorded level(s); "
              "recording a level again overwrites it.")

    marker = load_marker(ASSETS)
    continue_tmpl = continue_template(ASSETS)
    device = AvdDevice.from_env()
    screen_size = device.screen_size()
    capture = WindowCapture(device_size=screen_size)
    session_dir = REPO_ROOT / "captures" / time.strftime(f"levels_{episode}_%Y%m%d_%H%M%S")
    session_dir.mkdir(parents=True, exist_ok=True)

    taps: list[dict] = []
    stop = threading.Event()
    threading.Thread(
        target=watch_taps, args=(device, screen_size, taps, stop), daemon=True
    ).start()

    level = args.level
    state = "wait_start"  # wait_start -> (recording | watching) per level
    t0 = 0.0
    p_freeze: float | None = None
    samples: list[tuple[float, float]] = []
    max_progress = 0.0
    stable_low = 0
    frame_count = 0

    def read_frozen_progress() -> float | None:
        readings = []
        for _ in range(FREEZE_SAMPLES):
            progress = read_progress(capture.grab(), marker)
            if progress is not None:
                readings.append(progress)
            time.sleep(0.05)
        return float(np.mean(readings)) if readings else None

    def wait_for_continue(visible: bool, timeout: float) -> float | None:
        """Wall time when the Continue button's visibility becomes `visible`."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            frame = capture.grab()
            now = time.perf_counter()
            if bool(find_template(frame, continue_tmpl, threshold=0.85)) == visible:
                return now
            time.sleep(0.05)
        return None

    def confirm_level(frame) -> str:
        """Pause, read the frozen marker, ask, wait for un-pause (t0)."""
        nonlocal t0, p_freeze, max_progress
        cv2.imwrite(str(session_dir / f"boundary_{level:02d}.png"), frame)
        menu_up = None
        for _ in range(15):  # an intro animation can swallow the pause; retry
            device.tap(*PAUSE_XY)
            menu_up = wait_for_continue(visible=True, timeout=1.0)
            if menu_up is not None:
                break
        if menu_up is None:
            print("WARNING: pause menu never appeared; recording this level anyway.")
            p_freeze = None
        else:
            p_freeze = read_frozen_progress()
        cv2.imwrite(str(session_dir / f"pause_menu_{level:02d}.png"), capture.grab())
        beep()
        answer = input(
            f"\nLevel {level} start detected (game paused"
            f"{'' if p_freeze is None else f' at {p_freeze:.1%}'}). "
            f"Record it? [Enter]=yes  s=skip (play it unrecorded)  q=quit: "
        ).strip().lower()
        if answer == "q":
            return "quit"
        print("Now tap the game's Continue button to resume.")
        resumed = wait_for_continue(visible=False, timeout=120.0)
        if resumed is None:
            print("WARNING: never saw the pause menu close; this level's timing may be off.")
            resumed = time.perf_counter()
        t0 = resumed
        max_progress = 0.0
        samples.clear()
        next_state = "watching" if answer == "s" else "recording"
        print(f"Resumed; {next_state} level {level}.")
        return next_state

    print("Watching for the level progress bar. Start the run whenever you like; Ctrl+C to stop.")
    try:
        while True:
            frame = capture.grab()
            now = time.perf_counter()
            frame_count += 1
            progress = read_progress(frame, marker)
            time.sleep(0.02)

            if progress is None:
                continue  # menus/cutscene/transition: marker not on screen

            if state == "wait_start":
                # First level: marker appears near the left edge.
                stable_low = stable_low + 1 if progress < LEVEL_START_MAX else 0
                if stable_low >= 3:
                    stable_low = 0
                    state = confirm_level(frame)
                    if state == "quit":
                        break
                continue

            # In a level: it ends when the marker snaps back to the start.
            if max_progress > LEVEL_END_MIN and progress < LEVEL_START_MAX:
                if state == "recording":
                    save_level(episode_dir, level, t0, p_freeze, taps, samples,
                               until=time.perf_counter())
                level += 1
                state = confirm_level(frame)
                if state == "quit":
                    break
                continue

            samples.append((now, progress))
            max_progress = max(max_progress, progress)

            # The run can end mid-level (death) or after the final level.
            if frame_count % 30 == 0 and find_template(frame, RESULT_OK_TEMPLATE, threshold=0.85):
                if state == "recording":
                    if max_progress > LEVEL_END_MIN:
                        save_level(episode_dir, level, t0, p_freeze, taps, samples,
                                   until=time.perf_counter())
                    else:
                        print(
                            f"Run ended at {max_progress:.0%} of level {level}; "
                            "recording discarded. Re-run and skip earlier levels to retry it."
                        )
                print("Result screen reached; session done.")
                break
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        stop.set()
        capture.close()
        print(f"Session artifacts in {session_dir}")


if __name__ == "__main__":
    main()
