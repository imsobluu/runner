# Friend-Farm Continuous Trace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replay the newest existing friend-farm v5 trace on a single time clock that starts when `earn_xp.png` appears and ends when `result_ok_button.png` appears.

**Architecture:** Keep this behavior local to `scripts/launch_mumu_cookierun.py`. Reuse `avd_runner.levels.load_levels` for v5 validation, select the last sorted level-1 variant, and add one small timed replay function that uses the existing menu capture for the start trigger and the existing 1280x720 replay capture for result detection.

**Tech Stack:** Python 3, existing `WindowCapture`, `AvdDevice.input_shell`, OpenCV template helpers, plain-Python assertion self-checks

## Global Constraints

- Preserve the user's unstaged `close_all_modals` change from `min(8.0, timeout_seconds)` to `min(10.0, timeout_seconds)` and exclude it from implementation commits.
- Preserve and include the user-provided `assets/friend-farm/earn_xp.png`; do not edit its pixels.
- Do not modify `avd_runner/levels.py`, `scripts/record_levels.py`, trace format version 5, general gameplay modes, or existing recording files.
- Treat repeated identical tap coordinates as valid and replay them unchanged.
- Use the last filename returned by the existing sorted v5 loader for `level_01`.
- Open no capture and read no recording during `--dry-run`.
- Add no dependency and no new CLI option.

---

### Task 1: Load and replay one timed friend-farm trace

**Files:**
- Modify: `scripts/launch_mumu_cookierun.py:23-49,893-968`
- Test: `scripts/test_launch_mumu_cookierun.py`

**Interfaces:**
- Consumes: `load_levels(levels_dir: Path) -> dict[int, list[dict]]`, `AvdDevice.input_shell()`, `find_transparent_template_multiscale`, and `find_template`
- Produces: `load_friend_farm_trace(levels_dir: Path = FRIEND_FARM_RECORDINGS_DIR) -> dict`
- Produces: `replay_friend_farm_trace(device, menu_capture, replay_capture, recorded: dict, trigger_timeout: float, max_seconds: float = 1200.0) -> bool`

- [ ] **Step 1: Add failing loader and timer checks**

Add `json` and `tempfile` imports to `scripts/test_launch_mumu_cookierun.py`, then add this focused check before the existing launcher integration fakes:

```python
import json
import tempfile


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
            ("swipe", round(FakeClock.now, 3), x1, y1, x2, y2, duration_ms, background, label)
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
```

- [ ] **Step 2: Run the focused check and verify the red state**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_launch_mumu_cookierun.py
```

Expected: fail with `AttributeError` because `load_friend_farm_trace` does not exist.

- [ ] **Step 3: Add the minimal loader and timed replay**

Change the level import and add the start template constant in `scripts/launch_mumu_cookierun.py`:

```python
from avd_runner.levels import LevelReplayer, load_levels

FRIEND_FARM_EARN_XP_TEMPLATE = FRIEND_FARM_ASSETS / "earn_xp.png"
```

Add these functions immediately before `run_friend_farm_levels`:

```python
def load_friend_farm_trace(
    levels_dir: Path = FRIEND_FARM_RECORDINGS_DIR,
) -> dict:
    variants = load_levels(levels_dir).get(1, [])
    if not variants:
        raise ValueError(f"No level 1 recording in {levels_dir}")
    return variants[-1]


def replay_friend_farm_trace(
    device: AvdDevice,
    menu_capture: WindowCapture,
    replay_capture: WindowCapture,
    recorded: dict,
    trigger_timeout: float,
    max_seconds: float = 1200.0,
) -> bool:
    with device.input_shell() as shell:
        trigger_deadline = time.perf_counter() + trigger_timeout
        while time.perf_counter() < trigger_deadline:
            if find_transparent_template_multiscale(
                menu_capture.grab(),
                FRIEND_FARM_EARN_XP_TEMPLATE,
                threshold=0.9,
            ):
                started = time.perf_counter()
                print(
                    f"Friend-farm timed replay of {len(recorded['taps'])} taps "
                    f"from {recorded['path'].name}."
                )
                break
            time.sleep(0.01)
        else:
            print("Timed out waiting for earn_xp.png; replay not started.")
            return False

        taps = recorded["taps"]
        tap_index = 0
        deadline = started + max_seconds
        next_result_check = started
        while time.perf_counter() < deadline:
            now = time.perf_counter()
            if now >= next_result_check:
                if find_template(
                    replay_capture.grab(),
                    RESULT_OK_BUTTON_TEMPLATE,
                    threshold=0.85,
                ):
                    print("Result screen detected; timed replay finished.")
                    return True
                next_result_check = now + 0.1

            while tap_index < len(taps) and now - started >= taps[tap_index]["t"]:
                tap = taps[tap_index]
                shell.swipe(
                    tap["x"],
                    tap["y"],
                    tap["x"],
                    tap["y"],
                    max(1, round(tap["duration"] * 1000)),
                    background=True,
                    label="friend_farm_trace",
                )
                tap_index += 1
            time.sleep(0.005)

    print("Timed replay timed out without reaching the result screen.")
    return False
```

- [ ] **Step 4: Run the focused check and verify green**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_launch_mumu_cookierun.py
```

Expected: exit `0` and print `ok`; the old integration remains temporarily available through the retained `LevelReplayer` import.

- [ ] **Step 5: Commit the independently tested timer**

```powershell
git -c safe.directory=E:/runner add -p -- scripts/launch_mumu_cookierun.py
# Answer `n` for the close_all_modals min(10.0) hunk and `y` for the timed-trace hunks.
git -c safe.directory=E:/runner add -- scripts/test_launch_mumu_cookierun.py assets/friend-farm/earn_xp.png
git -c safe.directory=E:/runner diff --cached --check
git -c safe.directory=E:/runner commit -m "feat: add friend-farm timed trace replay"
```

Expected: the commit contains only the timer, its focused checks, and the supplied trigger asset; the user's `min(10.0, timeout_seconds)` line remains unstaged.

---

### Task 2: Route the friend-farm launcher through the timed trace

**Files:**
- Modify: `scripts/launch_mumu_cookierun.py:893-968`
- Test: `scripts/test_launch_mumu_cookierun.py:11-211`

**Interfaces:**
- Consumes: `load_friend_farm_trace() -> dict` and `replay_friend_farm_trace(...) -> bool` from Task 1
- Produces: `run_friend_farm_levels(...) -> bool` that loads before `play_3`, starts on `earn_xp.png`, and exits on `result_ok_button.png`

- [ ] **Step 1: Replace the old fake replayer with failing timed-integration checks**

Replace `FakeReplayer` with a fake timed function configured through module-level state:

```python
fake_trace = {"path": Path("level_01_008.json"), "taps": []}
fake_load_error: Exception | None = None
fake_replay_result = True
fake_replay_error: Exception | None = None


def fake_load_trace() -> dict:
    events.append("load")
    if fake_load_error is not None:
        raise fake_load_error
    return fake_trace


def fake_timed_replay(
    device,
    menu_capture,
    replay_capture,
    recorded,
    trigger_timeout: float,
) -> bool:
    events.append("replay")
    assert menu_capture == "capture"
    assert isinstance(replay_capture, FakeCapture)
    assert recorded is fake_trace
    assert trigger_timeout == 3.0
    if fake_replay_error is not None:
        raise fake_replay_error
    return fake_replay_result
```

Update `reset()` to clear those four fake controls. Save and replace the original `load_friend_farm_trace` and `replay_friend_farm_trace` bindings in the `try/finally` block. Update the success assertion to:

```python
assert events == ["load", "capture", "device", "tap", "replay", "close"]
```

Update the failure assertions to prove:

```python
# Missing/invalid trace: no capture and no play_3 tap.
assert events == ["load"]

# Failed play_3: trace and replay resources were prepared but replay did not start.
assert events == ["load", "capture", "device", "tap", "close"]

# Replay false or exception: capture is always closed.
assert events == ["load", "capture", "device", "tap", "replay", "close"]

# Dry run: no trace load and no capture.
assert events == ["tap"]
```

- [ ] **Step 2: Run the focused check and verify the red state**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_launch_mumu_cookierun.py
```

Expected: fail because `run_friend_farm_levels` still constructs `LevelReplayer` instead of calling the two timed-trace functions.

- [ ] **Step 3: Replace the old integration with the timed path**

Keep the dry-run branch unchanged. In the real branch of `run_friend_farm_levels`, load the trace before resolving the MuMu window, then create the replay capture/device, tap `play_3`, and call the timed function:

```python
    if capture is None:
        print(f"{serial}: WGC capture is unavailable.")
        return False

    replay_capture: WindowCapture | None = None
    try:
        recorded = load_friend_farm_trace()
        hwnd = mumu_window_for_serial(serial)
        if hwnd is None:
            raise RuntimeError("could not find its MuMu window")
        replay_capture = WindowCapture(
            window_hwnd=hwnd,
            device_size=DEFAULT_DEVICE_SIZE,
        )
        replay_device = AvdDevice(
            serial=serial,
            adb_path=adb_path,
            device_size=DEFAULT_DEVICE_SIZE,
            input_size=device_size,
        )
    except Exception as exc:
        if replay_capture is not None:
            replay_capture.close()
        print(f"{serial}: could not prepare timed replay: {exc}")
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
        return replay_friend_farm_trace(
            replay_device,
            capture,
            replay_capture,
            recorded,
            timeout_seconds,
        )
    except Exception as exc:
        print(f"{serial}: timed replay failed: {exc}")
        return False
    finally:
        replay_capture.close()
```

Remove the now-unused `LevelReplayer` import and all corresponding fake/original bindings from the self-check.

- [ ] **Step 4: Run focused checks and verify green**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_launch_mumu_cookierun.py
.venv\Scripts\python.exe scripts\test_levels.py
```

Expected: both exit `0` and print `ok`.

- [ ] **Step 5: Run the regression gate**

Run:

```powershell
.venv\Scripts\python.exe -m compileall -q avd_runner scripts
.venv\Scripts\python.exe scripts\launch_mumu_cookierun.py --help
.venv\Scripts\python.exe scripts\test_launch_mumu_cookierun.py
.venv\Scripts\python.exe scripts\test_levels.py
.venv\Scripts\python.exe scripts\test_recording.py
.venv\Scripts\python.exe scripts\test_capture.py
.venv\Scripts\python.exe scripts\test_device.py
git -c safe.directory=E:/runner diff --check
```

Expected: every command exits `0`; each self-check prints `ok`; `git diff --check` emits no errors. The launcher's unrelated `min(10.0, timeout_seconds)` edit remains present.

- [ ] **Step 6: Commit the launcher integration**

```powershell
git -c safe.directory=E:/runner add -p -- scripts/launch_mumu_cookierun.py
# Answer `n` for the close_all_modals min(10.0) hunk and `y` for the timed-integration hunks.
git -c safe.directory=E:/runner add -- scripts/test_launch_mumu_cookierun.py
git -c safe.directory=E:/runner diff --cached --check
git -c safe.directory=E:/runner commit -m "feat: use timed friend-farm trace"
```

Expected: the integration commit replaces only the friend-farm `LevelReplayer` path and its focused self-check.
