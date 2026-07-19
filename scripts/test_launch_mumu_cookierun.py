from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import launch_mumu_cookierun as launcher


with tempfile.TemporaryDirectory() as tmp:
    recordings = Path(tmp)
    level_dir = recordings / "levels" / "level_01"
    level_dir.mkdir(parents=True)
    for suffix, x in (("001", 100), ("002", 178)):
        (level_dir / f"level_01_{suffix}.json").write_text(
            json.dumps(
                {
                    "version": 5,
                    "level": 1,
                    "taps": [
                        {
                            "t": 0.1,
                            "progress": 0.01,
                            "x": x,
                            "y": 93,
                            "duration": 0.06,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
    loaded = launcher.load_friend_farm_trace(recordings)
    assert loaded["path"].name == "level_01_002.json"
    assert loaded["taps"][0]["x"] == 178


class FakeClock:
    now = 0.0

    @classmethod
    def perf_counter(cls) -> float:
        return cls.now

    @classmethod
    def sleep(cls, seconds: float) -> None:
        cls.now += seconds


class FakeShell:
    def __init__(self, events: list[tuple]):
        self.events = events

    def __enter__(self):
        self.events.append(("shell-open", FakeClock.now))
        return self

    def __exit__(self, *exc) -> None:
        self.events.append(("shell-close", FakeClock.now))

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int,
        *,
        background: bool,
        label: str,
    ) -> None:
        self.events.append(
            (
                "swipe",
                round(FakeClock.now, 3),
                x1,
                y1,
                x2,
                y2,
                duration_ms,
                background,
                label,
            )
        )


class TimedDevice:
    def __init__(self, events: list[tuple]):
        self.events = events

    def input_shell(self) -> FakeShell:
        return FakeShell(self.events)


class TimedCapture:
    def __init__(self, name: str):
        self.name = name

    def grab(self) -> str:
        return self.name


timed_events: list[tuple] = []
recorded = {
    "path": Path("level_01_008.json"),
    "taps": [
        {"t": 0.10, "progress": 0.01, "x": 178, "y": 93, "duration": 0.06},
        {"t": 0.20, "progress": 0.02, "x": 178, "y": 93, "duration": 0.08},
    ],
}
original_time = launcher.time
original_transparent_match = launcher.find_transparent_template_multiscale
original_find_template = launcher.find_template
try:
    FakeClock.now = 0.0
    launcher.time = FakeClock
    launcher.find_transparent_template_multiscale = (
        lambda frame, template, threshold=0.9: object()
        if FakeClock.now >= 0.05
        else None
    )
    launcher.find_template = (
        lambda frame, template, threshold=0.85: FakeClock.now >= 0.30
    )
    assert launcher.replay_friend_farm_trace(
        TimedDevice(timed_events),
        TimedCapture("menu"),
        TimedCapture("replay"),
        recorded,
        trigger_timeout=1.0,
        max_seconds=1.0,
    )
finally:
    launcher.time = original_time
    launcher.find_transparent_template_multiscale = original_transparent_match
    launcher.find_template = original_find_template

swipes = [event for event in timed_events if event[0] == "swipe"]
assert [event[2:7] for event in swipes] == [
    (178, 93, 178, 93, 60),
    (178, 93, 178, 93, 80),
]
assert swipes[0][1] >= 0.15
assert timed_events[0][0] == "shell-open"
assert timed_events[-1][0] == "shell-close"

for trigger_found, result_found in ((False, False), (True, False)):
    timeout_events: list[tuple] = []
    try:
        FakeClock.now = 0.0
        launcher.time = FakeClock
        launcher.find_transparent_template_multiscale = (
            lambda frame, template, threshold=0.9: object()
            if trigger_found
            else None
        )
        launcher.find_template = (
            lambda frame, template, threshold=0.85: result_found
        )
        assert not launcher.replay_friend_farm_trace(
            TimedDevice(timeout_events),
            TimedCapture("menu"),
            TimedCapture("replay"),
            recorded,
            trigger_timeout=0.05,
            max_seconds=0.25,
        )
    finally:
        launcher.time = original_time
        launcher.find_transparent_template_multiscale = original_transparent_match
        launcher.find_template = original_find_template
    assert timeout_events[0][0] == "shell-open"
    assert timeout_events[-1][0] == "shell-close"


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
