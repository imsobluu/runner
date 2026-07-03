import argparse
import json
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from avd_runner import AvdDevice, find_template, solve_captcha, wait
from avd_runner.recording import (
    load_ldplayer_record,
    load_taps,
    play_recorded_taps,
    record_taps,
)


ASSETS = REPO_ROOT / "assets"
CAPTCHA_BANNER_TEMPLATE = ASSETS / "captcha_banner.png"

# The anti-bot captcha can appear on any menu/transition screen, so every
# screenshot-driven helper checks for it. Toggled off by --no-captcha.
_captcha_enabled = True
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
RUN_RECORDING_PATH = REPO_ROOT / "recordings" / "auto_runner.json"
LDPLAYER_RECORDING_PATH = REPO_ROOT / "recordings" / "my_script(4).record"


def solve_captcha_if_present(device: AvdDevice, screen: bytes) -> bool:
    """Solve the anti-bot captcha if the given screenshot shows it.

    Reuses screenshot bytes the caller already captured, so it adds no extra
    screencaps on the common path where no captcha is present.
    """
    if not _captcha_enabled:
        return False
    if find_template(screen, CAPTCHA_BANNER_TEMPLATE, threshold=0.9) is None:
        return False

    print("Anti-bot captcha detected; solving.")
    if not solve_captcha(device, banner_template=CAPTCHA_BANNER_TEMPLATE):
        print("Failed to solve captcha.")
        raise SystemExit(1)
    return True


def tap_template(
    device: AvdDevice,
    name: str,
    template_path: Path,
    threshold: float = 0.85,
    attempts: int = 5,
    delay_seconds: float = 0.5,
    save_debug: bool = False,
) -> bool:
    attempt = 0
    while attempt < attempts:
        screen = device.screenshot_bytes()
        match = find_template(screen, template_path, threshold=threshold)

        if match:
            device.tap(match.center_x, match.center_y)
            print(
                f"Tapped {name} at {match.center_x}, {match.center_y} "
                f"score={match.score:.3f}"
            )
            return True

        # A captcha covering the screen is why the template is missing; solve
        # it and retry without spending an attempt.
        if solve_captcha_if_present(device, screen):
            continue

        attempt += 1
        print(f"{name} not found on attempt {attempt}/{attempts}")
        wait(delay_seconds)

    if save_debug:
        debug_path = REPO_ROOT / "screenshots" / f"{template_path.stem}_not_found.png"
        device.save_screenshot(debug_path)
        print(f"Saved {debug_path}")
    return False


def tap_play_button(
    device: AvdDevice,
    attempts: int = 5,
) -> bool:
    return tap_template(device, "Play", PLAY_BUTTON_TEMPLATE, attempts=attempts)


def tap_play_with_double_coins_button(
    device: AvdDevice,
    attempts: int = 5,
) -> bool:
    return tap_template(
        device,
        "Play with Double Coins",
        PLAY_WITH_DOUBLE_COINS_TEMPLATE,
        attempts=attempts,
    )


def has_template(
    device: AvdDevice,
    name: str,
    template_path: Path,
    threshold: float = 0.85,
) -> bool:
    screen = device.screenshot_bytes()
    match = find_template(screen, template_path, threshold=threshold)
    if not match:
        solve_captcha_if_present(device, screen)
        return False

    print(f"{name} already visible score={match.score:.3f}")
    return True


def wait_for_template(
    device: AvdDevice,
    name: str,
    template_path: Path,
    threshold: float = 0.85,
    attempts: int = 120,
    delay_seconds: float = 1.0,
) -> bool:
    attempt = 0
    while attempt < attempts:
        screen = device.screenshot_bytes()
        match = find_template(screen, template_path, threshold=threshold)
        if match:
            print(f"Found {name} score={match.score:.3f}")
            return True

        if solve_captcha_if_present(device, screen):
            continue

        attempt += 1
        print(f"{name} not found on attempt {attempt}/{attempts}")
        wait(delay_seconds)

    return False


def tap_random_boost_button(
    device: AvdDevice,
    attempts: int = 5,
    save_debug: bool = False,
) -> bool:
    if has_template(device, "Random Boost Selected", RANDOM_BOOST_SELECTED_TEMPLATE):
        return True

    return tap_template(
        device,
        "Random Boost",
        RANDOM_BOOST_TEMPLATE,
        attempts=attempts,
        save_debug=save_debug,
    )


def should_skip_random_boost_page(device: AvdDevice) -> bool:
    return has_template(device, "Double Coins Banner", DOUBLE_COINS_BANNER_TEMPLATE)


def tap_multi_button(
    device: AvdDevice,
    attempts: int = 5,
    save_debug: bool = False,
) -> bool:
    return tap_template(
        device,
        "Multi",
        MULTI_BUTTON_TEMPLATE,
        attempts=attempts,
        save_debug=save_debug,
    )


def tap_multi_buy_button(
    device: AvdDevice,
    attempts: int = 5,
    save_debug: bool = False,
) -> bool:
    return tap_template(
        device,
        "Multi Buy",
        MULTI_BUY_BUTTON_TEMPLATE,
        attempts=attempts,
        save_debug=save_debug,
    )


def tap_double_coins_button(
    device: AvdDevice,
    attempts: int = 5,
    save_debug: bool = False,
) -> bool:
    if has_template(
        device,
        "Double Coins Selected",
        DOUBLE_COINS_SELECTED_TEMPLATE,
        threshold=0.99,
    ):
        return True

    return tap_template(
        device,
        "Double Coins",
        DOUBLE_COINS_TEMPLATE,
        attempts=attempts,
        save_debug=save_debug,
    )


def tap_fast_start_0_if_visible(device: AvdDevice) -> bool:
    return tap_template(
        device,
        "Fast Start 0",
        FAST_START_0_TEMPLATE,
        threshold=0.99,
        attempts=1,
    )


def tap_cookie_relay_0_if_visible(device: AvdDevice) -> bool:
    return tap_template(
        device,
        "Cookie Relay 0",
        COOKIE_RELAY_0_TEMPLATE,
        threshold=0.99,
        attempts=1,
    )


def tap_double_xp_if_visible(device: AvdDevice) -> bool:
    return tap_template(device, "Double XP", DOUBLE_XP_TEMPLATE, attempts=1)


def tap_power_jelly_boost_if_visible(device: AvdDevice) -> bool:
    return tap_template(
        device,
        "Power Jelly Boost",
        POWER_JELLY_BOOST_TEMPLATE,
        attempts=1,
    )


def tap_hp_extension_if_visible(device: AvdDevice) -> bool:
    return tap_template(device, "HP Extension", HP_EXTENSION_TEMPLATE, attempts=1)


def tap_boost_buy_button(device: AvdDevice) -> bool:
    return tap_template(device, "Boost Buy", BOOST_BUY_BUTTON_TEMPLATE)


def tap_result_ok_button(device: AvdDevice) -> bool:
    return tap_template(device, "Result OK", RESULT_OK_BUTTON_TEMPLATE, attempts=120)


def tap_open_all_mystery_box_button(device: AvdDevice) -> bool:
    return tap_template(
        device,
        "Open All Mystery Box",
        OPEN_ALL_MYSTERY_BOX_BUTTON_TEMPLATE,
        attempts=10,
    )


def tap_confirm_mystery_box_button(device: AvdDevice) -> bool:
    return tap_template(
        device,
        "Confirm Mystery Box",
        CONFIRM_MYSTERY_BOX_BUTTON_TEMPLATE,
        attempts=10,
    )

def tap_level_up_confirm_button(device: AvdDevice) -> bool:
    return tap_template(
        device,
        "Level Up Confirm",
        LEVEL_UP_CONFIRM_BUTTON_TEMPLATE,
        attempts=10,
    )


def monitor_activate_cookie_relay(
    device: AvdDevice,
    stop_event: threading.Event,
    interval_seconds: float,
) -> None:
    while not stop_event.is_set():
        screen = device.screenshot_bytes()
        match = find_template(screen, ACTIVATE_COOKIE_RELAY_TEMPLATE, threshold=0.85)
        if match:
            device.tap(match.center_x, match.center_y)
            print(
                f"Tapped Activate Cookie Relay at {match.center_x}, {match.center_y} "
                f"score={match.score:.3f}"
            )
            stop_event.set()
            return

        stop_event.wait(interval_seconds)


def load_anchors(recording_path: Path) -> list[dict]:
    """Load re-sync checkpoints for a recording, if any.

    An anchors file lives next to the recording as `<name>.anchors.json`:

        {"anchors": [
            {"after_tap": 12, "template": "double_coins_banner.png", "timeout": 30}
        ]}

    `after_tap` is the 1-based tap index printed during recording ("Recorded
    tap N"); playback pauses after that tap until `template` (relative to
    assets/) is on screen, or aborts after `timeout` seconds (default 30).
    """
    path = recording_path.with_name(recording_path.name + ".anchors.json")
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["anchors"]


def split_taps_at_anchors(taps: list, anchors: list[dict]) -> list[tuple[list, dict | None]]:
    """Split taps into (segment, anchor) pairs; the final segment has no anchor."""
    segments: list[tuple[list, dict | None]] = []
    start = 0
    for anchor in sorted(anchors, key=lambda a: a["after_tap"]):
        end = min(max(int(anchor["after_tap"]), start), len(taps))
        segments.append((taps[start:end], anchor))
        start = end
    segments.append((taps[start:], None))
    return segments


def run_after_start(
    device: AvdDevice,
    mode: str,
    recording_path: Path,
    speed: float,
    stop_on_cookie_relay: bool,
    cookie_relay_check_interval: float,
) -> None:
    if mode == "record":
        record_taps(device, recording_path)
        return

    if not recording_path.exists():
        print(f"Recording not found: {recording_path}")
        raise SystemExit(1)

    stop_event = threading.Event()
    if stop_on_cookie_relay:
        monitor = threading.Thread(
            target=monitor_activate_cookie_relay,
            args=(device, stop_event, cookie_relay_check_interval),
            daemon=True,
        )
        monitor.start()

    if mode == "ldplayer":
        taps = load_ldplayer_record(recording_path, target_size=device.screen_size())
    else:
        taps = load_taps(recording_path)

    synced = True
    for segment, anchor in split_taps_at_anchors(taps, load_anchors(recording_path)):
        play_recorded_taps(device, segment, speed, stop_event=stop_event)
        if stop_event.is_set() or anchor is None:
            break
        # Re-sync on the anchor before the next segment; wait_for_template
        # also solves any captcha that popped up mid-playback.
        if not wait_for_template(
            device,
            anchor["template"],
            ASSETS / anchor["template"],
            attempts=int(anchor.get("timeout", 30)),
        ):
            print(f"Anchor {anchor['template']} not found after tap {anchor['after_tap']}.")
            synced = False
            break

    stop_event.set()
    if not synced:
        raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Cookie Run setup bot.")
    parser.add_argument(
        "--mode",
        choices=("ldplayer", "playback", "record"),
        default="ldplayer",
        help="Replay an LDPlayer .record, replay JSON taps, or record new JSON taps.",
    )
    parser.add_argument(
        "--recording",
        type=Path,
        help="Path to the recording file.",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Playback speed multiplier. Use values below 1.0 to slow down.",
    )
    parser.add_argument(
        "--stop-on-cookie-relay",
        action="store_true",
        help="During playback, tap activate_cookie_relay.png if found and stop playback.",
    )
    parser.add_argument(
        "--cookie-relay-check-interval",
        type=float,
        default=2.0,
        help="Seconds between activate_cookie_relay.png checks during playback.",
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
    args = parser.parse_args()
    if args.loop_count is not None and args.loop_count < 1:
        parser.error("--loop-count must be at least 1")
    if args.recording is None:
        args.recording = LDPLAYER_RECORDING_PATH if args.mode == "ldplayer" else RUN_RECORDING_PATH
    return args


def run_once(device: AvdDevice, args: argparse.Namespace) -> None:
    if not tap_play_button(device):
        raise SystemExit(1)

    wait(1.0)
    if not should_skip_random_boost_page(device):
        if not tap_random_boost_button(device):
            raise SystemExit(1)

        wait(0.5)
        if not tap_multi_button(device):
            raise SystemExit(1)

        wait(0.5)
        if not tap_double_coins_button(device):
            raise SystemExit(1)

        wait(0.5)
        if not tap_multi_buy_button(device):
            raise SystemExit(1)

    if not wait_for_template(device, "Double Coins Banner", DOUBLE_COINS_BANNER_TEMPLATE):
        raise SystemExit(1)

    if tap_fast_start_0_if_visible(device):
        wait(0.5)
        if not tap_boost_buy_button(device):
            raise SystemExit(1)

    wait(0.5)

    if tap_cookie_relay_0_if_visible(device):
        wait(0.5)
        if not tap_boost_buy_button(device):
            raise SystemExit(1)

    wait(0.5)
    tap_double_xp_if_visible(device)

    wait(0.5)
    tap_power_jelly_boost_if_visible(device)

    wait(0.5)
    tap_hp_extension_if_visible(device)

    run_after_start(
        device,
        args.mode,
        args.recording,
        args.speed,
        args.stop_on_cookie_relay,
        args.cookie_relay_check_interval,
    )

    wait(0.5)
    if not tap_result_ok_button(device):
        raise SystemExit(1)

    wait(0.5)
    if not tap_open_all_mystery_box_button(device):
        raise SystemExit(1)

    wait(0.5)
    if not tap_confirm_mystery_box_button(device):
        raise SystemExit(1)

    wait(0.5)
    # The level-up dialog only appears on some runs, so a miss is fine.
    tap_level_up_confirm_button(device)


def main() -> None:
    global _captcha_enabled
    args = parse_args()
    _captcha_enabled = not args.no_captcha
    device = AvdDevice.from_env()
    run_number = 1

    while True:
        print(f"Starting run {run_number}")
        run_once(device, args)
        print(f"Finished run {run_number}")

        if args.loop_count is not None:
            if run_number >= args.loop_count:
                break
        elif not args.loop:
            break

        run_number += 1
        wait(args.loop_delay)


if __name__ == "__main__":
    main()
