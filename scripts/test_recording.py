import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avd_runner.recording import _parse_getevent_line, find_touch_event_device


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

print("ok")
