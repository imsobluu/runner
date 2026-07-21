import argparse
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from collections.abc import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from avd_runner import AvdDevice, find_template, wait
from avd_runner.debug_session import DebugSession
from avd_runner.menu import (
    MenuAutomationError,
    debug_save_tap,
    is_toggle_selected,
    tap_template,
    wait_for_any_template,
    wait_for_template,
)
from avd_runner.mystery_box import (
    MysteryBoxCapture,
    MysteryBoxOCRError,
    MysteryBoxTargetReached,
)


ASSETS = REPO_ROOT / "assets"
CAPTCHA_BANNER_TEMPLATE = ASSETS / "captcha_banner.png"

@dataclass
class AutoRunnerContext:
    device: AvdDevice
    capture: object
    debug: DebugSession
    captcha_enabled: bool = True


class RunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class TemplateTarget:
    name: str
    path: Path
    threshold: float = 0.85
    attempts: int = 5
    verify_gone: bool = False


PLAY_BUTTON_TEMPLATE = ASSETS / "play_button.png"
PLAY_WITH_DOUBLE_COINS_TEMPLATE = ASSETS / "play_with_double_coins.png"
RANDOM_BOOST_TEMPLATE = ASSETS / "random_boost.png"
RANDOM_BOOST_SELECTED_TEMPLATE = ASSETS / "random_boost_selected.png"
MULTI_BUTTON_TEMPLATE = ASSETS / "multi_button.png"
MULTI_BUY_BUTTON_TEMPLATE = ASSETS / "multi_buy_button.png"
CHECKBOX_TEMPLATE = ASSETS / "checkbox.png"
CHECKMARK_TEMPLATE = ASSETS / "checkmark.png"
DOUBLE_COINS_BANNER_TEMPLATE = ASSETS / "double_coins_banner.png"
FAST_START_0_TEMPLATE = ASSETS / "fast_start_0.png"
COOKIE_RELAY_0_TEMPLATE = ASSETS / "cookie_relay_0.png"
DOUBLE_XP_TEMPLATE = ASSETS / "double_xp.png"
POWER_JELLY_BOOST_TEMPLATE = ASSETS / "power_jelly_boost.png"
HP_EXTENSION_TEMPLATE = ASSETS / "hp_extension.png"
BOOST_BUY_BUTTON_TEMPLATE = ASSETS / "boost_buy_button.png"
ACTIVATE_COOKIE_RELAY_TEMPLATE = ASSETS / "activate_cookie_relay.png"
ACTIVATE_FAST_START_TEMPLATE = ASSETS / "activate_fast_start.png"
GET_ALERT_TEMPLATE = ASSETS / "get_alert.png"
RELIC_GEM_TEMPLATE = ASSETS / "relic_gem.png"
CLAIM_RELIC_BUTTON_TEMPLATE = ASSETS / "claim_relic_button.png"
CONFIRM_RELIC_BUTTON_TEMPLATE = ASSETS / "confirm_relic_button.png"
EXIT_RELIC_PAGE_BUTTON_TEMPLATE = ASSETS / "exit_relic_page_button.png"
RESULT_OK_BUTTON_TEMPLATE = ASSETS / "result_ok_button.png"
OPEN_ALL_MYSTERY_BOX_BUTTON_TEMPLATE = ASSETS / "open_all_mystery_box_button.png"
CONFIRM_MYSTERY_BOX_BUTTON_TEMPLATE = ASSETS / "confirm_mystery_box_button.png"
LEVEL_UP_CONFIRM_BUTTON_TEMPLATE = ASSETS / "level_up_confirm_button.png"
MYSTERY_BOX_TEMPLATE = ASSETS / "mystery_box.png"
PAUSE_XY = (1194, 37)
QUIT_TEMPLATE = ASSETS / "quit.png"
LEVEL_RECORDINGS_DIR = REPO_ROOT / "recordings" / "episodes"
REFERENCE_SIZE = (1280, 720)
CHECKBOX_HALF_SIZE = (28, 24)
CHECKBOX_READY_SCORE = 0.80
CHECKBOX_SCORE_MARGIN = 0.05

RANDOM_BOOSTS = {
    "double-coins": ("Double Coins", (284, 175)),
    "score-bonus": ("15% score bonus", (665, 175)),
    "hp-drain-reduction": ("-15% HP drain", (284, 224)),
    "revive": ("Revive once with 80 HP", (665, 224)),
    "crush-chance": ("70% Crush Chance", (284, 274)),
    "base-speed": ("+17% base speed", (665, 274)),
    "gold-coin-magic": ("Gold Coin Magic", (284, 323)),
    "collision-damage-reduction": ("-30% collision damage", (665, 323)),
    "potion-hp": ("+20% HP from potions", (284, 373)),
    "magnetic-aura": ("Magnetic Aura", (665, 373)),
    "pit-lifts": ("2 Pit Lifts", (284, 423)),
}

PLAY_TARGET = TemplateTarget("Play", PLAY_BUTTON_TEMPLATE)
PLAY_WITH_DOUBLE_COINS_TARGET = TemplateTarget(
    "Play with Double Coins",
    PLAY_WITH_DOUBLE_COINS_TEMPLATE,
    verify_gone=True,
)
RANDOM_BOOST_TARGET = TemplateTarget("Random Boost", RANDOM_BOOST_TEMPLATE)
MULTI_TARGET = TemplateTarget("Multi", MULTI_BUTTON_TEMPLATE)
MULTI_BUY_TARGET = TemplateTarget("Multi Buy", MULTI_BUY_BUTTON_TEMPLATE)
FAST_START_0_TARGET = TemplateTarget("Fast Start 0", FAST_START_0_TEMPLATE, threshold=0.99, attempts=1)
COOKIE_RELAY_0_TARGET = TemplateTarget("Cookie Relay 0", COOKIE_RELAY_0_TEMPLATE, threshold=0.98, attempts=1)
DOUBLE_XP_TARGET = TemplateTarget("Double XP", DOUBLE_XP_TEMPLATE, attempts=1)
POWER_JELLY_BOOST_TARGET = TemplateTarget("Power Jelly Boost", POWER_JELLY_BOOST_TEMPLATE, attempts=1)
HP_EXTENSION_TARGET = TemplateTarget("HP Extension", HP_EXTENSION_TEMPLATE, attempts=1)
BOOST_BUY_TARGET = TemplateTarget("Boost Buy", BOOST_BUY_BUTTON_TEMPLATE)
GET_ALERT_TARGET = TemplateTarget("Get Alert", GET_ALERT_TEMPLATE, attempts=1)
RELIC_GEM_TARGET = TemplateTarget("Relic Gem", RELIC_GEM_TEMPLATE)
CLAIM_RELIC_TARGET = TemplateTarget("Claim Relic", CLAIM_RELIC_BUTTON_TEMPLATE)
CONFIRM_RELIC_TARGET = TemplateTarget("Confirm Relic", CONFIRM_RELIC_BUTTON_TEMPLATE, attempts=20)
EXIT_RELIC_PAGE_TARGET = TemplateTarget("Exit Relic Page", EXIT_RELIC_PAGE_BUTTON_TEMPLATE)
RESULT_OK_TARGET = TemplateTarget("Result OK", RESULT_OK_BUTTON_TEMPLATE, attempts=120)
OPEN_ALL_MYSTERY_BOX_TARGET = TemplateTarget("Open All Mystery Box", OPEN_ALL_MYSTERY_BOX_BUTTON_TEMPLATE)
CONFIRM_MYSTERY_BOX_TARGET = TemplateTarget("Confirm Mystery Box", CONFIRM_MYSTERY_BOX_BUTTON_TEMPLATE)
LEVEL_UP_CONFIRM_TARGET = TemplateTarget("Level Up Confirm", LEVEL_UP_CONFIRM_BUTTON_TEMPLATE)
QUIT_TARGET = TemplateTarget("Quit", QUIT_TEMPLATE, attempts=120)


def tap_target(
    ctx: AutoRunnerContext,
    target: TemplateTarget,
    *,
    attempts: int | None = None,
    save_debug: bool = False,
) -> bool:
    return tap_template(
        ctx,
        target.name,
        target.path,
        CAPTCHA_BANNER_TEMPLATE,
        threshold=target.threshold,
        attempts=target.attempts if attempts is None else attempts,
        save_debug=save_debug,
        verify_gone=target.verify_gone,
    )


def tap_play_button(
    ctx: AutoRunnerContext,
    attempts: int = 5,
) -> bool:
    return tap_target(ctx, PLAY_TARGET, attempts=attempts)


def tap_play_with_double_coins_button(
    ctx: AutoRunnerContext,
    attempts: int = 5,
) -> bool:
    # The purchase-complete modal from a boost buy can swallow this tap without
    # covering the button; re-tap until the button actually goes.
    targets = (PLAY_WITH_DOUBLE_COINS_TARGET, PLAY_TARGET)
    seen = wait_for_any_template(
        ctx,
        [(target.name, target.path) for target in targets],
        CAPTCHA_BANNER_TEMPLATE,
        attempts=attempts,
    )
    for target in targets:
        if target.name == seen:
            return tap_target(ctx, target, attempts=attempts)
    return False


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

    return tap_target(ctx, RANDOM_BOOST_TARGET, attempts=attempts, save_debug=save_debug)


def tap_multi_button(
    ctx: AutoRunnerContext,
    attempts: int = 5,
    save_debug: bool = False,
) -> bool:
    return tap_target(ctx, MULTI_TARGET, attempts=attempts, save_debug=save_debug)


def tap_multi_buy_button(
    ctx: AutoRunnerContext,
    attempts: int = 5,
    save_debug: bool = False,
) -> bool:
    return tap_target(ctx, MULTI_BUY_TARGET, attempts=attempts, save_debug=save_debug)


def tap_fast_start_0_if_visible(ctx: AutoRunnerContext) -> bool:
    return tap_target(ctx, FAST_START_0_TARGET)


def tap_cookie_relay_0_if_visible(ctx: AutoRunnerContext) -> bool:
    return tap_target(ctx, COOKIE_RELAY_0_TARGET)


def tap_double_xp_if_visible(ctx: AutoRunnerContext) -> bool:
    return tap_target(ctx, DOUBLE_XP_TARGET)


def tap_power_jelly_boost_if_visible(ctx: AutoRunnerContext) -> bool:
    return tap_target(ctx, POWER_JELLY_BOOST_TARGET)


def tap_hp_extension_if_visible(ctx: AutoRunnerContext) -> bool:
    return tap_target(ctx, HP_EXTENSION_TARGET)


def tap_boost_buy_button(ctx: AutoRunnerContext) -> bool:
    return tap_target(ctx, BOOST_BUY_TARGET)


def claim_relic_if_alert(ctx: AutoRunnerContext) -> bool:
    if not tap_target(ctx, GET_ALERT_TARGET):
        return False
    if not tap_target(ctx, RELIC_GEM_TARGET):
        raise RunnerError("Get alert was visible, but relic_gem.png could not be tapped.")
    if not tap_target(ctx, CLAIM_RELIC_TARGET):
        raise RunnerError("Relic gem was tapped, but claim_relic_button.png could not be tapped.")
    if not tap_target(ctx, CONFIRM_RELIC_TARGET):
        raise RunnerError("Claim relic was tapped, but confirm_relic_button.png could not be tapped.")
    if not tap_target(ctx, EXIT_RELIC_PAGE_TARGET):
        raise RunnerError("Relic was confirmed, but exit_relic_page_button.png could not be tapped.")
    return True


def tap_result_ok_button(ctx: AutoRunnerContext) -> bool:
    return tap_target(ctx, RESULT_OK_TARGET)


def tap_open_all_mystery_box_button(ctx: AutoRunnerContext) -> bool:
    return tap_target(ctx, OPEN_ALL_MYSTERY_BOX_TARGET)


def tap_confirm_mystery_box_button(ctx: AutoRunnerContext) -> bool:
    return tap_target(ctx, CONFIRM_MYSTERY_BOX_TARGET)

def tap_level_up_confirm_button(ctx: AutoRunnerContext) -> bool:
    return tap_target(ctx, LEVEL_UP_CONFIRM_TARGET)


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
            raise RunnerError(
                f"No recordings for episode {episode!r}. Available: {available or 'none'}"
            )
        return path
    if len(available) == 1:
        return recordings_dir / available[0]
    raise RunnerError(
        f"--episode is required when there isn't exactly one recorded episode. "
        f"Available: {available or 'none'}"
    )


def build_gameplay_runner(
    ctx: AutoRunnerContext,
    mode: str,
    relay_template: Path | None,
    fast_start_template: Path | None,
    episode_dir: Path | None,
):
    if mode == "levels":
        if episode_dir is None:
            raise RunnerError("Episode recordings are required for levels mode.")
        from avd_runner.levels import LevelReplayer

        return LevelReplayer(
            ctx.device,
            ctx.capture,
            ASSETS,
            episode_dir,
            exit_template=RESULT_OK_BUTTON_TEMPLATE,
            relay_template=relay_template,
            fast_start_template=fast_start_template,
            on_tap=ctx.debug.save_tap if ctx.debug.enabled_for_tap_saves else None,
            debug_view=ctx.debug.view,
        )
    if mode == "reactive":
        from avd_runner.reactive import ReactiveRunner

        return ReactiveRunner(
            ctx.device,
            ctx.capture,
            ASSETS / "witch_oven",
            exit_template=RESULT_OK_BUTTON_TEMPLATE,
            relay_template=relay_template,
            fast_start_template=fast_start_template,
            debug_view=ctx.debug.view,
        )
    if mode == "none":
        from avd_runner.none import NoneRunner

        return NoneRunner(
            ctx.device,
            ctx.capture,
            exit_template=RESULT_OK_BUTTON_TEMPLATE,
            relay_template=relay_template,
            fast_start_template=fast_start_template,
            debug_view=ctx.debug.view,
        )
    raise RunnerError(f"Unknown gameplay mode: {mode}")


def run_after_start(
    ctx: AutoRunnerContext,
    mode: str,
    no_cookie_relay: bool,
    fast_start: bool,
    episode: str | None,
    quit_on_collect_mystery_box: int | None = None,
) -> None:
    # Resolve before tapping Play so a missing episode fails without
    # starting (and wasting) a run.
    episode_dir = resolve_episode_dir(episode) if mode == "levels" else None
    relay_template = None if no_cookie_relay else ACTIVATE_COOKIE_RELAY_TEMPLATE
    fast_start_template = ACTIVATE_FAST_START_TEMPLATE if fast_start else None

    # The gameplay drivers take over after the boost screen's final Play button.
    if not tap_play_with_double_coins_button(ctx):
        raise RunnerError()

    runner_ctx = ctx
    if quit_on_collect_mystery_box is not None:
        runner_ctx = replace(
            ctx,
            capture=MysteryBoxCapture(
                ctx.capture,
                MYSTERY_BOX_TEMPLATE,
                quit_on_collect_mystery_box,
            ),
        )

    runner = build_gameplay_runner(
        runner_ctx,
        mode,
        relay_template,
        fast_start_template,
        episode_dir,
    )
    try:
        completed = runner.run()
    except MysteryBoxTargetReached as exc:
        print(str(exc))
        quit_gameplay(ctx)
        completed = True
    except MysteryBoxOCRError as exc:
        raise RunnerError(str(exc)) from exc
    if not completed:
        raise RunnerError()


def _read_menu_key() -> str:
    import msvcrt

    key = msvcrt.getwch()
    if key in ("\x00", "\xe0"):
        return {"H": "up", "P": "down"}.get(msvcrt.getwch(), "")
    return {
        "\r": "\r",
        "\x08": "backspace",
        "\x1b": "escape",
    }.get(key, key)


def select_random_boost(read_key=None, write=None) -> str | None:
    read_key = _read_menu_key if read_key is None else read_key
    write = sys.stdout.write if write is None else write
    boosts = list(RANDOM_BOOSTS.items())
    selected = 0
    digits = ""
    rendered = False

    while True:
        if rendered:
            write(f"\x1b[{len(boosts) + 2}F")
        write("Select one Random Boost (arrows/numbers, Enter confirms):\n")
        for number, (_slug, (label, _xy)) in enumerate(boosts, 1):
            marker = ">" if number - 1 == selected else " "
            write(f"{marker} {number:2}. {label}\n")
        write("Esc cancels\n")
        rendered = True

        key = read_key()
        if key == "up":
            selected = max(0, selected - 1)
            digits = ""
        elif key == "down":
            selected = min(len(boosts) - 1, selected + 1)
            digits = ""
        elif key == "backspace":
            digits = ""
        elif key == "escape":
            return None
        elif key == "\r":
            return boosts[selected][0]
        elif key.isdigit():
            candidate = digits + key
            number = int(candidate)
            if 1 <= number <= len(boosts):
                digits = candidate
                selected = number - 1
            elif key != "0":
                digits = key
                selected = int(key) - 1


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
        "recordings/episodes/). Defaults to the only recorded episode.",
    )
    parser.add_argument(
        "--no-cookie-relay",
        action="store_true",
        help="Don't tap activate_cookie_relay.png when it appears mid-run "
        "(all gameplay modes tap it by default).",
    )
    parser.add_argument(
        "--fast-start",
        action="store_true",
        help="Tap Activate Fast Start when it appears during gameplay.",
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
        "--random-boost",
        nargs="?",
        const="",
        metavar="BOOST",
        help="Select a Random Boost by kebab-case name; omit BOOST for an interactive menu.",
    )
    parser.add_argument(
        "--quit-on-collect-mystery-box",
        type=int,
        help="Pause and quit gameplay after collecting exactly this many mystery boxes.",
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
    if args.random_boost == "":
        try:
            args.random_boost = select_random_boost()
        except (EOFError, OSError, ImportError):
            parser.error("Interactive Random Boost selection needs a Windows console")
        if args.random_boost is None:
            parser.error("Random Boost selection cancelled")
    elif args.random_boost is not None and args.random_boost not in RANDOM_BOOSTS:
        parser.error(
            "--random-boost must be one of: " + ", ".join(RANDOM_BOOSTS)
        )
    if args.loop_count is not None and args.loop_count < 1:
        parser.error("--loop-count must be at least 1")
    if (
        args.quit_on_collect_mystery_box is not None
        and args.quit_on_collect_mystery_box < 1
    ):
        parser.error("--quit-on-collect-mystery-box must be at least 1")
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
        raise RunnerError()
    if not wait_for_template(ctx, "Double Coins Banner", DOUBLE_COINS_BANNER_TEMPLATE, CAPTCHA_BANNER_TEMPLATE):
        raise RunnerError()


def _checkbox_is_checked(crop) -> bool:
    checked = find_template(crop, CHECKMARK_TEMPLATE, threshold=-1.0)
    empty = find_template(crop, CHECKBOX_TEMPLATE, threshold=-1.0)
    checked_score = checked.score if checked else 0.0
    empty_score = empty.score if empty else 0.0
    if (
        max(checked_score, empty_score) < CHECKBOX_READY_SCORE
        or abs(checked_score - empty_score) < CHECKBOX_SCORE_MARGIN
    ):
        raise RunnerError(
            f"Ambiguous boost checkbox: checked={checked_score:.3f} "
            f"empty={empty_score:.3f}"
        )
    return checked_score > empty_score


def checked_random_boosts(screen) -> set[str]:
    height, width = screen.shape[:2]
    sx = width / REFERENCE_SIZE[0]
    sy = height / REFERENCE_SIZE[1]
    half_width, half_height = CHECKBOX_HALF_SIZE
    checked = set()
    for slug, (_label, (x, y)) in RANDOM_BOOSTS.items():
        x1 = round((x - half_width) * sx)
        y1 = round((y - half_height) * sy)
        x2 = round((x + half_width) * sx)
        y2 = round((y + half_height) * sy)
        if _checkbox_is_checked(screen[y1:y2, x1:x2]):
            checked.add(slug)
    return checked


def random_boosts_to_toggle(checked: set[str], desired: str) -> list[str]:
    return [
        slug
        for slug in RANDOM_BOOSTS
        if (slug == desired) != (slug in checked)
    ]


def reconcile_random_boost_checkboxes(
    ctx: AutoRunnerContext,
    desired: str,
) -> None:
    screen = ctx.capture.grab()
    for slug in random_boosts_to_toggle(checked_random_boosts(screen), desired):
        label, (x, y) = RANDOM_BOOSTS[slug]
        tx, ty = ctx.device.tap(x, y, label=label)
        debug_save_tap(ctx, label, screen, tx, ty)
        wait(0.2)
    final_checked = checked_random_boosts(ctx.capture.grab())
    if final_checked != {desired}:
        raise RunnerError(
            "Random Boost checkbox verification failed: "
            + ", ".join(sorted(final_checked))
        )


def ensure_random_boost_setup(ctx: AutoRunnerContext, desired: str) -> None:
    seen = wait_for_any_template(
        ctx,
        [
            ("Random Boost Selected", RANDOM_BOOST_SELECTED_TEMPLATE),
            ("Random Boost", RANDOM_BOOST_TEMPLATE),
        ],
        CAPTCHA_BANNER_TEMPLATE,
    )
    if seen is None:
        raise RunnerError("The boost-selection screen did not appear.")
    if not tap_random_boost_button(ctx):
        raise RunnerError("Could not select Random Boost.")
    if not tap_multi_button(ctx):
        raise RunnerError("Could not open Multi selection.")
    reconcile_random_boost_checkboxes(ctx, desired)
    if not tap_multi_buy_button(ctx):
        raise RunnerError("Could not tap Multi-Buy.")
    if wait_for_any_template(
        ctx,
        [
            ("Random Boost Selected", RANDOM_BOOST_SELECTED_TEMPLATE),
            ("Random Boost", RANDOM_BOOST_TEMPLATE),
        ],
        CAPTCHA_BANNER_TEMPLATE,
    ) is None:
        raise RunnerError("Boost store did not reappear after Multi-Buy.")


def buy_optional_boosts(ctx: AutoRunnerContext, skip_top_row_boosts: bool) -> None:
    buy_boost_if_available(ctx, tap_fast_start_0_if_visible)
    buy_boost_if_available(ctx, tap_cookie_relay_0_if_visible)

    if not skip_top_row_boosts:
        tap_double_xp_if_visible(ctx)
        tap_power_jelly_boost_if_visible(ctx)
        tap_hp_extension_if_visible(ctx)


def clear_results(ctx: AutoRunnerContext) -> None:
    if not tap_result_ok_button(ctx):
        raise RunnerError()

    if tap_open_all_mystery_box_button(ctx):
        tap_confirm_mystery_box_button(ctx)

    tap_level_up_confirm_button(ctx)


def quit_gameplay(ctx: AutoRunnerContext) -> None:
    ctx.device.tap(*PAUSE_XY, label="Pause")
    for target in (QUIT_TARGET, QUIT_TARGET):
        if not tap_target(ctx, target):
            raise RunnerError(
                f"Could not tap {target.path.name} while quitting gameplay."
            )


def run_once(ctx: AutoRunnerContext, args: argparse.Namespace) -> None:
    claim_relic_if_alert(ctx)
    if not tap_play_button(ctx):
        raise RunnerError()

    if args.random_boost is None:
        wait(0.5)
    else:
        ensure_random_boost_setup(ctx, args.random_boost)

    buy_optional_boosts(ctx, args.skip_top_row_boosts)
    run_after_start(
        ctx,
        args.mode,
        args.no_cookie_relay,
        args.fast_start,
        args.episode,
        args.quit_on_collect_mystery_box,
    )
    clear_results(ctx)


def main() -> None:
    args = parse_args()
    device = AvdDevice.from_env()
    from avd_runner.capture import WindowCapture

    if device.input_screen_size() != device.screen_size():
        logical_width, logical_height = device.screen_size()
        input_width, input_height = device.input_screen_size()
        print(
            f"Scaling input coordinates {logical_width}x{logical_height} -> "
            f"{input_width}x{input_height}"
        )
    capture = WindowCapture(device_size=device.screen_size())
    debug_root = None
    if args.debug:
        debug_root = REPO_ROOT / "debug" / time.strftime("%Y%m%d_%H%M%S")
        print(f"Debug tap captures -> {debug_root}")
    debug = DebugSession(capture=capture, window=args.debug_window, root=debug_root)
    debug.attach_device(device)
    ctx = AutoRunnerContext(
        device=device,
        capture=capture,
        debug=debug,
        captcha_enabled=not args.no_captcha,
    )
    run_number = 1

    try:
        while True:
            ctx.debug.start_run(run_number)
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
    except (MenuAutomationError, RunnerError) as exc:
        if str(exc):
            print(str(exc))
        raise SystemExit(1)
    finally:
        ctx.debug.close()
        capture.close()


if __name__ == "__main__":
    main()
