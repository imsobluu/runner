# Coordinate Gameplay Play Tap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start gameplay by tapping the final Play button at reference coordinate `(920, 616)` instead of matching Double Coins-specific templates.

**Architecture:** Keep the action in `scripts/auto_runner.py` as a small named helper used by `run_after_start()`. Reuse `AvdDevice.tap()` for existing 1280x720 coordinate scaling and remove only the template symbols made dead by the replacement.

**Tech Stack:** Python 3, existing `AvdDevice` input abstraction, repository assertion-script tests.

## Global Constraints

- Use the fixed 1280x720 reference coordinate `(920, 616)`.
- Name the helper `tap_gameplay_play_button(ctx)` and return `None`.
- Send the device tap with label `"Play"`.
- Do not add template lookup, retries, or a synthetic success value.
- Preserve level-recording validation before spending a run.
- Keep `assets/play_with_double_coins.png`; asset deletion is outside scope.
- Preserve all CLI, Random Boost, optional boost, gameplay runner, and result-cleanup behavior.

---

### Task 1: Replace the template-based gameplay-start tap

**Files:**
- Modify: `scripts/auto_runner.py:53-54,77-78,102-107,155-171,329-345`
- Test: `scripts/test_auto_runner.py:231-273,411-498`

**Interfaces:**
- Consumes: `AutoRunnerContext.device.tap(x: int, y: int, label: str = "") -> tuple[int, int]`
- Produces: `GAMEPLAY_PLAY_XY: tuple[int, int] = (920, 616)`
- Produces: `tap_gameplay_play_button(ctx: AutoRunnerContext) -> None`
- Preserves: `run_after_start(ctx, mode, no_cookie_relay, fast_start, episode, quit_on_collect_mystery_box=None) -> None`

- [ ] **Step 1: Write the failing direct-tap test**

In `scripts/test_auto_runner.py`, remove the assertion for `PLAY_WITH_DOUBLE_COINS_TARGET` and replace the template-selection test block with:

```python
assert auto_runner.GAMEPLAY_PLAY_XY == (920, 616)

original_device_tap = ctx.device.tap
gameplay_play_taps = []
try:
    ctx.device.tap = (
        lambda x, y, label="": gameplay_play_taps.append((x, y, label))
        or (x, y)
    )
    assert auto_runner.tap_gameplay_play_button(ctx) is None
    assert gameplay_play_taps == [(920, 616, "Play")]
finally:
    ctx.device.tap = original_device_tap
```

Rename every saved/mock reference in the later `run_after_start()` tests:

```python
original_tap_gameplay_play_button = auto_runner.tap_gameplay_play_button
```

Use `auto_runner.tap_gameplay_play_button = lambda _ctx: tap_calls.append("tap")` in the invalid-episode ordering test, and `lambda _ctx: None` in tests that only need gameplay to start. Restore `original_tap_gameplay_play_button` in each matching `finally` block.

- [ ] **Step 2: Run the test and verify it fails for the missing coordinate API**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_auto_runner.py
```

Expected: `AttributeError` for `GAMEPLAY_PLAY_XY` or `tap_gameplay_play_button`, proving the new contract is not implemented yet.

- [ ] **Step 3: Implement the minimal direct-tap helper**

In `scripts/auto_runner.py`, remove:

```python
PLAY_WITH_DOUBLE_COINS_TEMPLATE = ASSETS / "play_with_double_coins.png"

PLAY_WITH_DOUBLE_COINS_TARGET = TemplateTarget(
    "Play with Double Coins",
    PLAY_WITH_DOUBLE_COINS_TEMPLATE,
    verify_gone=True,
)
```

Add the coordinate beside the other reference-coordinate constants:

```python
GAMEPLAY_PLAY_XY = (920, 616)
PAUSE_XY = (1194, 37)
```

Replace `tap_play_with_double_coins_button()` with:

```python
def tap_gameplay_play_button(ctx: AutoRunnerContext) -> None:
    ctx.device.tap(*GAMEPLAY_PLAY_XY, label="Play")
```

Replace the conditional template-based call in `run_after_start()`:

```python
    tap_gameplay_play_button(ctx)
```

- [ ] **Step 4: Run the focused regression test**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_auto_runner.py
```

Expected final output:

```text
Collected 2 mystery boxes.
ok
```

- [ ] **Step 5: Check for dead references and source-integrity issues**

Run:

```powershell
rg -n "tap_play_with_double_coins_button|PLAY_WITH_DOUBLE_COINS_(TEMPLATE|TARGET)" scripts README.md
git -c safe.directory=E:/runner diff --check
git -c safe.directory=E:/runner diff -- scripts/auto_runner.py scripts/test_auto_runner.py
```

Expected: `rg` finds no obsolete code references; `diff --check` exits successfully; the diff contains only the coordinate helper, caller change, dead symbol removal, and corresponding test updates.

- [ ] **Step 6: Commit the verified behavior change**

```powershell
git -c safe.directory=E:/runner add -- scripts/auto_runner.py scripts/test_auto_runner.py
git -c safe.directory=E:/runner diff --cached --check
git -c safe.directory=E:/runner commit -m "refactor: tap gameplay Play by coordinate"
```

Expected: one commit modifying only the runner and its assertion script.
