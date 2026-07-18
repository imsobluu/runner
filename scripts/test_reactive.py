import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import cv2
import numpy as np

from avd_runner import reactive
from avd_runner.reactive import ReactiveRunner, detect_obstacle, load_obstacles
from avd_runner.vision import TemplateMatch


assert "fast_start_template" in inspect.signature(ReactiveRunner).parameters


class FakeCapture:
    def __init__(self):
        self.count = 0

    def grab(self):
        self.count += 1
        return np.zeros((720, 1280, 3), dtype=np.uint8)


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


class FakeDebugView:
    def __init__(self):
        self.updates = []

    def update(self, frame, boxes):
        self.updates.append((frame, boxes))

obstacles = load_obstacles(REPO_ROOT / "assets" / "witch_oven")
assert {(o.name, o.action) for o in obstacles} == {
    ("fork", "slide"),
    ("ham_fork", "slide"),
    ("ground_spike", "jump"),
}

# Real-frame checks against a recorded burst (skipped if not present locally).
captures = REPO_ROOT / "captures" / "probe1"
if captures.exists():
    for frame_name, expected in [
        ("frame_00226.jpg", "slide"),  # hanging fork
        ("frame_00294.jpg", "jump"),   # ground spike
        ("frame_00118.jpg", None),     # jellies only: no action
        ("frame_00082.jpg", None),     # coin/bear wall: no action
    ]:
        frame = cv2.imread(str(captures / frame_name))
        obstacle, score, box = detect_obstacle(frame, obstacles)
        got = obstacle.action if obstacle else None
        assert got == expected, f"{frame_name}: expected {expected}, got {got} (score={score:.2f})"
        # A detection must report a box; a non-detection must not.
        assert (box is not None) == (obstacle is not None)
        if box is not None:
            assert box[0] < box[2] and box[1] < box[3]
else:
    print("captures/probe1 missing; skipped real-frame checks")

# Helper seams: obstacle dispatch respects cooldown and debug output includes
# the lookahead box plus a detection box when present.
helper = object.__new__(ReactiveRunner)
helper._debug_view = FakeDebugView()
helper._tap = lambda shell, x, y, hold_ms, label: shell.swipes.append((x, y, hold_ms, label))
state = reactive.ReactiveState()
shell = FakeShell()
obstacle = reactive.Obstacle("fake", "slide", np.zeros((4, 4, 3), dtype=np.uint8))
helper._handle_obstacle(state, shell, obstacle, 0.91, now=1.0)
assert shell.swipes == [(*reactive.SLIDE_XY, reactive.HOLD_MS["slide"], "slide")]
assert state.cooldown_until == 1.0 + reactive.ACTION_COOLDOWN
helper._handle_obstacle(state, shell, obstacle, 0.91, now=1.1)
assert len(shell.swipes) == 1

original_sleep = reactive.time.sleep
try:
    reactive.time.sleep = lambda _seconds: None
    state = reactive.ReactiveState()
    shell = FakeShell()
    obstacle = reactive.Obstacle("fake_jp2A", "jump", np.zeros((4, 4, 3), dtype=np.uint8))
    helper._handle_obstacle(state, shell, obstacle, 0.91, now=2.0)
    assert shell.swipes == [
        (*reactive.JUMP_XY, reactive.HOLD_MS["jump"], "jump"),
        (*reactive.JUMP_XY, reactive.HOLD_MS["jump"], "double_jump"),
    ]
finally:
    reactive.time.sleep = original_sleep

obstacle = reactive.Obstacle("fake", "slide", np.zeros((4, 4, 3), dtype=np.uint8))
helper._update_debug_view("frame", obstacle, 0.91, (1, 2, 3, 4))
assert helper._debug_view.updates == [
    (
        "frame",
        [
            (reactive.LOOK_X1, reactive.LOOK_Y1, reactive.LOOK_X2, reactive.LOOK_Y2, "lookahead", (0, 255, 0)),
            (reactive.ACTION_TRIGGER_X - 2, reactive.LOOK_Y1, reactive.ACTION_TRIGGER_X + 2, reactive.LOOK_Y2, "trigger", (255, 255, 0)),
            (1, 2, 3, 4, "fake 0.91 s=1.00", (0, 0, 255)),
        ],
    )
]

helper._exit_template = Path("result.png")
helper._relay_template = Path("relay.png")
helper._fast_start_template = Path("fast-start.png")
helper._fast_start_handled = False
helper._tap = lambda shell, x, y, hold_ms, label: shell.swipes.append((x, y, hold_ms, label))
original_find_template = reactive.find_template
try:
    reactive.find_template = lambda _frame, template, threshold=0.85: (
        TemplateMatch(20, 30, 8, 8, 0.99)
        if template == Path("fast-start.png")
        else None
    )
    assert not helper._check_exit_or_relay("frame", shell)
    assert helper._fast_start_handled
    assert shell.swipes[-1] == (24, 34, 80, "fast_start")
    fast_start_swipes = len(shell.swipes)
    assert not helper._check_exit_or_relay("frame", shell)
    assert len(shell.swipes) == fast_start_swipes

    reactive.find_template = lambda _frame, template, threshold=0.85: (
        TemplateMatch(10, 20, 8, 8, 0.99) if template == Path("relay.png") else None
    )
    assert not helper._check_exit_or_relay("frame", shell)
    assert shell.swipes[-1] == (14, 24, 80, "relay")

    reactive.find_template = lambda _frame, template, threshold=0.85: (
        TemplateMatch(0, 0, 8, 8, 0.99) if template == Path("result.png") else None
    )
    assert helper._check_exit_or_relay("frame", shell)
finally:
    reactive.find_template = original_find_template

# Runner-loop seam: one obstacle action fires, cooldown suppresses repeats, and
# the result template exits the loop. This avoids real capture/input.
runner = object.__new__(ReactiveRunner)
runner._device = FakeDevice()
runner._capture = FakeCapture()
runner._obstacles = [reactive.Obstacle("fake", "jump", np.zeros((4, 4, 3), dtype=np.uint8))]
runner._exit_template = Path("result.png")
runner._relay_template = None
runner._fast_start_template = None
runner._fast_start_handled = False
runner._debug_view = None

original_check_every = reactive.CHECK_EVERY
original_detect_obstacle = reactive.detect_obstacle
original_find_template = reactive.find_template
original_perf_counter = reactive.time.perf_counter
original_sleep = reactive.time.sleep
original_randint = reactive.random.randint
original_uniform = reactive.random.uniform
ticks = iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5])
try:
    reactive.CHECK_EVERY = 3
    reactive.detect_obstacle = lambda _frame, obstacles: (obstacles[0], 0.99, (1, 2, 3, 4))
    reactive.find_template = lambda _frame, template, threshold=0.85: (
        TemplateMatch(0, 0, 10, 10, 0.99) if template == Path("result.png") else None
    )
    reactive.time.perf_counter = lambda: next(ticks)
    reactive.time.sleep = lambda _seconds: None
    reactive.random.randint = lambda _a, _b: 0
    reactive.random.uniform = lambda _a, _b: 1.0

    assert runner.run(max_seconds=10.0)
    assert len(runner._device.shell.swipes) == 1
    args, kwargs = runner._device.shell.swipes[0]
    assert args[:5] == (*reactive.JUMP_XY, *reactive.JUMP_XY, reactive.HOLD_MS["jump"])
    assert kwargs["label"] == "jump"
finally:
    reactive.CHECK_EVERY = original_check_every
    reactive.detect_obstacle = original_detect_obstacle
    reactive.find_template = original_find_template
    reactive.time.perf_counter = original_perf_counter
    reactive.time.sleep = original_sleep
    reactive.random.randint = original_randint
    reactive.random.uniform = original_uniform

print("ok")
