# Fast Start Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `--fast-start` flag that taps `activate_fast_start.png` once during gameplay in every mode without disabling recorded level replay.

**Architecture:** Each gameplay runner receives a separate optional `fast_start_template` beside its existing Cookie Relay template. Its existing every-15th-frame full-screen check taps Fast Start once and then stops checking only that template; `auto_runner.py` supplies the template when `--fast-start` is present.

**Tech Stack:** Python 3.12+, `argparse`, existing OpenCV template matching, existing ADB input wrappers, plain-Python assert self-checks.

## Global Constraints

- Fast Start purchasing during menu setup remains unchanged.
- `--fast-start` defaults to false and enables only in-run activation.
- A runner stops checking Fast Start after its first successful tap.
- Gameplay, result detection, Cookie Relay handling, and recorded level replay continue after Fast Start activation.
- Cookie Relay retains its existing level-replay shutdown behavior.
- Add no dependency and no generic activation-policy abstraction.
- Preserve the user's existing `scripts/launch_mumu_cookierun.py` change.

## File Structure

- Modify `avd_runner/none.py`: optional Fast Start template and one-shot handling in no-gameplay mode.
- Modify `avd_runner/reactive.py`: optional Fast Start template and one-shot handling alongside obstacle play.
- Modify `avd_runner/levels.py`: optional Fast Start template and state that does not alter recorded replay.
- Modify `scripts/test_none.py`, `scripts/test_reactive.py`, and `scripts/test_levels.py`: runner-level regression checks.
- Modify `scripts/auto_runner.py`: asset constant, CLI flag, runner wiring, and orchestration argument.
- Modify `scripts/test_auto_runner.py`: parsing and wiring checks.
- Modify `README.md`: user-facing flag documentation.
- Add existing user-provided `assets/activate_fast_start.png` to the feature commit without editing its bytes.

---

### Task 1: Teach all gameplay runners one-shot Fast Start activation

**Files:**
- Modify: `scripts/test_none.py`
- Modify: `scripts/test_reactive.py`
- Modify: `scripts/test_levels.py`
- Modify: `avd_runner/none.py`
- Modify: `avd_runner/reactive.py`
- Modify: `avd_runner/levels.py`

**Interfaces:**
- Consumes: each runner's existing `find_template(frame, path, threshold=0.85)` and `_tap()` method.
- Produces: optional constructor keyword `fast_start_template: Path | None = None` on `NoneRunner`, `ReactiveRunner`, and `LevelReplayer`; one successful tap labeled `fast_start`; one-shot handled state.

- [ ] **Step 1: Write the failing NoneRunner check**

Update `scripts/test_none.py` so the runner receives the Fast Start template:

```python
runner = none.NoneRunner(
    device,
    capture,
    exit_template=Path("result.png"),
    relay_template=Path("relay.png"),
    fast_start_template=Path("fast-start.png"),
)
```

Make the fake matcher keep returning Fast Start through frame 2, return relay on frame 2, and result on frame 3:

```python
def fake_find_template(frame, template_path, threshold=0.85):
    if template_path == Path("fast-start.png") and frame in ("frame-1", "frame-2"):
        return TemplateMatch(x=20, y=30, width=8, height=8, score=0.99)
    if template_path == Path("relay.png") and frame == "frame-2":
        return TemplateMatch(x=10, y=20, width=8, height=8, score=0.99)
    if template_path == Path("result.png") and frame == "frame-3":
        return TemplateMatch(x=100, y=200, width=8, height=8, score=0.99)
    return None
```

Replace the final assertions with:

```python
assert capture.count == 3
assert [kwargs["label"] for _args, kwargs in device.shell.swipes] == [
    "fast_start",
    "relay",
]
assert runner._fast_start_handled
```

The persistent frame-2 match proves Fast Start is not tapped twice.

- [ ] **Step 2: Write the failing ReactiveRunner check**

In the existing `_check_exit_or_relay` seam in `scripts/test_reactive.py`, initialize:

```python
helper._fast_start_template = Path("fast-start.png")
helper._fast_start_handled = False
```

Before the relay assertion, use a matcher that returns Fast Start and call the check twice:

```python
reactive.find_template = lambda _frame, template, threshold=0.85: (
    TemplateMatch(20, 30, 8, 8, 0.99)
    if template == Path("fast-start.png")
    else None
)
assert not helper._check_exit_or_relay("frame", shell)
assert helper._fast_start_handled
assert shell.swipes[-1] == (24, 34, 80, "fast_start")
fast_start_swipes = len(shell.swipes)
assert not helper._check_exit_or_relay("frame", shell)
assert len(shell.swipes) == fast_start_swipes
```

Then retain the existing relay and result assertions. Set `runner._fast_start_template = None` and `runner._fast_start_handled = False` in the later `object.__new__(ReactiveRunner)` loop fixture.

- [ ] **Step 3: Write the failing LevelReplayer check**

In `scripts/test_levels.py`, add a Fast Start seam before the Cookie Relay seam:

```python
fast_runner = object.__new__(LevelReplayer)
fast_runner._exit_template = Path("result.png")
fast_runner._relay_template = None
fast_runner._fast_start_template = Path("activate_fast_start.png")
fast_shell = FakeShell()
recorded = {
    "taps": [
        {"t": 0.0, "progress": 0.2, "x": 100, "y": 200, "duration": 0.08}
    ],
    "path": Path("level_01_001.json"),
}
fast_state = ReplayState(level=1, in_level=True, recorded=recorded)

original_find_template = levels_module.find_template
original_randint = levels_module.random.randint
original_uniform = levels_module.random.uniform
try:
    levels_module.find_template = lambda _frame, template, threshold=0.85: (
        TemplateMatch(10, 20, 30, 40, 0.99)
        if template == fast_runner._fast_start_template
        else None
    )
    levels_module.random.randint = lambda _a, _b: 0
    levels_module.random.uniform = lambda _a, _b: 1.0

    assert not fast_runner._check_exit_or_relay("fast-frame", fast_state, fast_shell)
    assert fast_state.fast_start_handled
    assert fast_state.replay_enabled
    assert fast_state.recorded is recorded
    assert fast_shell.swipes[0][1] == {"background": False, "label": "fast_start"}

    assert not fast_runner._check_exit_or_relay("fast-frame", fast_state, fast_shell)
    assert len(fast_shell.swipes) == 1
    fast_runner._play_due_taps(fast_state, fast_shell, progress=1.0, now=100.0)
    assert len(fast_shell.swipes) == 2
finally:
    levels_module.find_template = original_find_template
    levels_module.random.randint = original_randint
    levels_module.random.uniform = original_uniform
```

Set `relay_runner._fast_start_template = None` in the existing Cookie Relay fixture so that test continues to isolate relay behavior. Set `_fast_start_template = None` on any other `LevelReplayer` fixture created via `object.__new__()` that reaches `_check_exit_or_relay()`.

- [ ] **Step 4: Run the runner checks and verify RED**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_none.py
.venv\Scripts\python.exe scripts\test_reactive.py
.venv\Scripts\python.exe scripts\test_levels.py
```

Expected: at least the constructor or handled-state assertion fails because Fast Start support is absent. Fix only test syntax/setup errors; retain an assertion or signature failure caused by missing behavior.

- [ ] **Step 5: Implement NoneRunner support**

Add the constructor argument and state in `avd_runner/none.py`:

```python
fast_start_template: Path | None = None,
```

```python
self._fast_start_template = fast_start_template
self._fast_start_handled = False
```

After result detection and before Cookie Relay detection, add:

```python
if not self._fast_start_handled and self._fast_start_template is not None:
    match = find_template(frame, self._fast_start_template, threshold=0.85)
    if match:
        self._tap(shell, match.center_x, match.center_y, 80, "fast_start")
        self._fast_start_handled = True
        print("Tapped Activate Fast Start.")
```

- [ ] **Step 6: Implement ReactiveRunner support**

Add the same optional constructor argument and instance state in `avd_runner/reactive.py`:

```python
fast_start_template: Path | None = None,
```

```python
self._fast_start_template = fast_start_template
self._fast_start_handled = False
```

In `_check_exit_or_relay()`, after result detection and before relay detection, add:

```python
if not self._fast_start_handled and self._fast_start_template is not None:
    match = find_template(frame, self._fast_start_template, threshold=0.85)
    if match:
        self._tap(shell, match.center_x, match.center_y, 80, "fast_start")
        self._fast_start_handled = True
        print("Tapped Activate Fast Start.")
```

- [ ] **Step 7: Implement LevelReplayer support without disabling replay**

Add state in `ReplayState`:

```python
fast_start_handled: bool = False
```

Add `fast_start_template: Path | None = None` to `LevelReplayer.__init__()` and store it as `self._fast_start_template`.

In `_check_exit_or_relay()`, after result detection and before relay detection, add:

```python
if not state.fast_start_handled and self._fast_start_template is not None:
    match = find_template(frame, self._fast_start_template, threshold=0.85)
    if match:
        self._tap(
            shell,
            match.center_x,
            match.center_y,
            0.08,
            background=False,
            label="fast_start",
        )
        state.fast_start_handled = True
        print("Tapped Activate Fast Start; recorded replay continues.")
```

Do not change `state.replay_enabled`, `state.recorded`, `state.tap_index`, or level progress fields in this block.

- [ ] **Step 8: Run the runner checks and verify GREEN**

Run the three commands from Step 4 again.

Expected: every command exits 0 and ends with `ok` (allowing existing documented skip messages for unavailable captures).

- [ ] **Step 9: Commit runner support**

```powershell
git -c safe.directory=E:/runner add -- avd_runner/none.py avd_runner/reactive.py avd_runner/levels.py scripts/test_none.py scripts/test_reactive.py scripts/test_levels.py
git -c safe.directory=E:/runner commit -m "feat: support fast start activation"
```

Verify `scripts/launch_mumu_cookierun.py` and `assets/activate_fast_start.png` remain unstaged at this checkpoint.

---

### Task 2: Wire `--fast-start` through auto-runner

**Files:**
- Modify: `scripts/test_auto_runner.py`
- Modify: `scripts/auto_runner.py`
- Modify: `README.md`
- Add: `assets/activate_fast_start.png` (existing user-provided asset; do not edit)

**Interfaces:**
- Consumes: Task 1 constructor keyword `fast_start_template: Path | None` on all gameplay runners.
- Produces: `ACTIVATE_FAST_START_TEMPLATE`; boolean `args.fast_start`; `build_gameplay_runner(ctx, mode, relay_template, fast_start_template, episode_dir)`; `run_after_start(ctx, mode, no_cookie_relay, fast_start, episode)`.

- [ ] **Step 1: Write failing CLI and runner-wiring checks**

In `scripts/test_auto_runner.py`, add parsing assertions:

```python
default_args = auto_runner.parse_args([])
fast_args = auto_runner.parse_args(["--fast-start"])
assert vars(default_args).get("fast_start") is False
assert vars(fast_args).get("fast_start") is True
```

Update both existing `build_gameplay_runner()` calls to pass `auto_runner.ACTIVATE_FAST_START_TEMPLATE` between the relay template and episode directory, then assert:

```python
assert instances[0].kwargs["fast_start_template"] == auto_runner.ACTIVATE_FAST_START_TEMPLATE
```

Update the bad-episode call to:

```python
auto_runner.run_after_start(
    ctx,
    "levels",
    False,
    True,
    "definitely_missing_episode",
)
```

Update the orchestration fake and fixtures:

```python
auto_runner.run_after_start = (
    lambda _ctx, _mode, _no_relay, _fast_start, _episode: order.append("gameplay")
)
```

```python
fast_start=False,
```

The regular `parse_args()` path already supplies `fast_start=False`; the explicit `SimpleNamespace` skip fixture needs the added field.

- [ ] **Step 2: Run the auto-runner check and verify RED**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_auto_runner.py
```

Expected: FAIL because `ACTIVATE_FAST_START_TEMPLATE`, `--fast-start`, or the new function arguments do not exist.

- [ ] **Step 3: Add the asset constant and CLI flag**

In `scripts/auto_runner.py`, add:

```python
ACTIVATE_FAST_START_TEMPLATE = ASSETS / "activate_fast_start.png"
```

Add beside the other gameplay options:

```python
parser.add_argument(
    "--fast-start",
    action="store_true",
    help="Tap Activate Fast Start when it appears during gameplay.",
)
```

- [ ] **Step 4: Wire the optional template through runner construction**

Change the signature to:

```python
def build_gameplay_runner(
    ctx: AutoRunnerContext,
    mode: str,
    relay_template: Path | None,
    fast_start_template: Path | None,
    episode_dir: Path | None,
):
```

Pass `fast_start_template=fast_start_template` to `LevelReplayer`, `ReactiveRunner`, and `NoneRunner`.

Change `run_after_start()` to accept `fast_start: bool`, derive the template, and pass it to the builder:

```python
fast_start_template = ACTIVATE_FAST_START_TEMPLATE if fast_start else None
```

```python
runner = build_gameplay_runner(
    ctx,
    mode,
    relay_template,
    fast_start_template,
    episode_dir,
)
```

Update `run_once()`:

```python
run_after_start(
    ctx,
    args.mode,
    args.no_cookie_relay,
    args.fast_start,
    args.episode,
)
```

- [ ] **Step 5: Run the auto-runner check and verify GREEN**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_auto_runner.py
```

Expected: exit code 0 and final output `ok`.

- [ ] **Step 6: Document the option**

In the README “Other flags” paragraph, add:

```markdown
`--fast-start` (tap Activate Fast Start once when it appears during gameplay; recorded level replay continues),
```

- [ ] **Step 7: Run full verification**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_auto_runner.py
.venv\Scripts\python.exe scripts\test_levels.py
.venv\Scripts\python.exe scripts\test_reactive.py
.venv\Scripts\python.exe scripts\test_captcha.py
.venv\Scripts\python.exe scripts\test_capture.py
.venv\Scripts\python.exe scripts\test_device.py
.venv\Scripts\python.exe scripts\test_none.py
```

Expected: every command exits 0; runnable checks print `ok`, while checks requiring unavailable local captures may print their documented skip messages.

Then run:

```powershell
git -c safe.directory=E:/runner diff --check
git -c safe.directory=E:/runner status --short
```

Expected: `diff --check` exits 0. Only the Task 2 files and the unrelated pre-existing launcher edit remain uncommitted.

- [ ] **Step 8: Commit CLI wiring, documentation, and asset**

```powershell
git -c safe.directory=E:/runner add -- scripts/auto_runner.py scripts/test_auto_runner.py README.md assets/activate_fast_start.png
git -c safe.directory=E:/runner commit -m "feat: add fast start option"
```

Verify `scripts/launch_mumu_cookierun.py` remains unstaged and unchanged by this feature.
