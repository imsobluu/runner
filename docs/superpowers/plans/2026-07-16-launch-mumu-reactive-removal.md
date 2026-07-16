# MuMu Launcher Reactive Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MuMu friend-farm automation finish successfully after tapping `play_3` without invoking or configuring reactive gameplay.

**Architecture:** Remove the reactive handoff from the existing friend-farm sequence and collapse its return path to the `play_3` template-tap result. Keep every general reactive runner module, test, debug script, and asset unchanged.

**Tech Stack:** Python 3, `argparse`, existing MuMu/ADB/WGC launcher helpers

## Global Constraints

- Modify runtime behavior only in `scripts/launch_mumu_cookierun.py`.
- Keep `avd_runner/reactive.py`, `scripts/auto_runner.py`, reactive tests, debug scripts, and all asset files unchanged.
- Do not add level recording in this change.
- Preserve MuMu launch, ADB readiness, window arrangement, capture, friend-farm steps, multi-instance aggregation, and exit-code behavior through `play_3`.

---

### Task 1: Remove the MuMu reactive handoff

**Files:**
- Modify: `scripts/launch_mumu_cookierun.py:45-46,890-1016,1290-1312,1410-1420`
- Verify: `scripts/launch_mumu_cookierun.py`

**Interfaces:**
- Consumes: `tap_template_on_device(adb_path: str, serial: str, capture: WindowCapture | None, device_size: tuple[int, int], template: Path, timeout_seconds: float, *, dry_run: bool) -> bool`
- Produces: `run_friend_farm_sequence(adb_path: str, serial: str, capture: WindowCapture | None, device_size: tuple[int, int], timeout_seconds: float, *, dry_run: bool) -> bool`

- [ ] **Step 1: Confirm the obsolete launcher surface exists**

Run:

```powershell
rg -n "DEFAULT_REACTIVE_THEME_DIR|RESULT_OK_BUTTON_TEMPLATE|run_reactive_gameplay|friend-farm-reactive|no_friend_farm_reactive|reactive_timeout|run_reactive" scripts/launch_mumu_cookierun.py
```

Expected: matches for the reactive constants, helper, sequence parameters, CLI options, validation, and call arguments.

- [ ] **Step 2: Delete the launcher-local reactive import, constants, and helper**

Remove the now-unused import:

```python
from avd_runner import AvdDevice
```

Remove these constants:

```python
RESULT_OK_BUTTON_TEMPLATE = REPO_ROOT / "assets" / "result_ok_button.png"
DEFAULT_REACTIVE_THEME_DIR = REPO_ROOT / "assets" / "friend-farm-reactive" / "epEV02"
```

Delete `run_reactive_gameplay` in full. Do not change `AvdDevice`,
`ReactiveRunner`, or any asset file elsewhere in the repository.

- [ ] **Step 3: Make `play_3` the terminal friend-farm step**

Change the sequence signature to:

```python
def run_friend_farm_sequence(
    adb_path: str,
    serial: str,
    capture: WindowCapture | None,
    device_size: tuple[int, int],
    timeout_seconds: float,
    *,
    dry_run: bool,
) -> bool:
```

Replace its final conditional reactive handoff with the direct terminal result:

```python
    return tap_template_on_device(
        adb_path,
        serial,
        capture,
        device_size,
        FRIEND_FARM_PLAY_3_TEMPLATE,
        timeout_seconds,
        dry_run=dry_run,
    )
```

- [ ] **Step 4: Remove reactive CLI configuration and call plumbing**

Delete the `--friend-farm-reactive-assets`, `--friend-farm-reactive-timeout`, and `--no-friend-farm-reactive` arguments. Delete validation of `args.friend_farm_reactive_timeout`.

Reduce the concurrent invocation to:

```python
run_friend_farm_sequence(
    adb_path,
    serial,
    captures[serial],
    serial_to_size[serial],
    args.tap_timeout,
    dry_run=args.dry_run,
)
```

- [ ] **Step 5: Verify syntax and command-line behavior**

Run:

```powershell
.venv\Scripts\python.exe -m py_compile scripts\launch_mumu_cookierun.py
.venv\Scripts\python.exe scripts\launch_mumu_cookierun.py --help
```

Expected: both commands exit `0`; help still lists `--friend-farm` and `--tap-timeout`, but none of the three removed reactive options.

- [ ] **Step 6: Verify the deletion boundary**

Run:

```powershell
if (rg -n -i "reactive" scripts/launch_mumu_cookierun.py) { exit 1 }
```

Expected: no reactive matches in the launcher. Confirm `git status --short`
shows no changes to general reactive code, tests, debug scripts, or assets
caused by this task.

- [ ] **Step 7: Preserve the user's existing untracked launcher work**

```powershell
git -c safe.directory=E:/runner status --short -- scripts/launch_mumu_cookierun.py
```

Expected: `scripts/launch_mumu_cookierun.py` remains untracked. Do not stage or
commit it because it predates this task as uncommitted user work.
