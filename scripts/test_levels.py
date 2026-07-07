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
    TRACE_VERSION,
    load_levels,
    load_marker,
    read_progress,
    tap_is_due,
)
from scripts.record_levels import progress_at_time, save_level


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

# Progress reading against real frames (skipped if the burst isn't present).
captures = REPO_ROOT / "captures" / "probe1"
if captures.exists():
    marker = load_marker(REPO_ROOT / "assets")
    cutscene = read_progress(cv2.imread(str(captures / "frame_00016.jpg")), marker)
    assert cutscene is None, f"cutscene should have no progress bar, got {cutscene}"
    early = read_progress(cv2.imread(str(captures / "frame_00091.jpg")), marker)
    late = read_progress(cv2.imread(str(captures / "frame_00436.jpg")), marker)
    assert early is not None and late is not None
    assert 0 <= early < 0.1 < 0.7 < late < 0.85, f"early={early}, late={late}"

# Tap progress is interpolated at finger-down time.
samples = [(10.0, 0.10), (10.1, 0.12)]
assert abs(progress_at_time(samples, 10.05) - 0.11) < 1e-9
assert progress_at_time(samples, 10.5) is None

# Moving taps use progress; stationary/unobserved taps use elapsed time.
moving = {"t": 5.0, "progress": 0.25}
assert not tap_is_due(moving, 0.24, 100.0)
assert tap_is_due(moving, 0.25, 0.0)
fallback = {"t": 2.0, "progress": None}
assert not tap_is_due(fallback, 0.9, 1.9)
assert tap_is_due(fallback, None, 2.0)

# Runner-loop seam with fake progress/input. Three low-progress frames start
# level 1, a progress-matched tap fires once, progress wraps to level 2, and
# the result template exits at the 30-frame polling boundary.
runner = object.__new__(LevelReplayer)
runner._device = FakeDevice()
runner._capture = FakeCapture()
runner._marker = np.zeros((1, 1), dtype=np.uint8)
runner._levels = {
    1: {
        "taps": [
            {"t": 99.0, "progress": 0.2, "x": 100, "y": 200, "duration": 0.08}
        ]
    }
}
runner._exit_template = Path("result.png")
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

# Saving produces a v5 trace whose taps carry progress, with null reserved for
# the explicit wall-time fallback when no nearby marker sample exists.
with tempfile.TemporaryDirectory() as td:
    directory = Path(td)
    taps = [
        {"t": 10.05, "x": 100, "y": 200, "duration": 0.08},
        {"t": 11.0, "x": 300, "y": 400, "duration": 0.09},
    ]
    save_level(directory, 1, 10.0, taps, samples, 12.0)
    raw = json.loads((directory / "level_01.json").read_text())
    assert raw["version"] == TRACE_VERSION
    assert abs(raw["taps"][0]["progress"] - 0.11) < 1e-9
    assert raw["taps"][1]["progress"] is None
    loaded = load_levels(directory)
    assert loaded[1]["taps"] == raw["taps"]

# Recorded traces load and are well-formed (skipped if none recorded yet).
# One folder per episode: recordings/levels/<episode>/level_NN.json
levels_root = REPO_ROOT / "recordings" / "levels"
if levels_root.exists():
    for episode_dir in sorted(p for p in levels_root.iterdir() if p.is_dir()):
        try:
            levels = load_levels(episode_dir)
        except ValueError as exc:
            print(f"episode {episode_dir.name}: {exc}")
            continue
        assert levels, f"no traces loaded for episode {episode_dir.name}"
        for number, data in levels.items():
            times = [tap["t"] for tap in data["taps"]]
            assert times == sorted(times), f"{episode_dir.name} level {number} taps out of order"
            assert all("progress" in tap for tap in data["taps"])
            assert all(tap["duration"] >= 0 for tap in data["taps"])
        print(f"validated episode {episode_dir.name}: levels {sorted(levels)}")

print("ok")
