# Skip Random Boost Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--skip-random-boost` so the auto-runner can bypass required boost setup while its gameplay-start function accepts either the Double Coins or plain Play template.

**Architecture:** Keep the feature in `scripts/auto_runner.py`. The flag only gates `ensure_double_coins_setup()` in `run_once()`; the existing final-play function becomes template-agnostic by polling both existing targets in priority order and tapping the one found.

**Tech Stack:** Python 3.12+, `argparse`, existing `avd_runner.menu` helpers, plain-Python assert self-checks.

## Global Constraints

- Preserve current behavior when `--skip-random-boost` is absent.
- When the flag is present, bypass the entire `ensure_double_coins_setup()` call.
- Check `PLAY_WITH_DOUBLE_COINS_TARGET` before `PLAY_TARGET` because the plain crop can match inside the Double Coins screen.
- Add no dependency or generic boost-policy abstraction.
- Do not modify the user's existing `scripts/launch_mumu_cookierun.py` change.

## File Structure

- Modify `scripts/auto_runner.py`: CLI flag, setup gate, and dual-template gameplay-start tap.
- Modify `scripts/test_auto_runner.py`: regression checks for parsing, orchestration, target order, both play variants, and no-match behavior.
- Modify `README.md`: document the flag and dual-template gameplay start.

---

### Task 1: Add the skip flag and dual-template gameplay start

**Files:**
- Modify: `scripts/test_auto_runner.py`
- Modify: `scripts/auto_runner.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: existing `TemplateTarget`, `PLAY_WITH_DOUBLE_COINS_TARGET`, `PLAY_TARGET`, `wait_for_any_template()`, and `tap_target()`.
- Produces: `parse_args(argv)` with boolean `skip_random_boost`; `tap_play_with_double_coins_button(ctx, attempts=5) -> bool` accepting either play target; `run_once(ctx, args)` conditionally bypassing `ensure_double_coins_setup()`.

- [ ] **Step 1: Write failing parsing and orchestration checks**

In `scripts/test_auto_runner.py`, extend the parse assertions with:

```python
default_args = auto_runner.parse_args([])
skip_args = auto_runner.parse_args(["--skip-random-boost"])
assert vars(default_args).get("skip_random_boost") is False
assert vars(skip_args).get("skip_random_boost") is True
```

Replace the current relic/play ordering assertion block with exact default and skipped flows:

```python
order = []
try:
    auto_runner.claim_relic_if_alert = lambda _ctx: order.append("relic") or False
    auto_runner.tap_play_button = lambda _ctx: order.append("play") or True
    auto_runner.ensure_double_coins_setup = lambda _ctx: order.append("double_coins")
    auto_runner.buy_optional_boosts = lambda _ctx, _skip: order.append("boosts")
    auto_runner.run_after_start = lambda _ctx, _mode, _no_relay, _episode: order.append("gameplay")
    auto_runner.clear_results = lambda _ctx: order.append("clear")

    auto_runner.run_once(ctx, auto_runner.parse_args(["--mode", "none"]))
    assert order == ["relic", "play", "double_coins", "boosts", "gameplay", "clear"]

    order.clear()
    skip_args = types.SimpleNamespace(
        mode="none",
        no_cookie_relay=False,
        episode=None,
        skip_top_row_boosts=False,
        skip_random_boost=True,
    )
    auto_runner.run_once(ctx, skip_args)
    assert order == ["relic", "play", "boosts", "gameplay", "clear"]
finally:
    auto_runner.tap_play_button = original_tap_play_button
    auto_runner.claim_relic_if_alert = original_claim_relic_if_alert
    auto_runner.ensure_double_coins_setup = original_ensure_double_coins_setup
    auto_runner.buy_optional_boosts = original_buy_optional_boosts
    auto_runner.run_after_start = original_run_after_start
    auto_runner.clear_results = original_clear_results
```

- [ ] **Step 2: Write failing dual-template gameplay-start checks**

Add this focused check after the target-definition assertions:

```python
original_wait_for_any_template = auto_runner.wait_for_any_template
original_tap_target = auto_runner.tap_target
lookups = []
tapped = []
expected_lookup = [
    (auto_runner.PLAY_WITH_DOUBLE_COINS_TARGET.name, auto_runner.PLAY_WITH_DOUBLE_COINS_TARGET.path),
    (auto_runner.PLAY_TARGET.name, auto_runner.PLAY_TARGET.path),
]
try:
    for seen, expected_target in (
        (auto_runner.PLAY_WITH_DOUBLE_COINS_TARGET.name, auto_runner.PLAY_WITH_DOUBLE_COINS_TARGET),
        (auto_runner.PLAY_TARGET.name, auto_runner.PLAY_TARGET),
    ):
        lookups.clear()
        tapped.clear()
        auto_runner.wait_for_any_template = (
            lambda _ctx, targets, _banner, **_kwargs: lookups.append(targets) or seen
        )
        auto_runner.tap_target = (
            lambda _ctx, target, **_kwargs: tapped.append(target) or True
        )
        assert auto_runner.tap_play_with_double_coins_button(ctx)
        assert lookups == [expected_lookup]
        assert tapped == [expected_target]

    tapped.clear()
    auto_runner.wait_for_any_template = lambda _ctx, _targets, _banner, **_kwargs: None
    assert not auto_runner.tap_play_with_double_coins_button(ctx)
    assert tapped == []
finally:
    auto_runner.wait_for_any_template = original_wait_for_any_template
    auto_runner.tap_target = original_tap_target
```

- [ ] **Step 3: Run the self-check and verify RED**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_auto_runner.py
```

Expected: FAIL on the new `skip_random_boost` parsing assertion or dual-template target assertion because neither behavior exists yet. The test must reach an assertion failure caused by missing behavior, not a syntax/import error.

- [ ] **Step 4: Add the CLI flag**

In `parse_args()`, place the new option beside the existing boost-skip option:

```python
parser.add_argument(
    "--skip-random-boost",
    action="store_true",
    help="Skip Random Boost, Multi, Double Coins, and Multi Buy setup.",
)
```

- [ ] **Step 5: Gate required boost setup**

Change the setup portion of `run_once()` to:

```python
if not args.skip_random_boost:
    ensure_double_coins_setup(ctx)
buy_optional_boosts(ctx, args.skip_top_row_boosts)
run_after_start(ctx, args.mode, args.no_cookie_relay, args.episode)
```

- [ ] **Step 6: Make the final-play function accept either template**

Replace the body of `tap_play_with_double_coins_button()` with:

```python
targets = (PLAY_WITH_DOUBLE_COINS_TARGET, PLAY_TARGET)
seen = wait_for_any_template(
    ctx,
    [(target.name, target.path) for target in targets],
    CAPTCHA_BANNER_TEMPLATE,
    attempts=attempts,
)
for target in targets:
    if target.name == seen:
        return tap_target(ctx, target, attempts=attempts)
return False
```

This retains each target's existing tap policy, including `verify_gone=True` for the Double Coins target.

- [ ] **Step 7: Run the focused self-check and verify GREEN**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_auto_runner.py
```

Expected: exit code 0 and final output `ok`.

- [ ] **Step 8: Document the option**

In the README's “Other flags” paragraph, add:

```markdown
`--skip-random-boost` (skip the Random Boost / Multi / Double Coins / Multi Buy setup; the run-start step accepts either the Double Coins or plain Play button),
```

- [ ] **Step 9: Run full relevant verification**

Run each self-check:

```powershell
.venv\Scripts\python.exe scripts\test_auto_runner.py
.venv\Scripts\python.exe scripts\test_levels.py
.venv\Scripts\python.exe scripts\test_reactive.py
.venv\Scripts\python.exe scripts\test_captcha.py
.venv\Scripts\python.exe scripts\test_capture.py
.venv\Scripts\python.exe scripts\test_device.py
.venv\Scripts\python.exe scripts\test_none.py
```

Expected: every command exits 0; runnable checks print `ok`, while checks requiring unavailable local captures/recordings may print their documented skip messages.

Then run:

```powershell
git -c safe.directory=E:/runner diff --check
git -c safe.directory=E:/runner diff -- scripts/auto_runner.py scripts/test_auto_runner.py README.md
```

Expected: `diff --check` exits 0, and the diff contains only the approved feature, its tests, and documentation.

- [ ] **Step 10: Commit the implementation**

```powershell
git -c safe.directory=E:/runner add -- scripts/auto_runner.py scripts/test_auto_runner.py README.md
git -c safe.directory=E:/runner commit -m "feat: add skip random boost option"
```

Verify `scripts/launch_mumu_cookierun.py` remains unstaged and unchanged by this task.
