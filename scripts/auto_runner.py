import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from avd_runner import AvdDevice, wait
from avd_runner.menu import (
    debug_save_tap,
    is_toggle_selected,
    tap_template,
    wait_for_any_template,
    wait_for_template,
)


ASSETS = REPO_ROOT / "assets"
CAPTCHA_BANNER_TEMPLATE = ASSETS / "captcha_banner.png"

@dataclass
class AutoRunnerContext:
    device: AvdDevice
    capture: object
    captcha_enabled: bool = True
    debug_view: object | None = None
    debug_run_dir: Path | None = None
    debug_tap_count: int = 0


PLAY_BUTTON_TEMPLATE = ASSETS / "play_button.png"
PLAY_WITH_DOUBLE_COINS_TEMPLATE = ASSETS / "play_with_double_coins.png"
RANDOM_BOOST_TEMPLATE = ASSETS / "random_boost.png"
RANDOM_BOOST_SELECTED_TEMPLATE = ASSETS / "random_boost_selected.png"
MULTI_BUTTON_TEMPLATE = ASSETS / "multi_button.png"
MULTI_BUY_BUTTON_TEMPLATE = ASSETS / "multi_buy_button.png"
DOUBLE_COINS_TEMPLATE = ASSETS / "double_coins.png"
DOUBLE_COINS_SELECTED_TEMPLATE = ASSETS / "double_coins_selected.png"
DOUBLE_COINS_BANNER_TEMPLATE = ASSETS / "double_coins_banner.png"
FAST_START_0_TEMPLATE = ASSETS / "fast_start_0.png"
COOKIE_RELAY_0_TEMPLATE = ASSETS / "cookie_relay_0.png"
DOUBLE_XP_TEMPLATE = ASSETS / "double_xp.png"
POWER_JELLY_BOOST_TEMPLATE = ASSETS / "power_jelly_boost.png"
HP_EXTENSION_TEMPLATE = ASSETS / "hp_extension.png"
BOOST_BUY_BUTTON_TEMPLATE = ASSETS / "boost_buy_button.png"
ACTIVATE_COOKIE_RELAY_TEMPLATE = ASSETS / "activate_cookie_relay.png"
RESULT_OK_BUTTON_TEMPLATE = ASSETS / "result_ok_button.png"
OPEN_ALL_MYSTERY_BOX_BUTTON_TEMPLATE = ASSETS / "open_all_mystery_box_button.png"
CONFIRM_MYSTERY_BOX_BUTTON_TEMPLATE = ASSETS / "confirm_mystery_box_button.png"
LEVEL_UP_CONFIRM_BUTTON_TEMPLATE = ASSETS / "level_up_confirm_button.png"
LEVEL_RECORDINGS_DIR = REPO_ROOT / "recordings" / "levels"


def tap_play_button(
    ctx: AutoRunnerContext,
    attempts: int = 5,
) -> bool:
    return tap_template(ctx, "Play", PLAY_BUTTON_TEMPLATE, CAPTCHA_BANNER_TEMPLATE, attempts=attempts)


def tap_play_with_double_coins_button(
    ctx: AutoRunnerContext,
    attempts: int = 5,
) -> bool:
    return tap_template(
        ctx,
        "Play with Double Coins",
        PLAY_WITH_DOUBLE_COINS_TEMPLATE,
        CAPTCHA_BANNER_TEMPLATE,
        attempts=attempts,
        # The purchase-complete modal from a boost buy can swallow this tap
        # without covering the button; re-tap until the button actually goes.
        verify_gone=True,
    )


def tap_random_boost_button(
    ctx: AutoRunnerContext,
    attempts: int = 5,
    save_debug: bool = False,
) -> bool:
    if is_toggle_selected(
        ctx, "Random Boost Selected", RANDOM_BOOST_SELECTED_TEMPLATE, RANDOM_BOOST_TEMPLATE,
        CAPTCHA_BANNER_TEMPLATE,
    ):
        return True

    return tap_template(
        ctx,
        "Random Boost",
        RANDOM_BOOST_TEMPLATE,
        CAPTCHA_BANNER_TEMPLATE,
        attempts=attempts,
        save_debug=save_debug,
    )


def tap_multi_button(
    ctx: AutoRunnerContext,
    attempts: int = 5,
    save_debug: bool = False,
) -> bool:
    return tap_template(
        ctx,
        "Multi",
        MULTI_BUTTON_TEMPLATE,
        CAPTCHA_BANNER_TEMPLATE,
        attempts=attempts,
        save_debug=save_debug,
    )


def tap_multi_buy_button(
    ctx: AutoRunnerContext,
    attempts: int = 5,
    save_debug: bool = False,
) -> bool:
    return tap_template(
        ctx,
        "Multi Buy",
        MULTI_BUY_BUTTON_TEMPLATE,
        CAPTCHA_BANNER_TEMPLATE,
        attempts=attempts,
        save_debug=save_debug,
    )


def tap_double_coins_button(
    ctx: AutoRunnerContext,
    attempts: int = 5,
    save_debug: bool = False,
) -> bool:
    if is_toggle_selected(
        ctx, "Double Coins Selected", DOUBLE_COINS_SELECTED_TEMPLATE, DOUBLE_COINS_TEMPLATE,
        CAPTCHA_BANNER_TEMPLATE,
    ):
        return True

    return tap_template(
        ctx,
        "Double Coins",
        DOUBLE_COINS_TEMPLATE,
        CAPTCHA_BANNER_TEMPLATE,
        attempts=attempts,
        save_debug=save_debug,
    )


def tap_fast_start_0_if_visible(ctx: AutoRunnerContext) -> bool:
    return tap_template(
        ctx,
        "Fast Start 0",
        FAST_START_0_TEMPLATE,
        CAPTCHA_BANNER_TEMPLATE,
        threshold=0.99,
        attempts=1,
    )


def tap_cookie_relay_0_if_visible(ctx: AutoRunnerContext) -> bool:
    return tap_template(
        ctx,
        "Cookie Relay 0",
        COOKIE_RELAY_0_TEMPLATE,
        CAPTCHA_BANNER_TEMPLATE,
        threshold=0.99,
        attempts=1,
    )


def tap_double_xp_if_visible(ctx: AutoRunnerContext) -> bool:
    return tap_template(ctx, "Double XP", DOUBLE_XP_TEMPLATE, CAPTCHA_BANNER_TEMPLATE, attempts=1)


def tap_power_jelly_boost_if_visible(ctx: AutoRunnerContext) -> bool:
    return tap_template(
        ctx,
        "Power Jelly Boost",
        POWER_JELLY_BOOST_TEMPLATE,
        CAPTCHA_BANNER_TEMPLATE,
        attempts=1,
    )


def tap_hp_extension_if_visible(ctx: AutoRunnerContext) -> bool:
    return tap_template(ctx, "HP Extension", HP_EXTENSION_TEMPLATE, CAPTCHA_BANNER_TEMPLATE, attempts=1)


def tap_boost_buy_button(ctx: AutoRunnerContext) -> bool:
    return tap_template(ctx, "Boost Buy", BOOST_BUY_BUTTON_TEMPLATE, CAPTCHA_BANNER_TEMPLATE)


def tap_result_ok_button(ctx: AutoRunnerContext) -> bool:
    return tap_template(ctx, "Result OK", RESULT_OK_BUTTON_TEMPLATE, CAPTCHA_BANNER_TEMPLATE, attempts=120)


def tap_open_all_mystery_box_button(ctx: AutoRunnerContext) -> bool:
    return tap_template(
        ctx,
        "Open All Mystery Box",
        OPEN_ALL_MYSTERY_BOX_BUTTON_TEMPLATE,
        CAPTCHA_BANNER_TEMPLATE,
        attempts=5,
    )


def tap_confirm_mystery_box_button(ctx: AutoRunnerContext) -> bool:
    return tap_template(
        ctx,
        "Confirm Mystery Box",
        CONFIRM_MYSTERY_BOX_BUTTON_TEMPLATE,
        CAPTCHA_BANNER_TEMPLATE,
        attempts=5,
    )

def tap_level_up_confirm_button(ctx: AutoRunnerContext) -> bool:
    return tap_template(
        ctx,
        "Level Up Confirm",
        LEVEL_UP_CONFIRM_BUTTON_TEMPLATE,
        CAPTCHA_BANNER_TEMPLATE,
        attempts=5,
    )


def resolve_episode_dir(
    episode: str | None,
    recordings_dir: Path = LEVEL_RECORDINGS_DIR,
) -> Path:
    """Pick the episode's recordings folder; default to the only one present."""
    available = sorted(
        p.name for p in recordings_dir.iterdir() if p.is_dir()
    ) if recordings_dir.is_dir() else []
    if episode:
        path = recordings_dir / episode
        if not path.is_dir():
            raise SystemExit(
                f"No recordings for episode {episode!r}. Available: {available or 'none'}"
            )
        return path
    if len(available) == 1:
        return recordings_dir / available[0]
    raise SystemExit(
        f"--episode is required when there isn't exactly one recorded episode. "
        f"Available: {available or 'none'}"
    )


def run_after_start(
    ctx: AutoRunnerContext,
    mode: str,
    no_cookie_relay: bool,
    episode: str | None,
) -> None:
    # Resolve before tapping Play so a missing episode fails without
    # starting (and wasting) a run.
    episode_dir = resolve_episode_dir(episode) if mode == "levels" else None
    relay_template = None if no_cookie_relay else ACTIVATE_COOKIE_RELAY_TEMPLATE

    # The gameplay drivers take over after the boost screen's final Play button.
    if not tap_play_with_double_coins_button(ctx):
        raise SystemExit(1)

    if mode == "levels":
        from avd_runner.levels import LevelReplayer

        runner = LevelReplayer(
            ctx.device,
            ctx.capture,
            ASSETS,
            episode_dir,
            exit_template=RESULT_OK_BUTTON_TEMPLATE,
            on_tap=(lambda name, frame, x, y: debug_save_tap(ctx, name, frame, x, y))
            if ctx.debug_run_dir is not None
            else None,
            debug_view=ctx.debug_view,
        )
    if mode == "reactive":
        from avd_runner.reactive import ReactiveRunner

        runner = ReactiveRunner(
            ctx.device,
            ctx.capture,
            ASSETS / "witch_oven",
            exit_template=RESULT_OK_BUTTON_TEMPLATE,
            relay_template=relay_template,
            debug_view=ctx.debug_view,
        )
    if mode == "none":
        from avd_runner.none import NoneRunner

        runner = NoneRunner(
            ctx.device,
            ctx.capture,
            exit_template=RESULT_OK_BUTTON_TEMPLATE,
            relay_template=relay_template,
            debug_view=ctx.debug_view,
        )
    if not runner.run():
        raise SystemExit(1)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Cookie Run setup bot.")
    parser.add_argument(
        "--mode",
        choices=("levels", "reactive", "none"),
        default="levels",
        help="Replay per-level recordings re-synced on the level progress bar, "
        "play reactively by detecting obstacles on screen, or 'none': play "
        "nothing and just watch for the relay banner and result screen.",
    )
    parser.add_argument(
        "--episode",
        help="Episode whose level recordings to replay (folder under "
        "recordings/levels/). Defaults to the only recorded episode.",
    )
    parser.add_argument(
        "--no-cookie-relay",
        action="store_true",
        help="Don't tap activate_cookie_relay.png when it appears mid-run "
        "(reactive and none modes tap it by default).",
    )
    parser.add_argument(
        "--no-captcha",
        action="store_true",
        help="Disable the anti-bot captcha solver run before and after gameplay.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Repeat the full auto-run flow until interrupted.",
    )
    parser.add_argument(
        "--loop-count",
        type=int,
        help="Repeat the full auto-run flow this many times.",
    )
    parser.add_argument(
        "--loop-delay",
        type=float,
        default=2.0,
        help="Seconds to wait between loop iterations.",
    )
    parser.add_argument(
        "--skip-top-row-boosts",
        action="store_true",
        help="Skip top row boost checks.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save each tapped frame with a red dot at the tap point to "
        "debug/<session id>/runN/<NN>_<button>.png.",
    )
    parser.add_argument(
        "--debug-window",
        action="store_true",
        help="Show a live window with detected template/obstacle boxes and "
        "taps drawn on the captured frames (menu, levels, and reactive).",
    )
    args = parser.parse_args(argv)
    if args.loop_count is not None and args.loop_count < 1:
        parser.error("--loop-count must be at least 1")
    return args


def buy_boost_if_available(ctx: AutoRunnerContext, select) -> None:
    """Select an optional boost and buy it, then wait for the boost screen back.

    `select` taps the boost tile if present (single-shot; absent boosts are
    skipped). After buying, the purchase modal dims the screen; re-anchoring on
    the Double Coins Banner waits for it to clear before the next boost check -
    replacing the old fixed post-purchase wait.
    """
    if not select(ctx):
        return
    if not tap_boost_buy_button(ctx):
        raise SystemExit(1)
    if not wait_for_template(ctx, "Double Coins Banner", DOUBLE_COINS_BANNER_TEMPLATE, CAPTCHA_BANNER_TEMPLATE):
        raise SystemExit(1)


def run_once(ctx: AutoRunnerContext, args: argparse.Namespace) -> None:
    if not tap_play_button(ctx):
        raise SystemExit(1)

    seen = wait_for_any_template(
        ctx,
        [
            ("Double Coins Banner", DOUBLE_COINS_BANNER_TEMPLATE),
            ("Random Boost Selected", RANDOM_BOOST_SELECTED_TEMPLATE),
            ("Random Boost", RANDOM_BOOST_TEMPLATE),
        ],
        CAPTCHA_BANNER_TEMPLATE,
    )
    if seen is None:
        print("Neither the boost-selection nor double-coins screen appeared.")
        raise SystemExit(1)

    if seen != "Double Coins Banner":
        if not tap_random_boost_button(ctx):
            raise SystemExit(1)
        if not tap_multi_button(ctx):
            raise SystemExit(1)
        if not tap_double_coins_button(ctx):
            raise SystemExit(1)
        if not tap_multi_buy_button(ctx):
            raise SystemExit(1)
        if not wait_for_template(ctx, "Double Coins Banner", DOUBLE_COINS_BANNER_TEMPLATE, CAPTCHA_BANNER_TEMPLATE):
            raise SystemExit(1)

    buy_boost_if_available(ctx, tap_fast_start_0_if_visible)
    buy_boost_if_available(ctx, tap_cookie_relay_0_if_visible)

    if not args.skip_top_row_boosts:
        tap_double_xp_if_visible(ctx)
        tap_power_jelly_boost_if_visible(ctx)
        tap_hp_extension_if_visible(ctx)

    run_after_start(ctx, args.mode, args.no_cookie_relay, args.episode)

    if not tap_result_ok_button(ctx):
        raise SystemExit(1)

    if tap_open_all_mystery_box_button(ctx):
        tap_confirm_mystery_box_button(ctx)

    tap_level_up_confirm_button(ctx)


def main() -> None:
    args = parse_args()
    device = AvdDevice.from_env()
    from avd_runner.capture import WindowCapture

    capture = WindowCapture(device_size=device.screen_size())
    ctx = AutoRunnerContext(
        device=device,
        capture=capture,
        captcha_enabled=not args.no_captcha,
    )
    if args.debug_window:
        from avd_runner.debugview import DebugView

        ctx.debug_view = DebugView(capture=capture)
        device.on_gesture = ctx.debug_view.mark_swipe
    debug_session = None
    if args.debug:
        debug_session = REPO_ROOT / "debug" / time.strftime("%Y%m%d_%H%M%S")
        print(f"Debug tap captures -> {debug_session}")
    run_number = 1

    try:
        while True:
            if debug_session is not None:
                ctx.debug_run_dir = debug_session / f"run{run_number}"
                ctx.debug_tap_count = 0
            print(f"Starting run {run_number}")
            run_once(ctx, args)
            print(f"Finished run {run_number}")

            if args.loop_count is not None:
                if run_number >= args.loop_count:
                    break
            elif not args.loop:
                break

            run_number += 1
            wait(args.loop_delay)
    finally:
        if ctx.debug_view is not None:
            ctx.debug_view.close()
        capture.close()


if __name__ == "__main__":
    main()
