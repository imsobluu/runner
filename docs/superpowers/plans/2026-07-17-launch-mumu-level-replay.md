# MuMu Friend-Farm Level Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the existing `LevelReplayer` after each MuMu friend-farm instance successfully taps `play_3`.

**Architecture:** Add one launcher-local adapter that prepares `LevelReplayer` from the fixed `recordings/friend_farm` root before tapping `play_3`, then runs it with the existing device and WGC capture. Keep `LevelReplayer`, `auto_runner`, existing episode recordings, and all CLI options unchanged.

**Tech Stack:** Python 3, existing `AvdDevice`, `WindowCapture`, and `LevelReplayer`

## Global Constraints

- Runtime changes are limited to `scripts/launch_mumu_cookierun.py`.
- Add one focused plain-Python self-check at `scripts/test_launch_mumu_cookierun.py`.
- Always load `recordings/friend_farm/levels/level_NN/level_NN_nnn.json`; add no `--episode` option and no fallback recording path.
- Do not modify `avd_runner/levels.py`, `scripts/auto_runner.py`, `recordings/episodes/ing01`, or general reactive tooling.
- Prepare and validate the replayer before tapping `play_3`.
- Supply no Cookie Relay template and use `LevelReplayer.run()` with its existing 20-minute default timeout.
- Dry-run must not require WGC or recordings on disk.

---

### Task 1: Add the launcher-local level replay handoff

**Files:**
- Create: `scripts/test_launch_mumu_cookierun.py`
- Modify: `scripts/launch_mumu_cookierun.py:20-43,887-961`

**Interfaces:**
- Consumes: `LevelReplayer(device, capture, assets_dir, levels_dir, exit_template, relay_template=None)` and `LevelReplayer.run(max_seconds: float = 1200.0) -> bool`
- Produces: `run_friend_farm_levels(adb_path: str, serial: str, capture: WindowCapture | None, device_size: tuple[int, int], timeout_seconds: float, *, dry_run: bool) -> bool`
- Updates: `run_friend_farm_sequence(...) -> bool` delegates its terminal step to `run_friend_farm_levels(...)`

- [ ] **Step 1: Write the failing launcher self-check**

Create `scripts/test_launch_mumu_cookierun.py` with this complete test:

```python
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import launch_mumu_cookierun as launcher


class FakeDevice:
    events: list[str] = []

    def __init__(self, *, serial: str, adb_path: str, device_size: tuple[int, int]):
        assert serial == "serial"
        assert adb_path == "adb"
        assert device_size == (960, 540)
        self.events.append("device")


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
        assert capture == "capture"
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
    FakeReplayer.events = events
    FakeReplayer.init_error = None
    FakeReplayer.run_result = True
    FakeReplayer.run_error = None
    return events


original_device = launcher.AvdDevice
original_replayer = launcher.LevelReplayer
original_tap = launcher.tap_template_on_device
original_levels = launcher.run_friend_farm_levels
try:
    launcher.AvdDevice = FakeDevice
    launcher.LevelReplayer = FakeReplayer

    events = reset()
    launcher.tap_template_on_device = lambda *args, **kwargs: events.append("tap") or True
    assert launcher.run_friend_farm_levels(
        "adb", "serial", "capture", (960, 540), 3.0, dry_run=False
    )
    assert events == ["device", "prepare", "tap", "run"]

    events = reset()
    FakeReplayer.init_error = ValueError("missing recordings")
    launcher.tap_template_on_device = lambda *args, **kwargs: events.append("tap") or True
    assert not launcher.run_friend_farm_levels(
        "adb", "serial", "capture", (960, 540), 3.0, dry_run=False
    )
    assert events == ["device", "prepare"]

    events = reset()
    launcher.tap_template_on_device = lambda *args, **kwargs: events.append("tap") or True
    assert not launcher.run_friend_farm_levels(
        "adb", "serial", None, (960, 540), 3.0, dry_run=False
    )
    assert events == []

    events = reset()
    launcher.tap_template_on_device = lambda *args, **kwargs: events.append("tap") or False
    assert not launcher.run_friend_farm_levels(
        "adb", "serial", "capture", (960, 540), 3.0, dry_run=False
    )
    assert events == ["device", "prepare", "tap"]

    events = reset()
    FakeReplayer.run_result = False
    launcher.tap_template_on_device = lambda *args, **kwargs: events.append("tap") or True
    assert not launcher.run_friend_farm_levels(
        "adb", "serial", "capture", (960, 540), 3.0, dry_run=False
    )
    assert events == ["device", "prepare", "tap", "run"]

    events = reset()
    FakeReplayer.run_error = RuntimeError("replay failed")
    launcher.tap_template_on_device = lambda *args, **kwargs: events.append("tap") or True
    assert not launcher.run_friend_farm_levels(
        "adb", "serial", "capture", (960, 540), 3.0, dry_run=False
    )
    assert events == ["device", "prepare", "tap", "run"]

    events = reset()
    launcher.tap_template_on_device = lambda *args, **kwargs: events.append("tap") or True
    assert launcher.run_friend_farm_levels(
        "adb", "serial", None, (960, 540), 3.0, dry_run=True
    )
    assert events == ["tap"]

    events = reset()
    launcher.tap_template_on_device = lambda *args, **kwargs: events.append("tap") or True
    launcher.run_friend_farm_levels = (
        lambda *args, **kwargs: events.append("levels") or True
    )
    assert launcher.run_friend_farm_sequence(
        "adb", "serial", None, (960, 540), 3.0, dry_run=True
    )
    assert events[-1] == "levels"
finally:
    launcher.AvdDevice = original_device
    launcher.LevelReplayer = original_replayer
    launcher.tap_template_on_device = original_tap
    launcher.run_friend_farm_levels = original_levels

print("ok")
```

- [ ] **Step 2: Run the self-check and verify the red state**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_launch_mumu_cookierun.py
```

Expected: fail during setup because `launch_mumu_cookierun` has no `AvdDevice`, `LevelReplayer`, or `run_friend_farm_levels` interface yet.

- [ ] **Step 3: Add the minimal launcher adapter**

In `scripts/launch_mumu_cookierun.py`, import the existing classes:

```python
from avd_runner import AvdDevice
from avd_runner.levels import LevelReplayer
```

Add fixed launcher-local paths beside the existing friend-farm constants:

```python
ASSETS = REPO_ROOT / "assets"
FRIEND_FARM_RECORDINGS_DIR = REPO_ROOT / "recordings" / "friend_farm"
RESULT_OK_BUTTON_TEMPLATE = ASSETS / "result_ok_button.png"
```

Add the adapter immediately before `run_friend_farm_sequence`:

```python
def run_friend_farm_levels(
    adb_path: str,
    serial: str,
    capture: WindowCapture | None,
    device_size: tuple[int, int],
    timeout_seconds: float,
    *,
    dry_run: bool,
) -> bool:
    if dry_run:
        if not tap_template_on_device(
            adb_path,
            serial,
            capture,
            device_size,
            FRIEND_FARM_PLAY_3_TEMPLATE,
            timeout_seconds,
            dry_run=True,
        ):
            return False
        print(f"{serial}: run level replay with {FRIEND_FARM_RECORDINGS_DIR}")
        return True
    if capture is None:
        print(f"{serial}: WGC capture is unavailable.")
        return False

    try:
        runner = LevelReplayer(
            AvdDevice(
                serial=serial,
                adb_path=adb_path,
                device_size=device_size,
            ),
            capture,
            ASSETS,
            FRIEND_FARM_RECORDINGS_DIR,
            exit_template=RESULT_OK_BUTTON_TEMPLATE,
        )
    except Exception as exc:
        print(f"{serial}: could not prepare level replay: {exc}")
        return False

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

    try:
        return runner.run()
    except Exception as exc:
        print(f"{serial}: level replay failed: {exc}")
        return False
```

Replace the final direct `play_3` tap in `run_friend_farm_sequence` with:

```python
    return run_friend_farm_levels(
        adb_path,
        serial,
        capture,
        device_size,
        timeout_seconds,
        dry_run=dry_run,
    )
```

- [ ] **Step 4: Run the focused self-check and verify green**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_launch_mumu_cookierun.py
```

Expected: exit `0` and print `ok`. Error-path cases may also print the expected preparation and replay failure messages.

- [ ] **Step 5: Run integration and regression verification**

Run:

```powershell
.venv\Scripts\python.exe -m compileall -q avd_runner scripts
.venv\Scripts\python.exe scripts\launch_mumu_cookierun.py --help
.venv\Scripts\python.exe scripts\test_levels.py
.venv\Scripts\python.exe scripts\test_reactive.py
.venv\Scripts\python.exe scripts\test_captcha.py
.venv\Scripts\python.exe scripts\test_auto_runner.py
.venv\Scripts\python.exe scripts\test_capture.py
.venv\Scripts\python.exe scripts\test_device.py
.venv\Scripts\python.exe scripts\test_none.py
.venv\Scripts\python.exe scripts\test_recording.py
.venv\Scripts\python.exe scripts\test_jump_timing.py --help
git -c safe.directory=E:/runner diff --check
```

Expected: every command exits `0`; launcher help contains no episode or reactive replay options; existing levels, auto-runner, recording, and reactive checks remain green.

- [ ] **Step 6: Commit the focused implementation**

```powershell
git add scripts/launch_mumu_cookierun.py scripts/test_launch_mumu_cookierun.py
git commit -m "feat(launcher): replay friend-farm levels"
```
