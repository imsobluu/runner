import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avd_runner import AvdDevice


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

print("ok")
