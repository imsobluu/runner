import inspect
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import cv2
import numpy as np

from avd_runner import levels as levels_module
from avd_runner.levels import (
    LevelReplayer,
    ProgressTracker,
    ReplayState,
    TRACE_VERSION,
    locate_marker,
    locate_marker_with_details,
    load_levels,
    load_marker,
    marker_mask,
    read_progress,
    tap_is_due,
)
from avd_runner.vision import TemplateMatch


assert "fast_start_template" in inspect.signature(LevelReplayer).parameters
assert "fast_start_handled" in ReplayState.__dataclass_fields__
from scripts.record_levels import LEVEL_END_LOW_FRAMES, level_end_detected, progress_at_time, save_level


class FakeCapture:
    def __init__(self):
        self.count = 0

    def grab(self):
        self.count += 1
        return self.count


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

# Marker matching should depend on the cookie marker, not the background behind
# it. During cookie skills the progress-bar background changes, but the marker
# foreground still needs to be found.
marker = load_marker(REPO_ROOT / "assets")
mask = marker_mask(marker) > 0
assert mask.any()
assert not mask.all()
assert marker_mask(marker) is marker_mask(marker)
assert locate_marker(np.full((720, 1280, 3), (160, 80, 200), dtype=np.uint8), marker) is None
for background in [(15, 25, 35), (160, 80, 200), (245, 245, 245), (220, 235, 255)]:
    frame = np.full((720, 1280, 3), background, dtype=np.uint8)
    x = levels_module.STRIP_X1 + 60
    y = levels_module.STRIP_Y1 + 8
    crop = frame[y : y + marker.shape[0], x : x + marker.shape[1]]
    crop[mask] = marker[mask]
    located = locate_marker(frame, marker)
    assert located is not None
    detailed = locate_marker_with_details(frame, marker)
    assert detailed is not None
    assert detailed.method in {"color", "edge"}
    assert detailed.score >= 0
    progress, box = located
    assert detailed.box == box
    assert abs(detailed.progress - progress) < 1e-9
    assert abs(box[0] - x) <= 1
    assert abs(box[1] - y) <= 1
    assert 0.0 <= progress <= 1.0

# Progress reading against real frames (skipped if the burst isn't present).
captures = REPO_ROOT / "captures" / "probe1"
if captures.exists():
    cutscene = read_progress(cv2.imread(str(captures / "frame_00016.jpg")), marker)
    assert cutscene is None, f"cutscene should have no progress bar, got {cutscene}"
    early = read_progress(cv2.imread(str(captures / "frame_00091.jpg")), marker)
    late = read_progress(cv2.imread(str(captures / "frame_00436.jpg")), marker)
    assert early is not None and late is not None
    assert 0 <= early < 0.1 < 0.7 < late < 0.85, f"early={early}, late={late}"

# Tap progress is interpolated at finger-down time.
samples = [(10.0, 0.10), (10.1, 0.12)]
assert abs(progress_at_time(samples, 10.05) - 0.11) < 1e-9
assert abs(progress_at_time(samples, 10.5) - 0.20) < 1e-9
gap_samples = [(10.0, 0.10), (11.0, 0.30)]
assert abs(progress_at_time(gap_samples, 10.5) - 0.20) < 1e-9
edge_samples = [(10.0, 0.10), (10.1, 0.12)]
assert progress_at_time(edge_samples, 10.2) == 0.12
assert abs(progress_at_time(edge_samples, 10.4) - 0.18) < 1e-9
assert progress_at_time(edge_samples, 10.7) is None

# Moving taps use progress; stationary/unobserved taps use elapsed time.
moving = {"t": 5.0, "progress": 0.25}
assert not tap_is_due(moving, 0.24, 100.0)
assert tap_is_due(moving, 0.25, 0.0)
fallback = {"t": 2.0, "progress": None}
assert not tap_is_due(fallback, 0.9, 1.9)
assert tap_is_due(fallback, None, 2.0)

# Progress tracker accepts real wraps, predicts short gaps, and rejects
# implausible one-frame detector jumps.
tracker = ProgressTracker()
assert tracker.update(0.0, 0.10).reason == "first"
assert tracker.update(1.0, 0.12).reason == "accepted"
missing = tracker.update(1.5, None)
assert missing.source == "predicted"
assert missing.progress is not None and missing.progress > 0.12
too_fast = tracker.update(1.6, 1.00)
assert too_fast.reason == "rejected_too_fast"
backward = tracker.update(1.7, 0.03)
assert backward.reason == "rejected_backward"
wrap_tracker = ProgressTracker()
wrap_tracker.update(0.0, 0.95)
wrapped = wrap_tracker.update(0.1, 0.01)
assert wrapped.reason == "accepted_wrap"
assert wrapped.progress == 0.01

# A level end requires sustained low progress after a plausible level duration;
# one bad low marker read must not fragment a recording.
ended, low_count = level_end_detected(0.9, 0.0, 3.0, 0)
assert not ended and low_count == 0
ended, low_count = level_end_detected(0.9, 0.0, 20.0, 0)
assert not ended and low_count == 1
low_count = 0
for _ in range(LEVEL_END_LOW_FRAMES):
    ended, low_count = level_end_detected(0.9, 0.0, 20.0, low_count)
assert ended

# State helpers start a level and advance only due taps.
helper_runner = object.__new__(LevelReplayer)
helper_runner._levels = {
    1: [{
        "taps": [
            {"t": 99.0, "progress": 0.2, "x": 100, "y": 200, "duration": 0.08},
            {"t": 99.0, "progress": 0.4, "x": 700, "y": 200, "duration": 0.09},
        ],
        "path": Path("level_01_001.json"),
    }]
}
helper_runner._tap = lambda shell, x, y, duration: shell.swipes.append((x, y, duration))
state = ReplayState(level=1)
original_perf_counter = levels_module.time.perf_counter
try:
    levels_module.time.perf_counter = lambda: 10.0
    helper_runner._start_level(state)
    assert state.in_level
    assert state.max_progress == 0.0
    assert state.tap_index == 0
    assert state.level_t0 == 10.0

    shell = FakeShell()
    helper_runner._play_due_taps(state, shell, progress=0.2, now=10.5)
    assert shell.swipes == [(100, 200, 0.08)]
    assert state.tap_index == 1
    helper_runner._play_due_taps(state, shell, progress=0.39, now=11.0)
    assert state.tap_index == 1
    helper_runner._play_due_taps(state, shell, progress=0.4, now=11.0)
    assert shell.swipes[-1] == (700, 200, 0.09)
    assert state.tap_index == 2
finally:
    levels_module.time.perf_counter = original_perf_counter

# Frame progress and debug output are isolated from the replay state machine.
debug_runner = object.__new__(LevelReplayer)
debug_runner._marker = object()
debug_runner._debug_view = FakeDebugView()
original_locate_marker = levels_module.locate_marker
try:
    levels_module.locate_marker = lambda frame, _marker: (0.25, (1, 2, 3, 4)) if frame == "with-marker" else None
    assert debug_runner._frame_progress("with-marker") == (0.25, (1, 2, 3, 4))
    assert debug_runner._frame_progress("without-marker") == (None, None)
    debug_runner._update_debug_view("frame", 0.25, (1, 2, 3, 4))
    assert debug_runner._debug_view.updates == [
        ("frame", [(1, 2, 3, 4, "progress 25%", (0, 255, 0))])
    ]
finally:
    levels_module.locate_marker = original_locate_marker

# Runner-loop seam with fake progress/input. Three low-progress frames start
# level 1, a progress-matched tap fires once, progress wraps to level 2, and
# the result template exits at the 30-frame polling boundary.
runner = object.__new__(LevelReplayer)
runner._device = FakeDevice()
runner._capture = FakeCapture()
runner._marker = np.zeros((1, 1), dtype=np.uint8)
runner._levels = {
    1: [{
        "taps": [
            {"t": 99.0, "progress": 0.2, "x": 100, "y": 200, "duration": 0.08}
        ],
        "path": Path("level_01_001.json"),
    }]
}
runner._exit_template = Path("result.png")
runner._relay_template = None
runner._fast_start_template = None
runner._on_tap = None
runner._debug_view = None

progress_by_frame = {
    1: 0.0,
    2: 0.0,
    3: 0.0,
    4: 0.2,
    5: 0.9,
    6: 0.0,
}

original_locate_marker = levels_module.locate_marker
original_find_template = levels_module.find_template
original_perf_counter = levels_module.time.perf_counter
original_sleep = levels_module.time.sleep
original_randint = levels_module.random.randint
original_uniform = levels_module.random.uniform
clock = {"value": 0.0}
try:
    levels_module.locate_marker = lambda frame, _marker: (
        progress_by_frame.get(frame, 0.5),
        (1, 2, 3, 4),
    )
    levels_module.find_template = lambda frame, template, threshold=0.85: (
        object() if template == Path("result.png") and frame >= 30 else None
    )
    levels_module.time.perf_counter = lambda: clock.update(value=clock["value"] + 0.1) or clock["value"]
    levels_module.time.sleep = lambda _seconds: None
    levels_module.random.randint = lambda _a, _b: 0
    levels_module.random.uniform = lambda _a, _b: 1.0

    assert runner.run(max_seconds=10.0)
    assert len(runner._device.shell.swipes) == 1
    args, kwargs = runner._device.shell.swipes[0]
    assert args[:5] == (100, 200, 100, 200, 80)
    assert kwargs == {"background": True, "label": "jump"}
finally:
    levels_module.locate_marker = original_locate_marker
    levels_module.find_template = original_find_template
    levels_module.time.perf_counter = original_perf_counter
    levels_module.time.sleep = original_sleep
    levels_module.random.randint = original_randint
    levels_module.random.uniform = original_uniform

# Activating Fast Start is a one-shot foreground tap that leaves recorded
# replay enabled and scheduled taps intact.
fast_runner = object.__new__(LevelReplayer)
fast_runner._exit_template = Path("result.png")
fast_runner._relay_template = None
fast_runner._fast_start_template = Path("activate_fast_start.png")
fast_shell = FakeShell()
recorded = {
    "taps": [
        {"t": 0.0, "progress": 0.2, "x": 100, "y": 200, "duration": 0.08}
    ],
    "path": Path("level_01_001.json"),
}
fast_state = ReplayState(level=1, in_level=True, recorded=recorded)

original_find_template = levels_module.find_template
original_randint = levels_module.random.randint
original_uniform = levels_module.random.uniform
try:
    levels_module.find_template = lambda _frame, template, threshold=0.85: (
        TemplateMatch(10, 20, 30, 40, 0.99)
        if template == fast_runner._fast_start_template
        else None
    )
    levels_module.random.randint = lambda _a, _b: 0
    levels_module.random.uniform = lambda _a, _b: 1.0

    assert not fast_runner._check_exit_or_relay("fast-frame", fast_state, fast_shell)
    assert fast_state.fast_start_handled
    assert fast_state.replay_enabled
    assert fast_state.recorded is recorded
    assert fast_shell.swipes[0][1] == {"background": False, "label": "fast_start"}

    assert not fast_runner._check_exit_or_relay("fast-frame", fast_state, fast_shell)
    assert len(fast_shell.swipes) == 1
    fast_runner._play_due_taps(fast_state, fast_shell, progress=1.0, now=100.0)
    assert len(fast_shell.swipes) == 2
finally:
    levels_module.find_template = original_find_template
    levels_module.random.randint = original_randint
    levels_module.random.uniform = original_uniform

# Activating Cookie Relay is a foreground tap and permanently disables future
# recorded taps, including recordings that exist for later levels.
relay_runner = object.__new__(LevelReplayer)
relay_runner._levels = {
    1: [{
        "taps": [
            {"t": 0.0, "progress": 0.2, "x": 100, "y": 200, "duration": 0.08}
        ],
        "path": Path("level_01_001.json"),
    }],
    2: [{
        "taps": [
            {"t": 0.0, "progress": 0.2, "x": 700, "y": 200, "duration": 0.08}
        ],
        "path": Path("level_02_001.json"),
    }],
}
relay_runner._exit_template = Path("result.png")
relay_runner._relay_template = Path("activate_cookie_relay.png")
relay_runner._fast_start_template = None
relay_shell = FakeShell()
relay_state = ReplayState(
    level=1,
    in_level=True,
    recorded=relay_runner._levels[1][0],
)

original_find_template = levels_module.find_template
original_randint = levels_module.random.randint
original_uniform = levels_module.random.uniform
try:
    levels_module.find_template = lambda _frame, template, threshold=0.85: (
        TemplateMatch(10, 20, 30, 40, 0.99)
        if template == relay_runner._relay_template
        else None
    )
    levels_module.random.randint = lambda _a, _b: 0
    levels_module.random.uniform = lambda _a, _b: 1.0

    assert not relay_runner._check_exit_or_relay("relay-frame", relay_state, relay_shell)
    assert relay_state.relay_handled
    assert not relay_state.replay_enabled
    assert relay_state.recorded is None
    assert len(relay_shell.swipes) == 1
    args, kwargs = relay_shell.swipes[0]
    assert args[:5] == (25, 40, 25, 40, 80)
    assert kwargs == {"background": False, "label": "relay"}

    relay_runner._play_due_taps(relay_state, relay_shell, progress=1.0, now=100.0)
    assert len(relay_shell.swipes) == 1
    relay_state.level = 2
    relay_runner._start_level(relay_state)
    assert relay_state.recorded is None
finally:
    levels_module.find_template = original_find_template
    levels_module.random.randint = original_randint
    levels_module.random.uniform = original_uniform

# Saving produces a v5 trace whose taps carry progress, with null reserved for
# the explicit wall-time fallback when no nearby marker sample exists.
with tempfile.TemporaryDirectory() as td:
    directory = Path(td)
    taps = [
        {"t": 10.05, "x": 100, "y": 200, "duration": 0.08},
        {"t": 11.0, "x": 300, "y": 400, "duration": 0.09},
    ]
    save_level(directory, 1, 10.0, taps, samples, 12.0)
    first_path = directory / "levels" / "level_01" / "level_01_001.json"
    raw = json.loads(first_path.read_text())
    assert raw["version"] == TRACE_VERSION
    assert abs(raw["taps"][0]["progress"] - 0.11) < 1e-9
    assert raw["taps"][1]["progress"] is None
    save_level(directory, 1, 10.0, taps, samples, 12.0)
    assert (directory / "levels" / "level_01" / "level_01_002.json").exists()
    loaded = load_levels(directory)
    assert len(loaded[1]) == 2
    assert loaded[1][0]["taps"] == raw["taps"]
    assert loaded[1][0]["path"] == first_path

# Old flat episode files are intentionally unsupported; only the nested
# levels/level_NN/level_NN_nnn.json layout is loaded.
with tempfile.TemporaryDirectory() as td:
    directory = Path(td)
    (directory / "level_01.json").write_text(
        json.dumps({"version": TRACE_VERSION, "level": 1, "taps": []}),
        encoding="utf-8",
    )
    assert load_levels(directory) == {}

# Recorded traces load and are well-formed (skipped if none recorded yet).
# One folder per episode: recordings/episodes/<episode>/levels/level_NN/level_NN_nnn.json
levels_root = REPO_ROOT / "recordings" / "episodes"
if levels_root.exists():
    for episode_dir in sorted(p for p in levels_root.iterdir() if p.is_dir()):
        try:
            levels = load_levels(episode_dir)
        except ValueError as exc:
            print(f"episode {episode_dir.name}: {exc}")
            continue
        assert levels, f"no traces loaded for episode {episode_dir.name}"
        for number, variants in levels.items():
            assert variants, f"{episode_dir.name} level {number} has no variants"
            for data in variants:
                times = [tap["t"] for tap in data["taps"]]
                assert times == sorted(times), f"{episode_dir.name} level {number} taps out of order"
                assert all("progress" in tap for tap in data["taps"])
                assert all(tap["duration"] >= 0 for tap in data["taps"])
        print(f"validated episode {episode_dir.name}: levels {sorted(levels)}")

print("ok")
