import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avd_runner import none
from avd_runner.vision import TemplateMatch


class FakeCapture:
    def __init__(self):
        self.count = 0

    def grab(self):
        self.count += 1
        return f"frame-{self.count}"


class FakeShell:
    def __init__(self):
        self.swipes = []

    def swipe(self, *args, **kwargs):
        self.swipes.append((args, kwargs))


class FakeInputShell:
    def __init__(self, shell):
        self.shell = shell

    def __enter__(self):
        return self.shell

    def __exit__(self, *exc):
        return None


class FakeDevice:
    def __init__(self):
        self.shell = FakeShell()

    def input_shell(self):
        return FakeInputShell(self.shell)


capture = FakeCapture()
device = FakeDevice()
runner = none.NoneRunner(
    device,
    capture,
    exit_template=Path("result.png"),
    relay_template=Path("relay.png"),
)

original_check_every = none.CHECK_EVERY
original_find_template = none.find_template
original_sleep = none.time.sleep
try:
    none.CHECK_EVERY = 1
    none.time.sleep = lambda _seconds: None

    def fake_find_template(frame, template_path, threshold=0.85):
        if template_path == Path("relay.png") and frame == "frame-1":
            return TemplateMatch(x=10, y=20, width=8, height=8, score=0.99)
        if template_path == Path("result.png") and frame == "frame-2":
            return TemplateMatch(x=100, y=200, width=8, height=8, score=0.99)
        return None

    none.find_template = fake_find_template

    assert runner.run(max_seconds=1.0)
    assert capture.count == 2
    assert len(device.shell.swipes) == 1
    assert device.shell.swipes[0][1]["label"] == "relay"
finally:
    none.CHECK_EVERY = original_check_every
    none.find_template = original_find_template
    none.time.sleep = original_sleep

print("ok")
