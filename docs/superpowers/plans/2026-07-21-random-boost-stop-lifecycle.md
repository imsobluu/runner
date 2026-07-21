# Random Boost Stop Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Confirm Random Boost Multi-Buy completion from the Stop button's appearance and disappearance instead of unrelated boost-store templates.

**Architecture:** Keep the lifecycle orchestration in `ensure_random_boost_setup()`. Reuse `avd_runner.menu.wait_for_template()` to prove rolling started and `wait_template_gone()` with a 120-second timeout to prove rolling finished; no new polling abstraction is needed.

**Tech Stack:** Python 3, OpenCV template matching through existing menu helpers, the repository's script-style assertion tests.

## Global Constraints

- Preserve the existing CLI and exclusive checkbox-selection behavior.
- Require `stop.png` to appear before its absence can confirm completion.
- Allow up to 120 seconds for `stop.png` to disappear.
- Raise stage-specific `RunnerError` messages when rolling does not start or finish.
- Add no dependency, OCR path, per-boost image set, or generic policy abstraction.
- Preserve and exclude unrelated working-tree changes from this feature's commit.

---

### Task 1: Confirm the Multi-Buy lifecycle with the Stop button

**Files:**
- Add: `assets/stop.png` (existing user-supplied template; stage the image unchanged)
- Modify: `scripts/auto_runner.py:13-19,51-58,599-626`
- Test: `scripts/test_auto_runner.py:155-195`

**Interfaces:**
- Consumes: `wait_for_template(ctx, name, template_path, banner_template, threshold=0.85, attempts=120, delay_seconds=1.0) -> bool`
- Consumes: `wait_template_gone(ctx, template_path, threshold, banner_template, timeout=5.0, poll_seconds=0.2) -> bool`
- Produces: `STOP_TEMPLATE: Path`
- Preserves: `ensure_random_boost_setup(ctx: AutoRunnerContext, desired: str) -> None`

- [ ] **Step 1: Replace the old success-path test with a failing Stop lifecycle test**

In `scripts/test_auto_runner.py`, save and mock both menu helpers alongside the existing setup mocks. Keep `wait_for_any_template()` for the initial boost-screen lookup only and assert the complete order:

```python
setup_order = []
original_wait_for_any_template = auto_runner.wait_for_any_template
original_wait_for_template = auto_runner.wait_for_template
original_wait_template_gone = auto_runner.wait_template_gone
original_tap_random_boost_button = auto_runner.tap_random_boost_button
original_tap_multi_button = auto_runner.tap_multi_button
original_reconcile = auto_runner.reconcile_random_boost_checkboxes
original_tap_multi_buy_button = auto_runner.tap_multi_buy_button
try:
    auto_runner.wait_for_any_template = lambda *_args, **_kwargs: "Random Boost"
    auto_runner.wait_for_template = (
        lambda _ctx, name, path, _banner, **_kwargs: setup_order.append(
            ("wait-present", name, path)
        )
        or True
    )
    auto_runner.wait_template_gone = (
        lambda _ctx, path, threshold, _banner, **kwargs: setup_order.append(
            ("wait-gone", path, threshold, kwargs["timeout"])
        )
        or True
    )
    auto_runner.tap_random_boost_button = lambda _ctx: setup_order.append("random") or True
    auto_runner.tap_multi_button = lambda _ctx: setup_order.append("multi") or True
    auto_runner.reconcile_random_boost_checkboxes = (
        lambda _ctx, boost: setup_order.append(("reconcile", boost))
    )
    auto_runner.tap_multi_buy_button = lambda _ctx: setup_order.append("buy") or True

    auto_runner.ensure_random_boost_setup(ctx, "magnetic-aura")

    assert setup_order == [
        "random",
        "multi",
        ("reconcile", "magnetic-aura"),
        "buy",
        ("wait-present", "Stop", auto_runner.STOP_TEMPLATE),
        ("wait-gone", auto_runner.STOP_TEMPLATE, 0.85, 120.0),
    ]
finally:
    auto_runner.wait_for_any_template = original_wait_for_any_template
    auto_runner.wait_for_template = original_wait_for_template
    auto_runner.wait_template_gone = original_wait_template_gone
    auto_runner.tap_random_boost_button = original_tap_random_boost_button
    auto_runner.tap_multi_button = original_tap_multi_button
    auto_runner.reconcile_random_boost_checkboxes = original_reconcile
    auto_runner.tap_multi_buy_button = original_tap_multi_buy_button
```

- [ ] **Step 2: Add failing tests for both lifecycle timeouts**

Within the same protected mock block, run these cases before restoring the original functions:

```python
auto_runner.wait_for_template = lambda *_args, **_kwargs: False
try:
    auto_runner.ensure_random_boost_setup(ctx, "magnetic-aura")
except auto_runner.RunnerError as exc:
    assert str(exc) == "Random Boost rolling did not start."
else:
    raise AssertionError("missing Stop button should fail setup")

auto_runner.wait_for_template = lambda *_args, **_kwargs: True
auto_runner.wait_template_gone = lambda *_args, **_kwargs: False
try:
    auto_runner.ensure_random_boost_setup(ctx, "magnetic-aura")
except auto_runner.RunnerError as exc:
    assert str(exc) == "Random Boost rolling did not finish."
else:
    raise AssertionError("persistent Stop button should fail setup")
```

Retain the existing reconciliation-failure assertion that Multi-Buy is never tapped when exclusive checkbox verification fails.

- [ ] **Step 3: Run the test and verify the new contract fails**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_auto_runner.py
```

Expected: failure while installing the new mocks because `auto_runner.wait_for_template`, `auto_runner.wait_template_gone`, or `auto_runner.STOP_TEMPLATE` is not yet defined.

- [ ] **Step 4: Implement the minimal Stop lifecycle**

Extend the menu import and template constants in `scripts/auto_runner.py`:

```python
from avd_runner.menu import (
    MenuAutomationError,
    debug_save_tap,
    is_toggle_selected,
    tap_template,
    wait_for_any_template,
    wait_for_template,
    wait_template_gone,
)

# beside the other Random Boost templates
STOP_TEMPLATE = ASSETS / "stop.png"
```

Replace the post-Multi-Buy boost-store lookup in `ensure_random_boost_setup()` with:

```python
    if not wait_for_template(
        ctx,
        "Stop",
        STOP_TEMPLATE,
        CAPTCHA_BANNER_TEMPLATE,
        attempts=20,
        delay_seconds=0.25,
    ):
        raise RunnerError("Random Boost rolling did not start.")
    if not wait_template_gone(
        ctx,
        STOP_TEMPLATE,
        0.85,
        CAPTCHA_BANNER_TEMPLATE,
        timeout=120.0,
    ):
        raise RunnerError("Random Boost rolling did not finish.")
```

- [ ] **Step 5: Run the focused test and verify it passes**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_auto_runner.py
```

Expected final output:

```text
Collected 2 mystery boxes.
ok
```

- [ ] **Step 6: Verify source integrity and inspect the scoped diff**

Run:

```powershell
git -c safe.directory=E:/runner diff --check
git -c safe.directory=E:/runner diff -- scripts/auto_runner.py scripts/test_auto_runner.py assets/stop.png
```

Expected: `diff --check` exits successfully; the inspected feature hunks contain only the Stop lifecycle while pre-existing unrelated edits remain unstaged.

- [ ] **Step 7: Commit only the Stop lifecycle hunks and asset**

Stage only the new import, constant, completion logic, corresponding tests, and the supplied image. Verify the cached diff excludes unrelated modifications before committing:

```powershell
git -c safe.directory=E:/runner diff --cached --check
git -c safe.directory=E:/runner diff --cached --stat
git -c safe.directory=E:/runner commit -m "fix: wait for random boost roll completion"
```

Expected: one commit containing `assets/stop.png` and only the relevant hunks from the two Python files.
