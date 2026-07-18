import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avd_runner.recording import (
    _parse_getevent_line,
    find_touch_event_device,
    scale_touch_axis,
    touch_axis_ranges,
)


assert _parse_getevent_line(
    "[  123.456] /dev/input/event4: EV_ABS       ABS_MT_POSITION_X    0000012c"
) == ("ABS_MT_POSITION_X", 300)
assert _parse_getevent_line(
    "[  123.456] /dev/input/event4: EV_ABS       ABS_MT_TRACKING_ID  ffffffff"
) == ("ABS_MT_TRACKING_ID", -1)
assert _parse_getevent_line(
    "[  123.456] /dev/input/event4: EV_KEY       BTN_TOUCH           DOWN"
) == ("BTN_TOUCH", 1)
assert _parse_getevent_line("unrelated") is None


class FakeDevice:
    def adb(self, *args):
        assert args == ("shell", "getevent", "-pl")
        return """
add device 1: /dev/input/event0
  name: "keyboard"
add device 2: /dev/input/event4
  name: "touchscreen"
    ABS_MT_POSITION_X
    ABS_MT_POSITION_Y
"""


assert find_touch_event_device(FakeDevice()) == "/dev/input/event4"


class FakeAxisDevice:
    def adb(self, *args):
        assert args == (
            "shell",
            "getevent",
            "-lp",
            "/dev/input/event4",
        )
        return """
    ABS_MT_POSITION_X : value 0, min 0, max 1279, fuzz 0
    ABS_MT_POSITION_Y : value 0, min 100, max 32867, fuzz 0
"""


ranges = touch_axis_ranges(FakeAxisDevice(), "/dev/input/event4")
assert ranges == {
    "ABS_MT_POSITION_X": (0, 1279),
    "ABS_MT_POSITION_Y": (100, 32867),
}
assert scale_touch_axis(640, 1280, ranges["ABS_MT_POSITION_X"]) == 640
assert scale_touch_axis(100, 720, ranges["ABS_MT_POSITION_Y"]) == 0
assert scale_touch_axis(32867, 720, ranges["ABS_MT_POSITION_Y"]) == 719
assert scale_touch_axis(16484, 720, ranges["ABS_MT_POSITION_Y"]) == 360
assert scale_touch_axis(500, 720, None) == 500
assert scale_touch_axis(900, 720, None) == 719
assert scale_touch_axis(500, 720, (4, 4)) == 500

print("ok")
