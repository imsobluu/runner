from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .device import AvdDevice, wait


@dataclass(frozen=True)
class RecordedTap:
    x: int
    y: int
    delay: float
    duration: float = 0.05


def load_taps(path: str | Path) -> list[RecordedTap]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        RecordedTap(
            x=int(step["x"]),
            y=int(step["y"]),
            delay=float(step.get("delay", 0)),
            duration=float(step.get("duration", 0.05)),
        )
        for step in data["steps"]
        if step.get("type") == "tap"
    ]


def play_taps(
    device: AvdDevice,
    path: str | Path,
    speed: float = 1.0,
    stop_event: threading.Event | None = None,
) -> None:
    if speed <= 0:
        raise ValueError("speed must be greater than 0")

    _play_recorded_taps(device, load_taps(path), speed, stop_event=stop_event)


def play_ldplayer_record(
    device: AvdDevice,
    path: str | Path,
    speed: float = 1.0,
    stop_event: threading.Event | None = None,
) -> None:
    if speed <= 0:
        raise ValueError("speed must be greater than 0")

    taps = load_ldplayer_record(path, target_size=device.screen_size())
    _play_recorded_taps(device, taps, speed, stop_event=stop_event)


def load_ldplayer_record(
    path: str | Path,
    target_size: tuple[int, int] | None = None,
) -> list[RecordedTap]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    operations = data["operations"]
    record_info = data.get("recordInfo", {})
    source_width = int(record_info.get("resolutionWidth", 10000))
    source_height = int(record_info.get("resolutionHeight", 10000))
    target_width, target_height = target_size or (source_width, source_height)

    active_touches: dict[int, tuple[int, int, int]] = {}
    taps: list[RecordedTap] = []
    last_tap_time = 0

    for operation in operations:
        if operation.get("operationId") != "PutMultiTouch":
            continue

        timing_ms = int(operation["timing"])
        for point in operation.get("points", []):
            touch_id = int(point["id"])
            x = _scale_ldplayer_position(
                int(point["x"]),
                axis_size=source_width,
                other_axis_size=source_height,
                target_axis_size=target_width,
            )
            y = _scale_ldplayer_position(
                int(point["y"]),
                axis_size=source_height,
                other_axis_size=source_width,
                target_axis_size=target_height,
            )
            state = int(point["state"])

            if state == 1:
                active_touches[touch_id] = (timing_ms, x, y)
            elif state == 0 and touch_id in active_touches:
                down_timing_ms, down_x, down_y = active_touches.pop(touch_id)
                delay = max(0, down_timing_ms - last_tap_time) / 1000
                duration = max(1, timing_ms - down_timing_ms) / 1000
                taps.append(
                    RecordedTap(
                        x=round((down_x + x) / 2),
                        y=round((down_y + y) / 2),
                        delay=delay,
                        duration=duration,
                    )
                )
                last_tap_time = timing_ms

    return taps


def _play_recorded_taps(
    device: AvdDevice,
    taps: list[RecordedTap],
    speed: float,
    stop_event: threading.Event | None = None,
) -> None:
    process = subprocess.Popen(
        device.command("shell"),
        stdin=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        assert process.stdin is not None
        for tap in taps:
            if _wait_for_playback(tap.delay / speed, stop_event):
                break
            duration_ms = max(1, int((tap.duration / speed) * 1000))
            process.stdin.write(
                f"input swipe {tap.x} {tap.y} {tap.x} {tap.y} {duration_ms}\n"
            )
            process.stdin.flush()
            if _wait_for_playback(tap.duration / speed, stop_event):
                break
            print(f"Tapped {tap.x}, {tap.y} for {duration_ms}ms")
    finally:
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()


def _wait_for_playback(seconds: float, stop_event: threading.Event | None) -> bool:
    if seconds <= 0:
        return stop_event.is_set() if stop_event else False
    if stop_event is None:
        wait(seconds)
        return False
    return stop_event.wait(seconds)


def save_taps(path: str | Path, taps: list[RecordedTap], screen_size: tuple[int, int]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "version": 1,
        "screen_size": {"width": screen_size[0], "height": screen_size[1]},
        "steps": [
            {
                "type": "tap",
                "x": tap.x,
                "y": tap.y,
                "delay": round(tap.delay, 3),
                "duration": round(tap.duration, 3),
            }
            for tap in taps
        ],
    }
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record_taps(
    device: AvdDevice,
    output_path: str | Path,
    duration_seconds: float | None = None,
    max_taps: int | None = None,
    event_device: str | None = None,
    max_tap_move: int = 30,
) -> list[RecordedTap]:
    screen_size = device.screen_size()
    event_device = event_device or find_touch_event_device(device)
    command = device.command("shell", "getevent", "-lt")
    if event_device:
        command.append(event_device)

    print("Recording taps. Press Ctrl+C to stop.")
    if event_device:
        print(f"Using touch input: {event_device}")

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    taps: list[RecordedTap] = []
    latest_x: int | None = None
    latest_y: int | None = None
    down_x: int | None = None
    down_y: int | None = None
    down_time: float | None = None
    last_tap_time = time.monotonic()
    started_at = time.monotonic()

    lines: queue.Queue[str | None] = queue.Queue()

    def read_lines() -> None:
        assert process.stdout is not None
        for output_line in process.stdout:
            lines.put(output_line)
        lines.put(None)

    reader = threading.Thread(target=read_lines, daemon=True)
    reader.start()

    try:
        while True:
            now = time.monotonic()
            if duration_seconds is not None and now - started_at >= duration_seconds:
                break

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
                latest_x = _scale_position(value, screen_size[0])
            elif name == "ABS_MT_POSITION_Y":
                latest_y = _scale_position(value, screen_size[1])
            elif name in {"BTN_TOUCH", "ABS_MT_TRACKING_ID"}:
                if name == "BTN_TOUCH" and value != 0:
                    down_x = latest_x
                    down_y = latest_y
                    down_time = now
                elif name == "ABS_MT_TRACKING_ID" and value != -1:
                    down_x = latest_x
                    down_y = latest_y
                    down_time = now
                elif latest_x is not None and latest_y is not None:
                    if _looks_like_tap(down_x, down_y, latest_x, latest_y, max_tap_move):
                        press_started_at = down_time or now
                        delay = press_started_at - last_tap_time
                        duration = now - press_started_at
                        tap = RecordedTap(
                            x=latest_x,
                            y=latest_y,
                            delay=max(0, delay),
                            duration=max(0, duration),
                        )
                        taps.append(tap)
                        last_tap_time = now
                        print(
                            f"Recorded tap {len(taps)}: {tap.x}, {tap.y} "
                            f"duration={tap.duration:.3f}s"
                        )
                        save_taps(output_path, taps, screen_size)

                    down_x = None
                    down_y = None
                    down_time = None
                    if max_taps is not None and len(taps) >= max_taps:
                        break
    except KeyboardInterrupt:
        pass
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()

    save_taps(output_path, taps, screen_size)
    print(f"Saved {len(taps)} tap(s) to {output_path}")
    return taps


def find_touch_event_device(device: AvdDevice) -> str | None:
    output = device.adb("shell", "getevent", "-pl")
    current_device: str | None = None
    current_block: list[str] = []

    for line in output.splitlines():
        match = re.search(r"add device \d+:\s+(.+)", line)
        if match:
            found = _touch_device_from_block(current_device, current_block)
            if found:
                return found
            current_device = match.group(1).strip()
            current_block = []
        else:
            current_block.append(line)

    return _touch_device_from_block(current_device, current_block)


def _touch_device_from_block(device_path: str | None, block: list[str]) -> str | None:
    if not device_path:
        return None
    text = "\n".join(block)
    if "ABS_MT_POSITION_X" in text and "ABS_MT_POSITION_Y" in text:
        return device_path
    return None


def _parse_getevent_line(line: str) -> tuple[str, int] | None:
    # getevent -l prints EV_KEY values as DOWN/UP labels and ABS values as hex.
    match = re.search(
        r"\b(ABS_MT_POSITION_X|ABS_MT_POSITION_Y|ABS_MT_TRACKING_ID|BTN_TOUCH)\s+(DOWN|UP|[0-9a-fA-F]+)\b",
        line,
    )
    if not match:
        return None

    value_text = match.group(2)
    if value_text == "DOWN":
        value = 1
    elif value_text == "UP":
        value = 0
    else:
        value = int(value_text, 16)
        if value_text.lower() in {"ffffffff", "ffffffffffffffff"}:
            value = -1
    return match.group(1), value


def _scale_position(value: int, axis_size: int) -> int:
    # Emulators report ABS_MT_POSITION_* in screen pixels, so clamping is
    # enough. Real devices often use a different raw range and would need
    # proportional scaling from the ranges in `getevent -p`.
    return max(0, min(axis_size - 1, value))


def _scale_ldplayer_position(
    value: int,
    axis_size: int,
    other_axis_size: int,
    target_axis_size: int,
) -> int:
    normalized_axis_size = 10000 * max(1, axis_size / other_axis_size)
    scaled = round(value / normalized_axis_size * target_axis_size)
    return max(0, min(target_axis_size - 1, scaled))


def _looks_like_tap(
    down_x: int | None,
    down_y: int | None,
    up_x: int,
    up_y: int,
    max_tap_move: int,
) -> bool:
    if down_x is None or down_y is None:
        return True
    return abs(up_x - down_x) <= max_tap_move and abs(up_y - down_y) <= max_tap_move
