from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import launch_mumu_cookierun as launcher


class FakeDevice:
    events: list[str] = []

    def __init__(
        self,
        *,
        serial: str,
        adb_path: str,
        device_size: tuple[int, int],
        input_size: tuple[int, int],
    ):
        assert serial == "serial"
        assert adb_path == "adb"
        assert device_size == (1280, 720)
        assert input_size == (960, 540)
        self.events.append("device")


class FakeCapture:
    events: list[str] = []
    init_error: Exception | None = None

    def __init__(
        self,
        *,
        window_hwnd: int,
        device_size: tuple[int, int],
    ):
        self.events.append("capture")
        assert window_hwnd == 123
        assert device_size == (1280, 720)
        if self.init_error is not None:
            raise self.init_error

    def close(self) -> None:
        self.events.append("close")


class FakeReplayer:
    events: list[str] = []
    init_error: Exception | None = None
    run_result = True
    run_error: Exception | None = None

    def __init__(
        self,
        device,
        capture,
        assets_dir: Path,
        levels_dir: Path,
        exit_template: Path,
    ):
        self.events.append("prepare")
        assert isinstance(capture, FakeCapture)
        assert assets_dir == REPO_ROOT / "assets"
        assert levels_dir == REPO_ROOT / "recordings" / "friend_farm"
        assert exit_template == REPO_ROOT / "assets" / "result_ok_button.png"
        if self.init_error is not None:
            raise self.init_error

    def run(self) -> bool:
        self.events.append("run")
        if self.run_error is not None:
            raise self.run_error
        return self.run_result


def reset() -> list[str]:
    events: list[str] = []
    FakeDevice.events = events
    FakeCapture.events = events
    FakeCapture.init_error = None
    FakeReplayer.events = events
    FakeReplayer.init_error = None
    FakeReplayer.run_result = True
    FakeReplayer.run_error = None
    return events


assert hasattr(launcher, "AvdDevice"), "launcher must expose AvdDevice"
assert hasattr(launcher, "LevelReplayer"), "launcher must expose LevelReplayer"
assert hasattr(
    launcher,
    "run_friend_farm_levels",
), "launcher must expose run_friend_farm_levels"

original_device = launcher.AvdDevice
original_capture = launcher.WindowCapture
original_replayer = launcher.LevelReplayer
original_tap = launcher.tap_template_on_device
original_levels = launcher.run_friend_farm_levels
original_window = launcher.mumu_window_for_serial
try:
    launcher.AvdDevice = FakeDevice
    launcher.WindowCapture = FakeCapture
    launcher.LevelReplayer = FakeReplayer
    launcher.mumu_window_for_serial = lambda serial: 123

    events = reset()
    launcher.tap_template_on_device = (
        lambda *args, **kwargs: events.append("tap") or True
    )
    assert launcher.run_friend_farm_levels(
        "adb", "serial", "capture", (960, 540), 3.0, dry_run=False
    )
    assert events == ["capture", "device", "prepare", "tap", "run", "close"]

    events = reset()
    FakeReplayer.init_error = ValueError("missing recordings")
    launcher.tap_template_on_device = (
        lambda *args, **kwargs: events.append("tap") or True
    )
    assert not launcher.run_friend_farm_levels(
        "adb", "serial", "capture", (960, 540), 3.0, dry_run=False
    )
    assert events == ["capture", "device", "prepare", "close"]

    events = reset()
    launcher.tap_template_on_device = (
        lambda *args, **kwargs: events.append("tap") or True
    )
    assert not launcher.run_friend_farm_levels(
        "adb", "serial", None, (960, 540), 3.0, dry_run=False
    )
    assert events == []

    events = reset()
    launcher.mumu_window_for_serial = lambda serial: None
    launcher.tap_template_on_device = (
        lambda *args, **kwargs: events.append("tap") or True
    )
    assert not launcher.run_friend_farm_levels(
        "adb", "serial", "capture", (960, 540), 3.0, dry_run=False
    )
    assert events == []
    launcher.mumu_window_for_serial = lambda serial: 123

    events = reset()
    FakeCapture.init_error = RuntimeError("capture failed")
    assert not launcher.run_friend_farm_levels(
        "adb", "serial", "capture", (960, 540), 3.0, dry_run=False
    )
    assert events == ["capture"]

    events = reset()
    launcher.tap_template_on_device = (
        lambda *args, **kwargs: events.append("tap") or False
    )
    assert not launcher.run_friend_farm_levels(
        "adb", "serial", "capture", (960, 540), 3.0, dry_run=False
    )
    assert events == ["capture", "device", "prepare", "tap", "close"]

    events = reset()
    FakeReplayer.run_result = False
    launcher.tap_template_on_device = (
        lambda *args, **kwargs: events.append("tap") or True
    )
    assert not launcher.run_friend_farm_levels(
        "adb", "serial", "capture", (960, 540), 3.0, dry_run=False
    )
    assert events == ["capture", "device", "prepare", "tap", "run", "close"]

    events = reset()
    FakeReplayer.run_error = RuntimeError("replay failed")
    launcher.tap_template_on_device = (
        lambda *args, **kwargs: events.append("tap") or True
    )
    assert not launcher.run_friend_farm_levels(
        "adb", "serial", "capture", (960, 540), 3.0, dry_run=False
    )
    assert events == ["capture", "device", "prepare", "tap", "run", "close"]

    events = reset()
    launcher.tap_template_on_device = (
        lambda *args, **kwargs: events.append("tap") or True
    )
    assert launcher.run_friend_farm_levels(
        "adb", "serial", None, (960, 540), 3.0, dry_run=True
    )
    assert events == ["tap"]

    events = reset()
    launcher.tap_template_on_device = (
        lambda *args, **kwargs: events.append("tap") or True
    )
    launcher.run_friend_farm_levels = (
        lambda *args, **kwargs: events.append("levels") or True
    )
    assert launcher.run_friend_farm_sequence(
        "adb", "serial", None, (960, 540), 3.0, dry_run=True
    )
    assert events[-1] == "levels"
finally:
    launcher.AvdDevice = original_device
    launcher.WindowCapture = original_capture
    launcher.LevelReplayer = original_replayer
    launcher.tap_template_on_device = original_tap
    launcher.run_friend_farm_levels = original_levels
    launcher.mumu_window_for_serial = original_window

print("ok")
