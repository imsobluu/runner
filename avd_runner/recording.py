"""Touch-event utilities for reading the device's raw tap stream via ADB getevent.

Used by the per-level trace recorder to observe the player's real Android
touches while WGC handles visual progress detection.
"""
from __future__ import annotations

import re

from .device import AvdDevice


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


def touch_axis_ranges(
    device: AvdDevice,
    event_device: str,
) -> dict[str, tuple[int, int]]:
    output = device.adb("shell", "getevent", "-lp", event_device)
    ranges: dict[str, tuple[int, int]] = {}
    for line in output.splitlines():
        match = re.search(
            r"\b(ABS_MT_POSITION_[XY])\b.*?"
            r"\bmin\s+(-?\d+),\s+max\s+(-?\d+)",
            line,
        )
        if match:
            ranges[match.group(1)] = (int(match.group(2)), int(match.group(3)))
    return ranges


def scale_touch_axis(
    value: int,
    logical_size: int,
    axis_range: tuple[int, int] | None,
) -> int:
    if axis_range is not None:
        minimum, maximum = axis_range
        if maximum > minimum:
            value = round(
                (value - minimum) * (logical_size - 1) / (maximum - minimum)
            )
    return max(0, min(logical_size - 1, value))


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
        r"\b(ABS_MT_POSITION_X|ABS_MT_POSITION_Y|ABS_MT_TRACKING_ID|BTN_TOUCH)\s+"
        r"(DOWN|UP|[0-9a-fA-F]+)\b",
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
