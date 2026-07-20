# Coordinate Pause Quit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tap Pause by logical coordinate when the mystery-box target is reached, then template-match both Quit buttons without explicit waits.

**Architecture:** Keep the change inside the existing `quit_gameplay` flow. Replace the Pause template target with a fixed logical coordinate consumed by `AvdDevice.tap`; retain the existing `QUIT_TARGET` and `tap_target` error path for both Quit buttons.

**Tech Stack:** Python 3, existing `AvdDevice` coordinate scaling, existing script-style assertion tests.

## Global Constraints

- The Pause logical coordinate is exactly `(1194, 37)`.
- The device layer remains responsible for scaling the logical coordinate to the active input resolution.
- Both Quit actions continue using `assets/quit.png` template matching.
- The action order is Pause coordinate, Quit template, Quit template.
- No explicit wait occurs between any actions in the quit sequence.
- Normal result cleanup and loop behavior remain unchanged.
- Preserve unrelated edits in `assets/activate_fast_start.png` and `scripts/launch_mumu_cookierun.py`.

---

### Task 1: Replace Pause template matching with a coordinate tap

**Files:**
- Modify: `scripts/auto_runner.py:78-108,523-531`
- Test: `scripts/test_auto_runner.py:39-104`

**Interfaces:**
- Consumes: `AutoRunnerContext.device.tap(x: int, y: int, label: str = "") -> tuple[int, int]` and `tap_target(ctx, QUIT_TARGET) -> bool`.
- Produces: `PAUSE_XY = (1194, 37)` and `quit_gameplay(ctx: AutoRunnerContext) -> None` with a coordinate Pause tap followed immediately by two Quit template taps.

- [ ] **Step 1: Write the failing quit-sequence test**

Replace the Pause target assertion and existing quit-sequence block in `scripts/test_auto_runner.py` with:

```python
assert auto_runner.PAUSE_XY == (1194, 37)
assert auto_runner.QUIT_TARGET.path == auto_runner.ASSETS / "quit.png"

# Reaching the configured collection target taps Pause by coordinate, then
# matches both Quit buttons without adding waits.
original_device_tap = ctx.device.tap
original_tap_target = auto_runner.tap_target
quit_sequence = []
try:
    ctx.device.tap = (
        lambda x, y, label="": quit_sequence.append(("tap", x, y, label))
        or (x, y)
    )
    auto_runner.tap_target = (
        lambda _ctx, target, **_kwargs: quit_sequence.append(target.name) or True
    )
    auto_runner.quit_gameplay(ctx)
    assert quit_sequence == [
        ("tap", 1194, 37, "Pause"),
        "Quit",
        "Quit",
    ]
finally:
    ctx.device.tap = original_device_tap
    auto_runner.tap_target = original_tap_target
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.venv\Scripts\python.exe scripts/test_auto_runner.py`

Expected: FAIL because `scripts.auto_runner` has no `PAUSE_XY` constant and still template-matches Pause with two recorded waits.

- [ ] **Step 3: Implement the minimal coordinate-based sequence**

In `scripts/auto_runner.py`, remove `PAUSE_TEMPLATE` and `PAUSE_TARGET`, then define the coordinate beside the remaining quit template:

```python
MYSTERY_BOX_TEMPLATE = ASSETS / "mystery_box.png"
PAUSE_XY = (1194, 37)
QUIT_TEMPLATE = ASSETS / "quit.png"
```

Replace `quit_gameplay` with:

```python
def quit_gameplay(ctx: AutoRunnerContext) -> None:
    ctx.device.tap(*PAUSE_XY, label="Pause")
    for target in (QUIT_TARGET, QUIT_TARGET):
        if not tap_target(ctx, target):
            raise RunnerError(
                f"Could not tap {target.path.name} while quitting gameplay."
            )
```

- [ ] **Step 4: Run focused and full regression verification**

Run:

```powershell
.venv\Scripts\python.exe scripts/test_auto_runner.py
$tests = @(
    "test_auto_runner.py",
    "test_captcha.py",
    "test_capture.py",
    "test_device.py",
    "test_launch_mumu_cookierun.py",
    "test_levels.py",
    "test_mystery_box.py",
    "test_none.py",
    "test_reactive.py",
    "test_recording.py"
)
$tests | ForEach-Object { & .venv\Scripts\python.exe "scripts/$_"; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }
git -c safe.directory=E:/runner diff --check
```

Expected: `scripts/test_auto_runner.py` ends in `ok`; every offline self-check exits 0; `git diff --check` reports no errors. Do not include the interactive `test_jump_timing.py` device harness or the `test_modal_*.py` analysis utilities in the offline suite.

- [ ] **Step 5: Commit only the implementation and test**

```powershell
git -c safe.directory=E:/runner add -- scripts/auto_runner.py scripts/test_auto_runner.py
git -c safe.directory=E:/runner commit -m "fix: tap pause by coordinate"
```

Expected: the commit contains only `scripts/auto_runner.py` and `scripts/test_auto_runner.py`; the unrelated Fast Start asset and launcher edit remain unstaged.
