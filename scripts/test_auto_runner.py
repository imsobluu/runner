import sys
import tempfile
import types
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from avd_runner import AvdDevice
from avd_runner.debug_session import DebugSession
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
    debug=DebugSession(),
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
assert menu.SCREENSHOTS_DIR == auto_runner.REPO_ROOT / "screenshots"
assert hasattr(auto_runner, "ACTIVATE_FAST_START_TEMPLATE")
assert auto_runner.PAUSE_XY == (1194, 37)
assert auto_runner.QUIT_TARGET.path == auto_runner.ASSETS / "quit.png"

# The final gameplay-start tap accepts both boosted and plain Play screens,
# preferring the more specific Double Coins template when both could match.
original_wait_for_any_template = auto_runner.wait_for_any_template
original_tap_target = auto_runner.tap_target
lookups = []
tapped = []
expected_lookup = [
    (auto_runner.PLAY_WITH_DOUBLE_COINS_TARGET.name, auto_runner.PLAY_WITH_DOUBLE_COINS_TARGET.path),
    (auto_runner.PLAY_TARGET.name, auto_runner.PLAY_TARGET.path),
]
try:
    for seen, expected_target in (
        (auto_runner.PLAY_WITH_DOUBLE_COINS_TARGET.name, auto_runner.PLAY_WITH_DOUBLE_COINS_TARGET),
        (auto_runner.PLAY_TARGET.name, auto_runner.PLAY_TARGET),
    ):
        lookups.clear()
        tapped.clear()
        auto_runner.wait_for_any_template = (
            lambda _ctx, targets, _banner, **_kwargs: lookups.append(targets) or seen
        )
        auto_runner.tap_target = (
            lambda _ctx, target, **_kwargs: tapped.append(target) or True
        )
        assert auto_runner.tap_play_with_double_coins_button(ctx)
        assert lookups == [expected_lookup]
        assert tapped == [expected_target]

    tapped.clear()
    auto_runner.wait_for_any_template = lambda _ctx, _targets, _banner, **_kwargs: None
    assert not auto_runner.tap_play_with_double_coins_button(ctx)
    assert tapped == []
finally:
    auto_runner.wait_for_any_template = original_wait_for_any_template
    auto_runner.tap_target = original_tap_target

# Reaching the configured collection target taps Pause by coordinate, then
# matches both Quit buttons without adding waits.
original_device_tap = ctx.device.tap
original_tap_target = auto_runner.tap_target
quit_sequence = []
try:
    ctx.device.tap = (
        lambda x, y, label="": quit_sequence.append(("tap", x, y, label))
        or (x, y)
    )
    auto_runner.tap_target = (
        lambda _ctx, target, **_kwargs: quit_sequence.append(target.name) or True
    )
    auto_runner.quit_gameplay(ctx)
    assert quit_sequence == [
        ("tap", 1194, 37, "Pause"),
        "Quit",
        "Quit",
    ]
finally:
    ctx.device.tap = original_device_tap
    auto_runner.tap_target = original_tap_target

# Debug tap saving is scoped to the context and increments per run directory.
with tempfile.TemporaryDirectory() as td:
    ctx.debug = DebugSession(root=Path(td))
    ctx.debug.start_run(1)
    menu.debug_save_tap(ctx, "Play Button", frame, 3, 4)
    assert (Path(td) / "run1" / "01_play_button.png").exists()

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
    except auto_runner.RunnerError as exc:
        assert "--episode is required" in str(exc)
    else:
        raise AssertionError("multiple episodes without explicit choice should exit")

    try:
        auto_runner.resolve_episode_dir("missing", root)
    except auto_runner.RunnerError as exc:
        assert "No recordings for episode" in str(exc)
    else:
        raise AssertionError("missing episode should exit")

# Gameplay runner construction is isolated from the final Play tap and can be
# checked without loading real gameplay assets.
ctx.debug = DebugSession()

def fake_runner_module(module_name, class_name):
    module = types.ModuleType(module_name)
    instances = []

    class FakeRunner:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            instances.append(self)

        def run(self):
            return True

    setattr(module, class_name, FakeRunner)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    return previous, instances


previous, instances = fake_runner_module("avd_runner.none", "NoneRunner")
try:
    runner = auto_runner.build_gameplay_runner(
        ctx,
        "none",
        auto_runner.ACTIVATE_COOKIE_RELAY_TEMPLATE,
        auto_runner.ACTIVATE_FAST_START_TEMPLATE,
        None,
    )
    assert runner is instances[0]
    assert instances[0].kwargs["exit_template"] == auto_runner.RESULT_OK_BUTTON_TEMPLATE
    assert instances[0].kwargs["relay_template"] == auto_runner.ACTIVATE_COOKIE_RELAY_TEMPLATE
    assert instances[0].kwargs["fast_start_template"] == auto_runner.ACTIVATE_FAST_START_TEMPLATE
finally:
    if previous is None:
        del sys.modules["avd_runner.none"]
    else:
        sys.modules["avd_runner.none"] = previous

previous, instances = fake_runner_module("avd_runner.levels", "LevelReplayer")
try:
    episode_dir = Path("recordings/episodes/ep01")
    runner = auto_runner.build_gameplay_runner(
        ctx,
        "levels",
        auto_runner.ACTIVATE_COOKIE_RELAY_TEMPLATE,
        auto_runner.ACTIVATE_FAST_START_TEMPLATE,
        episode_dir,
    )
    assert runner is instances[0]
    assert instances[0].args[2] == auto_runner.ASSETS
    assert instances[0].args[3] == episode_dir
    assert instances[0].kwargs["relay_template"] == auto_runner.ACTIVATE_COOKIE_RELAY_TEMPLATE
    assert instances[0].kwargs["fast_start_template"] == auto_runner.ACTIVATE_FAST_START_TEMPLATE
finally:
    if previous is None:
        del sys.modules["avd_runner.levels"]
    else:
        sys.modules["avd_runner.levels"] = previous

previous, instances = fake_runner_module("avd_runner.reactive", "ReactiveRunner")
try:
    runner = auto_runner.build_gameplay_runner(
        ctx,
        "reactive",
        auto_runner.ACTIVATE_COOKIE_RELAY_TEMPLATE,
        auto_runner.ACTIVATE_FAST_START_TEMPLATE,
        None,
    )
    assert runner is instances[0]
    assert instances[0].kwargs["relay_template"] == auto_runner.ACTIVATE_COOKIE_RELAY_TEMPLATE
    assert instances[0].kwargs["fast_start_template"] == auto_runner.ACTIVATE_FAST_START_TEMPLATE
finally:
    if previous is None:
        del sys.modules["avd_runner.reactive"]
    else:
        sys.modules["avd_runner.reactive"] = previous

# run_after_start must keep validating levels recordings before the final Play
# tap, so a bad episode does not spend a run.
original_tap_play_with_double_coins_button = auto_runner.tap_play_with_double_coins_button
tap_calls = []
try:
    auto_runner.tap_play_with_double_coins_button = lambda _ctx: tap_calls.append("tap") or True
    try:
        auto_runner.run_after_start(ctx, "levels", False, True, "definitely_missing_episode")
    except auto_runner.RunnerError as exc:
        assert "No recordings for episode" in str(exc)
    else:
        raise AssertionError("missing episode should stop run_after_start")
    assert tap_calls == []
finally:
    auto_runner.tap_play_with_double_coins_button = original_tap_play_with_double_coins_button

# --fast-start maps to an optional gameplay-runner template without changing
# the existing Cookie Relay template.
original_build_gameplay_runner = auto_runner.build_gameplay_runner
original_tap_play_with_double_coins_button = auto_runner.tap_play_with_double_coins_button
fast_start_templates = []

class FakeGameplayRunner:
    def run(self):
        return True

try:
    auto_runner.tap_play_with_double_coins_button = lambda _ctx: True
    auto_runner.build_gameplay_runner = (
        lambda _ctx, _mode, _relay, fast_start, _episode: (
            fast_start_templates.append(fast_start) or FakeGameplayRunner()
        )
    )
    auto_runner.run_after_start(ctx, "none", False, False, None)
    auto_runner.run_after_start(ctx, "none", False, True, None)
    assert fast_start_templates == [None, auto_runner.ACTIVATE_FAST_START_TEMPLATE]
finally:
    auto_runner.build_gameplay_runner = original_build_gameplay_runner
    auto_runner.tap_play_with_double_coins_button = original_tap_play_with_double_coins_button

# A mystery-box target signal runs the quit sequence and then returns normally
# so the caller can continue with result cleanup.
class TargetRunner:
    def run(self):
        raise auto_runner.MysteryBoxTargetReached(2)


original_tap_play_with_double_coins_button = auto_runner.tap_play_with_double_coins_button
original_quit_gameplay = auto_runner.quit_gameplay
original_build_gameplay_runner = auto_runner.build_gameplay_runner
quit_calls = []
captures = []
try:
    auto_runner.tap_play_with_double_coins_button = lambda _ctx: True
    auto_runner.quit_gameplay = lambda _ctx: quit_calls.append("quit")
    auto_runner.build_gameplay_runner = (
        lambda runner_ctx, _mode, _relay, _fast_start, _episode: (
            captures.append(runner_ctx.capture) or TargetRunner()
        )
    )
    auto_runner.run_after_start(ctx, "none", False, False, None, 2)
    assert isinstance(captures[0], auto_runner.MysteryBoxCapture)
    assert quit_calls == ["quit"]
finally:
    auto_runner.tap_play_with_double_coins_button = original_tap_play_with_double_coins_button
    auto_runner.quit_gameplay = original_quit_gameplay
    auto_runner.build_gameplay_runner = original_build_gameplay_runner

# OCR setup/inference failures use the runner's controlled error path instead
# of leaking a traceback from the gameplay loop.
class BrokenOCRRunner:
    def run(self):
        raise auto_runner.MysteryBoxOCRError("OCR unavailable")


original_tap_play_with_double_coins_button = auto_runner.tap_play_with_double_coins_button
original_build_gameplay_runner = auto_runner.build_gameplay_runner
try:
    auto_runner.tap_play_with_double_coins_button = lambda _ctx: True
    auto_runner.build_gameplay_runner = (
        lambda _ctx, _mode, _relay, _fast_start, _episode: BrokenOCRRunner()
    )
    try:
        auto_runner.run_after_start(ctx, "none", False, False, None, 2)
    except auto_runner.RunnerError as exc:
        assert str(exc) == "OCR unavailable"
    else:
        raise AssertionError("OCR errors should be translated to RunnerError")
finally:
    auto_runner.tap_play_with_double_coins_button = original_tap_play_with_double_coins_button
    auto_runner.build_gameplay_runner = original_build_gameplay_runner

# The optional relic claim runs before the initial Play tap.
original_tap_play_button = auto_runner.tap_play_button
original_claim_relic_if_alert = auto_runner.claim_relic_if_alert
original_ensure_double_coins_setup = auto_runner.ensure_double_coins_setup
original_buy_optional_boosts = auto_runner.buy_optional_boosts
original_run_after_start = auto_runner.run_after_start
original_clear_results = auto_runner.clear_results
order = []
try:
    auto_runner.claim_relic_if_alert = lambda _ctx: order.append("relic") or False
    auto_runner.tap_play_button = lambda _ctx: order.append("play") or True
    auto_runner.ensure_double_coins_setup = lambda _ctx: order.append("double_coins")
    auto_runner.buy_optional_boosts = lambda _ctx, _skip: order.append("boosts")
    auto_runner.run_after_start = (
        lambda _ctx, _mode, _no_relay, fast_start, _episode, mystery_target: order.append(
            ("gameplay", fast_start, mystery_target)
        )
    )
    auto_runner.clear_results = lambda _ctx: order.append("clear")

    auto_runner.run_once(ctx, auto_runner.parse_args(["--mode", "none"]))
    assert order == [
        "relic",
        "play",
        "double_coins",
        "boosts",
        ("gameplay", False, None),
        "clear",
    ]

    order.clear()
    auto_runner.run_once(ctx, auto_runner.parse_args(["--mode", "none", "--fast-start"]))
    assert order == [
        "relic",
        "play",
        "double_coins",
        "boosts",
        ("gameplay", True, None),
        "clear",
    ]

    order.clear()
    skip_args = types.SimpleNamespace(
        mode="none",
        no_cookie_relay=False,
        episode=None,
        skip_top_row_boosts=False,
        skip_random_boost=True,
        fast_start=False,
        quit_on_collect_mystery_box=None,
    )
    auto_runner.run_once(ctx, skip_args)
    assert order == ["relic", "play", "boosts", ("gameplay", False, None), "clear"]
finally:
    auto_runner.tap_play_button = original_tap_play_button
    auto_runner.claim_relic_if_alert = original_claim_relic_if_alert
    auto_runner.ensure_double_coins_setup = original_ensure_double_coins_setup
    auto_runner.buy_optional_boosts = original_buy_optional_boosts
    auto_runner.run_after_start = original_run_after_start
    auto_runner.clear_results = original_clear_results

# Relic claim sequence exits the relic page after confirming the claim.
original_tap_target = auto_runner.tap_target
sequence = []
try:
    auto_runner.tap_target = lambda _ctx, target, **_kwargs: sequence.append(target.name) or True
    assert auto_runner.claim_relic_if_alert(ctx)
    assert sequence == [
        "Get Alert",
        "Relic Gem",
        "Claim Relic",
        "Confirm Relic",
        "Exit Relic Page",
    ]
finally:
    auto_runner.tap_target = original_tap_target

# parse_args is now testable without mutating sys.argv.
args = auto_runner.parse_args(["--mode", "none", "--loop-count", "2"])
assert args.mode == "none"
assert args.loop_count == 2

mystery_args = auto_runner.parse_args(["--quit-on-collect-mystery-box", "3"])
assert mystery_args.quit_on_collect_mystery_box == 3
assert auto_runner.parse_args([]).quit_on_collect_mystery_box is None

try:
    with redirect_stderr(StringIO()):
        auto_runner.parse_args(["--quit-on-collect-mystery-box", "0"])
except SystemExit:
    pass
else:
    raise AssertionError("mystery-box target 0 should be rejected")

default_args = auto_runner.parse_args([])
skip_args = auto_runner.parse_args(["--skip-random-boost"])
assert vars(default_args).get("skip_random_boost") is False
assert vars(skip_args).get("skip_random_boost") is True

fast_args = auto_runner.parse_args(["--fast-start"])
assert vars(default_args).get("fast_start") is False
assert vars(fast_args).get("fast_start") is True

try:
    with redirect_stderr(StringIO()):
        auto_runner.parse_args(["--loop-count", "0"])
except SystemExit:
    pass
else:
    raise AssertionError("--loop-count 0 should be rejected")

# Flow helpers should now be testable without directly raising SystemExit.
original_tap_play_button = auto_runner.tap_play_button
original_claim_relic_if_alert = auto_runner.claim_relic_if_alert
try:
    auto_runner.claim_relic_if_alert = lambda _ctx: False
    auto_runner.tap_play_button = lambda _ctx: False
    try:
        auto_runner.run_once(ctx, auto_runner.parse_args([]))
    except auto_runner.RunnerError:
        pass
    else:
        raise AssertionError("run_once should raise RunnerError when Play fails")
finally:
    auto_runner.claim_relic_if_alert = original_claim_relic_if_alert
    auto_runner.tap_play_button = original_tap_play_button

print("ok")
