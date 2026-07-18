# MuMu Level Recording and Playback Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record valid MuMu touch coordinates and start level replay in the coordinate space expected by the existing `LevelReplayer`.

**Architecture:** Extend the existing touch-event utility to normalize each raw ABS axis into the recorder's 1280x720 logical space. Keep the launcher's 960x540 menu capture unchanged, but create and own a second 1280x720 capture and logical `AvdDevice` exclusively for `LevelReplayer`.

**Tech Stack:** Python 3, ADB `getevent`, existing WGC `WindowCapture`, existing `AvdDevice`, existing `LevelReplayer`

## Global Constraints

- Do not modify `avd_runner/levels.py`, its marker constants, or trace format version 5.
- Do not modify or delete `recordings/friend_farm/levels/level_01/level_01_001.json`; the user will replace the invalid trace after this fix.
- Keep launcher menu automation at `VISION_REFERENCE_SIZE = (960, 540)`.
- Use `DEFAULT_DEVICE_SIZE = (1280, 720)` for level capture and recorded replay coordinates.
- Preserve the user's unstaged `scripts/launch_mumu_cookierun.py` change from `min(8.0, timeout_seconds)` to `min(10.0, timeout_seconds)` and do not include it in either implementation commit.
- Dry-run must open no capture and require no recordings.
- Add no dependency and no new CLI option.

---

### Task 1: Normalize MuMu raw touch coordinates

**Files:**
- Modify: `avd_runner/recording.py:8-60`
- Modify: `scripts/record_levels.py:16-26,69-138`
- Test: `scripts/test_recording.py`

**Interfaces:**
- Produces: `touch_axis_ranges(device: AvdDevice, event_device: str) -> dict[str, tuple[int, int]]`
- Produces: `scale_touch_axis(value: int, logical_size: int, axis_range: tuple[int, int] | None) -> int`
- Consumes: `AvdDevice.adb("shell", "getevent", "-lp", event_device) -> str`

- [ ] **Step 1: Add failing axis metadata and scaling checks**

Update the import in `scripts/test_recording.py` to:

```python
from avd_runner.recording import (
    _parse_getevent_line,
    find_touch_event_device,
    scale_touch_axis,
    touch_axis_ranges,
)
```

Append this complete check before `print("ok")`:

```python
class FakeAxisDevice:
    def adb(self, *args):
        assert args == (
            "shell",
            "getevent",
            "-lp",
            "/dev/input/event4",
        )
        return """
    ABS_MT_POSITION_X : value 0, min 0, max 1279, fuzz 0
    ABS_MT_POSITION_Y : value 0, min 100, max 32867, fuzz 0
"""


ranges = touch_axis_ranges(FakeAxisDevice(), "/dev/input/event4")
assert ranges == {
    "ABS_MT_POSITION_X": (0, 1279),
    "ABS_MT_POSITION_Y": (100, 32867),
}
assert scale_touch_axis(640, 1280, ranges["ABS_MT_POSITION_X"]) == 640
assert scale_touch_axis(100, 720, ranges["ABS_MT_POSITION_Y"]) == 0
assert scale_touch_axis(32867, 720, ranges["ABS_MT_POSITION_Y"]) == 719
assert scale_touch_axis(16484, 720, ranges["ABS_MT_POSITION_Y"]) == 360
assert scale_touch_axis(500, 720, None) == 500
assert scale_touch_axis(900, 720, None) == 719
assert scale_touch_axis(500, 720, (4, 4)) == 500
```

- [ ] **Step 2: Run the recording check and verify the red state**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_recording.py
```

Expected: fail during import because `scale_touch_axis` and
`touch_axis_ranges` do not exist.

- [ ] **Step 3: Implement metadata parsing and scaling**

Append these functions to `avd_runner/recording.py` after
`find_touch_event_device` and before `_touch_device_from_block`:

```python
def touch_axis_ranges(
    device: AvdDevice,
    event_device: str,
) -> dict[str, tuple[int, int]]:
    output = device.adb("shell", "getevent", "-lp", event_device)
    ranges: dict[str, tuple[int, int]] = {}
    for line in output.splitlines():
        match = re.search(
            r"\b(ABS_MT_POSITION_[XY])\b.*?"
            r"\bmin\s+(-?\d+),\s+max\s+(-?\d+)",
            line,
        )
        if match:
            ranges[match.group(1)] = (int(match.group(2)), int(match.group(3)))
    return ranges


def scale_touch_axis(
    value: int,
    logical_size: int,
    axis_range: tuple[int, int] | None,
) -> int:
    if axis_range is not None:
        minimum, maximum = axis_range
        if maximum > minimum:
            value = round(
                (value - minimum) * (logical_size - 1) / (maximum - minimum)
            )
    return max(0, min(logical_size - 1, value))
```

Update the import in `scripts/record_levels.py` to:

```python
from avd_runner.recording import (
    _parse_getevent_line,
    find_touch_event_device,
    scale_touch_axis,
    touch_axis_ranges,
)
```

In `watch_taps`, immediately after the existing event-device message, add:

```python
    axis_ranges = (
        touch_axis_ranges(device, event_device)
        if event_device is not None
        else {}
    )
```

Replace the two raw clamp assignments with:

```python
        if name == "ABS_MT_POSITION_X":
            latest_x = scale_touch_axis(
                value,
                width,
                axis_ranges.get("ABS_MT_POSITION_X"),
            )
        elif name == "ABS_MT_POSITION_Y":
            latest_y = scale_touch_axis(
                value,
                height,
                axis_ranges.get("ABS_MT_POSITION_Y"),
            )
```

- [ ] **Step 4: Run focused recording checks and verify green**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_recording.py
.venv\Scripts\python.exe scripts\test_levels.py
```

Expected: both exit `0` and print `ok`. `test_levels.py` may also print its
existing replay and temporary recording diagnostics.

- [ ] **Step 5: Commit the recording fix**

Run:

```powershell
git -c safe.directory=E:/runner add -- avd_runner/recording.py scripts/record_levels.py scripts/test_recording.py
git -c safe.directory=E:/runner diff --cached --check
git -c safe.directory=E:/runner commit -m "fix(recording): scale raw touch axes"
```

Expected: the commit contains only the three Task 1 files.

---

### Task 2: Give LevelReplayer its own 1280x720 MuMu capture

**Files:**
- Modify: `scripts/launch_mumu_cookierun.py:20-24,892-950`
- Test: `scripts/test_launch_mumu_cookierun.py`

**Interfaces:**
- Consumes: `mumu_window_for_serial(serial: str) -> int | None`
- Consumes: `WindowCapture(window_hwnd: int, device_size: tuple[int, int])`
- Consumes: `AvdDevice(serial: str, adb_path: str, device_size: tuple[int, int], input_size: tuple[int, int])`
- Preserves: `run_friend_farm_levels(adb_path, serial, capture, device_size, timeout_seconds, *, dry_run) -> bool`

- [ ] **Step 1: Extend the launcher self-check for replay capture ownership**

Replace `FakeDevice` in `scripts/test_launch_mumu_cookierun.py` with:

```python
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
```

Add this fake immediately after `FakeDevice`:

```python
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
```

In `FakeReplayer.__init__`, replace `assert capture == "capture"` with:

```python
        assert isinstance(capture, FakeCapture)
```

Update `reset()` to include:

```python
    FakeCapture.events = events
    FakeCapture.init_error = None
```

Save and patch these additional originals before the `try` block:

```python
original_capture = launcher.WindowCapture
original_window = launcher.mumu_window_for_serial
```

At the start of the `try` block, add:

```python
    launcher.WindowCapture = FakeCapture
    launcher.mumu_window_for_serial = lambda serial: 123
```

Change the success expectation to:

```python
    assert events == ["capture", "device", "prepare", "tap", "run", "close"]
```

Change the constructor-failure expectation to:

```python
    assert events == ["capture", "device", "prepare", "close"]
```

Change the tap-failure expectation to:

```python
    assert events == ["capture", "device", "prepare", "tap", "close"]
```

Change both replay-false and replay-exception expectations to:

```python
    assert events == ["capture", "device", "prepare", "tap", "run", "close"]
```

After the missing-menu-capture case, add these cases:

```python
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
```

Restore the additional originals in `finally`:

```python
    launcher.WindowCapture = original_capture
    launcher.mumu_window_for_serial = original_window
```

The dry-run expectation remains `events == ["tap"]`, proving it creates no
replay capture.

- [ ] **Step 2: Run the launcher check and verify the red state**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_launch_mumu_cookierun.py
```

Expected: fail because the current implementation does not construct a
dedicated `WindowCapture`, does not pass `input_size`, and does not close a
replay capture.

- [ ] **Step 3: Implement the dedicated replay capture**

Add this import beside the existing `AvdDevice` import in
`scripts/launch_mumu_cookierun.py`:

```python
from avd_runner.device import DEFAULT_DEVICE_SIZE
```

Replace the non-dry-run body of `run_friend_farm_levels`, beginning at the
existing `if capture is None`, with:

```python
    if capture is None:
        print(f"{serial}: WGC capture is unavailable.")
        return False

    replay_capture: WindowCapture | None = None
    try:
        hwnd = mumu_window_for_serial(serial)
        if hwnd is None:
            raise RuntimeError("could not find its MuMu window")
        replay_capture = WindowCapture(
            window_hwnd=hwnd,
            device_size=DEFAULT_DEVICE_SIZE,
        )
        runner = LevelReplayer(
            AvdDevice(
                serial=serial,
                adb_path=adb_path,
                device_size=DEFAULT_DEVICE_SIZE,
                input_size=device_size,
            ),
            replay_capture,
            ASSETS,
            FRIEND_FARM_RECORDINGS_DIR,
            exit_template=RESULT_OK_BUTTON_TEMPLATE,
        )
    except Exception as exc:
        if replay_capture is not None:
            replay_capture.close()
        print(f"{serial}: could not prepare level replay: {exc}")
        return False

    try:
        if not tap_template_on_device(
            adb_path,
            serial,
            capture,
            device_size,
            FRIEND_FARM_PLAY_3_TEMPLATE,
            timeout_seconds,
            dry_run=False,
        ):
            return False
        return runner.run()
    except Exception as exc:
        print(f"{serial}: level replay failed: {exc}")
        return False
    finally:
        replay_capture.close()
```

Do not alter the user's `scan_until = started + min(10.0, timeout_seconds)`
working-tree change elsewhere in this file.

- [ ] **Step 4: Run focused launcher checks and verify green**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_launch_mumu_cookierun.py
.venv\Scripts\python.exe scripts\test_capture.py
.venv\Scripts\python.exe scripts\test_device.py
```

Expected: all three exit `0` and print `ok`; the launcher check may print its
expected failure-path diagnostics.

- [ ] **Step 5: Run the complete regression gate**

Run:

```powershell
.venv\Scripts\python.exe -m compileall -q avd_runner scripts
.venv\Scripts\python.exe scripts\launch_mumu_cookierun.py --help
.venv\Scripts\python.exe scripts\record_levels.py --help
.venv\Scripts\python.exe scripts\test_launch_mumu_cookierun.py
.venv\Scripts\python.exe scripts\test_levels.py
.venv\Scripts\python.exe scripts\test_recording.py
.venv\Scripts\python.exe scripts\test_reactive.py
.venv\Scripts\python.exe scripts\test_captcha.py
.venv\Scripts\python.exe scripts\test_auto_runner.py
.venv\Scripts\python.exe scripts\test_capture.py
.venv\Scripts\python.exe scripts\test_device.py
.venv\Scripts\python.exe scripts\test_none.py
.venv\Scripts\python.exe scripts\test_jump_timing.py --help
git -c safe.directory=E:/runner diff --check
```

Expected: every command exits `0`; help output adds no CLI option; the user's
unstaged `scan_until` change remains present and uncommitted.

- [ ] **Step 6: Commit only the replay-coordinate hunks**

Stage the test normally, then interactively stage only the new import and
`run_friend_farm_levels` hunks from the launcher:

```powershell
git -c safe.directory=E:/runner add -- scripts/test_launch_mumu_cookierun.py
git -c safe.directory=E:/runner add -p -- scripts/launch_mumu_cookierun.py
git -c safe.directory=E:/runner diff --cached --check
git -c safe.directory=E:/runner diff --cached --name-only
git -c safe.directory=E:/runner commit -m "fix(launcher): align level replay coordinates"
```

For `git add -p`, answer `n` to the `scan_until` hunk and `y` to the import and
`run_friend_farm_levels` hunks. Before committing, the cached name list must be
exactly:

```text
scripts/launch_mumu_cookierun.py
scripts/test_launch_mumu_cookierun.py
```

After the commit, `git status --short` must still show only the user's unstaged
launcher modification.

## Manual Validation After Implementation

The existing trace is known-bad and is intentionally left untouched. The user
must replace it after the code commits:

```powershell
Remove-Item -LiteralPath recordings\friend_farm\levels\level_01\level_01_001.json
$env:ANDROID_SERIAL = "127.0.0.1:16384"
.venv\Scripts\python.exe -u -c "import os,sys; sys.path.insert(0,'scripts'); import launch_mumu_cookierun as m, record_levels as r; hwnd=m.mumu_window_for_serial(os.environ['ANDROID_SERIAL']); assert hwnd, 'Could not find the MuMu window'; Capture=r.WindowCapture; r.WindowCapture=lambda **kwargs: Capture(window_hwnd=hwnd, **kwargs); r.main()" --out recordings --episode friend_farm
```

After recording, inspect the trace and confirm tap Y values are not all `719`,
then run:

```powershell
.venv\Scripts\python.exe scripts\launch_mumu_cookierun.py --friend-farm --instances 0
```

Expected runtime output includes:

```text
Level 1: progress-driven replay of <count> taps from level_01_001.json.
```
