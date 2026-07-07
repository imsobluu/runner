import sys
import tempfile
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from avd_runner import AvdDevice
from avd_runner import menu
from scripts import auto_runner


class FakeCapture:
    def __init__(self, frame):
        self.frame = frame

    def grab(self):
        return self.frame


frame = np.zeros((8, 8, 3), dtype=np.uint8)
ctx = auto_runner.AutoRunnerContext(
    device=AvdDevice(),
    capture=FakeCapture(frame),
    captcha_enabled=False,
)

# Context-backed capture and disabled captcha checks are pure and should not
# touch WGC/ADB.
assert menu.take_screenshot(ctx) is frame
assert not menu.solve_captcha_if_present(ctx, frame, auto_runner.CAPTCHA_BANNER_TEMPLATE)

# Target definitions preserve behavior-sensitive retry policy.
assert auto_runner.PLAY_WITH_DOUBLE_COINS_TARGET.verify_gone
assert auto_runner.FAST_START_0_TARGET.threshold == 0.99
assert auto_runner.FAST_START_0_TARGET.attempts == 1
assert auto_runner.RESULT_OK_TARGET.attempts == 120

# Debug tap saving is scoped to the context and increments per run directory.
with tempfile.TemporaryDirectory() as td:
    ctx.debug_run_dir = Path(td)
    ctx.debug_tap_count = 0
    menu.debug_save_tap(ctx, "Play Button", frame, 3, 4)
    assert ctx.debug_tap_count == 1
    assert (Path(td) / "01_play_button.png").exists()

# Episode resolution behavior without touching repo recordings.
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    only = root / "ep01"
    only.mkdir()
    assert auto_runner.resolve_episode_dir(None, root) == only
    assert auto_runner.resolve_episode_dir("ep01", root) == only

    (root / "ep02").mkdir()
    try:
        auto_runner.resolve_episode_dir(None, root)
    except SystemExit as exc:
        assert "--episode is required" in str(exc)
    else:
        raise AssertionError("multiple episodes without explicit choice should exit")

    try:
        auto_runner.resolve_episode_dir("missing", root)
    except SystemExit as exc:
        assert "No recordings for episode" in str(exc)
    else:
        raise AssertionError("missing episode should exit")

# parse_args is now testable without mutating sys.argv.
args = auto_runner.parse_args(["--mode", "none", "--loop-count", "2"])
assert args.mode == "none"
assert args.loop_count == 2

try:
    with redirect_stderr(StringIO()):
        auto_runner.parse_args(["--loop-count", "0"])
except SystemExit:
    pass
else:
    raise AssertionError("--loop-count 0 should be rejected")

# Flow helpers should now be testable without directly raising SystemExit.
original_tap_play_button = auto_runner.tap_play_button
try:
    auto_runner.tap_play_button = lambda _ctx: False
    try:
        auto_runner.run_once(ctx, auto_runner.parse_args([]))
    except auto_runner.RunnerError:
        pass
    else:
        raise AssertionError("run_once should raise RunnerError when Play fails")
finally:
    auto_runner.tap_play_button = original_tap_play_button

print("ok")
