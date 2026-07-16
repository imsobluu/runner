"""Debug jump timing with one play button and episode obstacle templates.

This harness is for tuning the trigger line. It taps assets/play_button.png,
then runs ReactiveRunner with obstacles from:

    extracted_sprites/epN01/epN01_tm01

The debug window shows the search region, trigger line, candidate box, action
box, and ADB swipe markers.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from avd_runner import AvdDevice
from avd_runner.capture import WindowCapture
from avd_runner.debugview import DebugView
from avd_runner.reactive import ReactiveRunner
from avd_runner.vision import find_template_multiscale

from launch_mumu_cookierun import (
    VISION_REFERENCE_SIZE,
    configured_instances,
    connect_adb,
    find_mumu_adb,
    find_mumu_manager,
    instance_adb_serial,
    instance_device_size,
    mumu_window_for_serial,
    scale_vision_point,
)


RESULT_OK_BUTTON_TEMPLATE = REPO_ROOT / "assets" / "result_ok_button.png"
DEFAULT_PLAY_TEMPLATE = REPO_ROOT / "assets" / "play_button.png"
DEFAULT_OBSTACLE_DIR = (
    REPO_ROOT
    / "extracted_sprites"
    / "epN01"
    / "epN01_tm01"
)
TIMING_THEME_DIR = REPO_ROOT / "debug" / "reactive_timing"


def parse_device_size(value: str) -> tuple[int, int]:
    raw = value.lower().replace("x", " ").replace(",", " ").split()
    if len(raw) != 2:
        raise argparse.ArgumentTypeError("expected WIDTHxHEIGHT")
    try:
        width, height = (int(part) for part in raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected WIDTHxHEIGHT") from exc
    if width < 1 or height < 1:
        raise argparse.ArgumentTypeError("width and height must be positive")
    return width, height


def choose_instance(manager: Path) -> int:
    instances = configured_instances(manager)
    if not instances:
        raise SystemExit("No MuMu instances found in the manager vms directory.")

    print("MuMu instances:")
    for instance in instances:
        serial = instance_adb_serial(manager, instance) or "no adb port found"
        print(f"  {instance}: {serial}")

    while True:
        value = input("Choose instance: ").strip()
        try:
            instance = int(value)
        except ValueError:
            print("Enter a numeric instance id.")
            continue
        if instance in instances:
            return instance
        print(f"Instance {instance} is not in: {', '.join(map(str, instances))}")


def prepare_obstacle_theme(obstacle_dir: Path) -> Path:
    if not obstacle_dir.exists() or not obstacle_dir.is_dir():
        raise SystemExit(f"Obstacle directory does not exist: {obstacle_dir}")
    TIMING_THEME_DIR.mkdir(parents=True, exist_ok=True)
    for old in TIMING_THEME_DIR.glob("*.png"):
        old.unlink()

    copied = 0
    for source in sorted(obstacle_dir.glob("*.png")):
        stem = source.stem
        if "noti" in stem:
            continue
        if "_jp" in stem:
            target = TIMING_THEME_DIR / f"{stem}_jump.png"
        elif "_sd" in stem:
            target = TIMING_THEME_DIR / f"{stem}_slide.png"
        else:
            continue
        shutil.copy2(source, target)
        copied += 1
    if copied == 0:
        raise SystemExit(f"No *_jp*.png or *_sd*.png obstacle sprites found in {obstacle_dir}")
    print(f"Copied {copied} obstacle templates into {TIMING_THEME_DIR}")
    return TIMING_THEME_DIR


def tap_play_button(
    *,
    adb_path: str,
    serial: str,
    capture: WindowCapture,
    debug_view: DebugView,
    device_size: tuple[int, int],
    play_template: Path,
    timeout_seconds: float,
    threshold: float,
) -> bool:
    if not play_template.exists():
        raise SystemExit(f"Play template does not exist: {play_template}")

    device = AvdDevice(serial=serial, adb_path=adb_path, device_size=device_size)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        frame = capture.grab()
        match = find_template_multiscale(frame, play_template, threshold=threshold)
        if match is not None:
            x1 = match.center_x - match.width // 2
            y1 = match.center_y - match.height // 2
            x2 = x1 + match.width
            y2 = y1 + match.height
            debug_view.update(
                frame,
                [(x1, y1, x2, y2, f"{play_template.name} {match.score:.3f}", (255, 0, 0))],
            )
            tap_x, tap_y = scale_vision_point(match.center_x, match.center_y, device_size)
            device.tap(tap_x, tap_y, label=play_template.stem)
            debug_view.mark_tap(match.center_x, match.center_y, play_template.stem)
            print(f"{serial}: tapped {play_template.name} score={match.score:.3f} at {tap_x},{tap_y}")
            return True
        debug_view.update(frame, [])
        time.sleep(0.2)

    print(f"{serial}: timed out waiting for {play_template}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tap assets/play_button.png and run epN01_tm01 obstacle timing debug.",
    )
    parser.add_argument("--manager", help="Path to MuMuNxMain.exe / MuMu manager.")
    parser.add_argument("--adb", help="Path to adb.exe. Defaults to MuMu adb when --manager is set.")
    parser.add_argument("--instance", type=int, help="MuMu instance id. If omitted, prompts.")
    parser.add_argument("--serial", help="ADB serial, e.g. 127.0.0.1:16384.")
    parser.add_argument("--device-size", type=parse_device_size, help="Device input resolution, e.g. 960x540.")
    parser.add_argument("--play-template", type=Path, default=DEFAULT_PLAY_TEMPLATE)
    parser.add_argument("--obstacle-dir", type=Path, default=DEFAULT_OBSTACLE_DIR)
    parser.add_argument("--play-timeout", type=float, default=30.0)
    parser.add_argument("--reactive-timeout", type=float, default=120.0)
    parser.add_argument("--threshold", type=float, default=0.85, help="Play button template threshold.")
    args = parser.parse_args()

    manager = find_mumu_manager(args.manager)
    if manager is None and (args.serial is None or args.adb is None):
        raise SystemExit("Provide --manager, or provide both --serial and --adb.")

    instance = args.instance
    if args.serial is None:
        assert manager is not None
        if instance is None:
            instance = choose_instance(manager)
        serial = instance_adb_serial(manager, instance)
        if serial is None:
            raise SystemExit(f"Could not find ADB serial for MuMu instance {instance}.")
    else:
        serial = args.serial

    adb_path = args.adb
    if adb_path is None:
        assert manager is not None
        adb_path = find_mumu_adb(manager, None)
    if adb_path is None:
        raise SystemExit("Could not find adb.exe. Pass --adb explicitly.")

    if args.device_size is not None:
        device_size = args.device_size
    elif manager is not None and instance is not None:
        device_size = instance_device_size(manager, instance) or VISION_REFERENCE_SIZE
    else:
        device_size = VISION_REFERENCE_SIZE

    obstacle_dir = args.obstacle_dir.resolve()
    theme_dir = prepare_obstacle_theme(obstacle_dir)
    print(f"serial: {serial}")
    print(f"adb: {adb_path}")
    print(f"device size: {device_size[0]}x{device_size[1]}")
    print(f"play template: {args.play_template.resolve()}")
    print(f"obstacle dir: {obstacle_dir}")
    print(f"timing theme: {theme_dir}")

    if not connect_adb(adb_path, serial, timeout_seconds=30, dry_run=False):
        raise SystemExit(f"Could not connect ADB to {serial}.")

    hwnd = mumu_window_for_serial(serial)
    if hwnd is None:
        raise SystemExit(f"Could not find MuMu window for {serial}. Is the instance running?")

    capture = WindowCapture(window_hwnd=hwnd, device_size=VISION_REFERENCE_SIZE, first_frame_timeout=5)
    debug_view = DebugView(title=f"jump timing debug {serial}", capture=capture, fps=30)
    device = AvdDevice(
        serial=serial,
        adb_path=adb_path,
        device_size=device_size,
        on_gesture=debug_view.mark_swipe,
    )

    try:
        if not tap_play_button(
            adb_path=adb_path,
            serial=serial,
            capture=capture,
            debug_view=debug_view,
            device_size=device_size,
            play_template=args.play_template.resolve(),
            timeout_seconds=args.play_timeout,
            threshold=args.threshold,
        ):
            return 1

        time.sleep(1.0)
        runner = ReactiveRunner(
            device,
            capture,
            theme_dir,
            exit_template=RESULT_OK_BUTTON_TEMPLATE,
            debug_view=debug_view,
            frame_size=VISION_REFERENCE_SIZE,
        )
        return 0 if runner.run(max_seconds=args.reactive_timeout) else 1
    finally:
        debug_view.close()
        capture.close()


if __name__ == "__main__":
    raise SystemExit(main())
