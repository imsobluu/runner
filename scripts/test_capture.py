import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avd_runner.capture import CaptureError, WindowCapture


class FakeControl:
    def __init__(self):
        self.stop_count = 0

    def stop(self):
        self.stop_count += 1


capture = object.__new__(WindowCapture)
capture._closed = False
capture._control = FakeControl()

capture.close()
capture.close()
assert capture._closed
assert capture._control.stop_count == 1

try:
    capture.grab()
except CaptureError as exc:
    assert "closed" in str(exc)
else:
    raise AssertionError("closed capture should reject grab()")

capture = object.__new__(WindowCapture)
capture._closed = False
capture._control = FakeControl()
assert capture.__enter__() is capture
capture.__exit__(None, None, None)
assert capture._control.stop_count == 1

print("ok")
