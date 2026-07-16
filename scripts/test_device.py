import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avd_runner import AvdDevice
from avd_runner.device import parse_wm_size


class FakeStdin:
    def __init__(self):
        self.lines = []
        self.closed = False
        self.flushed = False

    def write(self, value: str) -> None:
        self.lines.append(value)

    def flush(self) -> None:
        self.flushed = True

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self):
        self.stdin = FakeStdin()
        self.waited = False
        self.terminated = False

    def wait(self, timeout=None) -> None:
        self.waited = True

    def terminate(self) -> None:
        self.terminated = True


gestures = []
device = AvdDevice(on_gesture=lambda *args: gestures.append(args))
process = FakeProcess()
device.open_input_shell = lambda: process

with device.input_shell() as shell:
    shell.swipe(1, 2, 3, 4, 55, background=True, label="jump")

assert process.stdin.lines == ["input swipe 1 2 3 4 55 &\n"]
assert process.stdin.flushed
assert process.stdin.closed
assert process.waited
assert not process.terminated
assert gestures == [(1, 2, 3, 4, 55, "jump")]
assert device.command("shell", "getevent", "-lt") == ["adb", "shell", "getevent", "-lt"]

# Vision stays in its calibrated 1280x720 coordinate space while input is
# mapped to the emulator's actual Android display size.
scaled_gestures = []
scaled_device = AvdDevice(
    device_size=(1280, 720),
    input_size=(960, 540),
    on_gesture=lambda *args: scaled_gestures.append(args),
)
scaled_inputs = []
scaled_device.input = lambda *args: scaled_inputs.append(args) or ""
scaled_device.swipe(953, 645, 956, 648, duration_ms=80, label="Play")
assert scaled_inputs == [("swipe", "715", "484", "717", "486", "80")]
assert scaled_gestures == [(953, 645, 956, 648, 80, "Play")]

scaled_process = FakeProcess()
scaled_device.open_input_shell = lambda: scaled_process
with scaled_device.input_shell() as shell:
    shell.swipe(953, 645, 956, 648, 80, label="Play")
assert scaled_process.stdin.lines == ["input swipe 715 484 717 486 80\n"]

assert parse_wm_size("Physical size: 960x540\n") == (960, 540)
assert parse_wm_size("Physical size: 1280x720\nOverride size: 960x540\n") == (960, 540)
assert parse_wm_size("unknown") is None

print("ok")
