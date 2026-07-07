# Refactor Plan

Status: in progress. This plan preserves existing behavior unless a later phase
is explicitly approved as a behavior change.

## Current architecture

- `scripts/auto_runner.py` is the full bot entry point. It owns CLI parsing,
  run-loop orchestration, setup policy, boost policy, gameplay-mode selection,
  and result cleanup.
- `avd_runner/menu.py` owns menu-phase screenshot/template/tap helpers using the
  shared WGC capture session and ADB input path.
- `avd_runner/debug_session.py` owns saved tap captures and live debug-window
  state. `avd_runner/debugview.py` renders the OpenCV overlay.
- `avd_runner/device.py` owns ADB input injection. Capture is Windows-only WGC;
  ADB is retained only for device input.
- `avd_runner/levels.py`, `avd_runner/reactive.py`, and `avd_runner/none.py`
  are gameplay drivers. They consume a capture object and use the shared device
  input shell.
- `avd_runner/captcha.py` owns captcha detection/selection heuristics.
- Tests are plain Python scripts under `scripts/test_*.py`.

## Highest-risk assumptions

- Existing gameplay timing is fragile; changes to `levels.py`, `reactive.py`,
  or input dispatch need captured-frame or fake-device coverage first.
- Captcha behavior is data/heuristic sensitive; refactor only after fixture
  tests prove modal detection and card selection behavior.
- WGC capture internals are platform-specific; avoid large changes unless a
  Windows emulator can be used for manual verification.
- ADB remains intentionally present for device inputs only.

## Validation commands

Use these before committing refactor phases:

```powershell
.\.venv\Scripts\python.exe -m compileall avd_runner scripts examples
.\.venv\Scripts\python.exe scripts\test_auto_runner.py
.\.venv\Scripts\python.exe scripts\test_device.py
.\.venv\Scripts\python.exe scripts\test_none.py
.\.venv\Scripts\python.exe scripts\test_captcha.py
.\.venv\Scripts\python.exe scripts\test_levels.py
.\.venv\Scripts\python.exe scripts\test_reactive.py
```

Known note: `test_levels.py` may print that an existing `ep02` recording is v4
and needs v5, then still exit `ok`; that is handled compatibility behavior.

## Phase 1: add seams and low-risk orchestration cleanup

- [x] Extract shared menu automation helpers.
  - Files: `scripts/auto_runner.py`, `avd_runner/menu.py`
  - Goal: remove duplicated menu screenshot/template/tap logic from the entry
    point.
  - Verification: `test_auto_runner.py`, compileall.

- [x] Introduce explicit runner context.
  - Files: `scripts/auto_runner.py`
  - Goal: pass device, capture, debug, and captcha state explicitly.
  - Verification: `test_auto_runner.py`.

- [x] Declare menu template targets.
  - Files: `scripts/auto_runner.py`
  - Goal: centralize retry thresholds, attempts, and verify-gone policy.
  - Verification: target policy assertions in `test_auto_runner.py`.

- [x] Normalize auto-runner failures.
  - Files: `scripts/auto_runner.py`, `avd_runner/menu.py`
  - Goal: helpers raise typed exceptions; only `main()` exits the process.
  - Verification: `test_auto_runner.py`.

- [x] Extract debug session state.
  - Files: `avd_runner/debug_session.py`, `scripts/auto_runner.py`
  - Goal: isolate saved-frame and live-window debug state.
  - Verification: debug save assertions in `test_auto_runner.py`.

- [x] Centralize input shell lifecycle.
  - Files: `avd_runner/device.py`, `avd_runner/levels.py`,
    `avd_runner/reactive.py`, `avd_runner/none.py`
  - Goal: avoid repeated manual `open_input_shell()` cleanup.
  - Verification: `test_device.py`, gameplay tests.

## Phase 2: decompose orchestration while preserving behavior

- [x] Fix extracted menu error/path behavior.
  - Files: `avd_runner/menu.py`, `scripts/auto_runner.py`
  - Goal: keep screenshot debug paths rooted at the repo and avoid direct
    `SystemExit` from menu helpers.
  - Verification: `test_auto_runner.py`.

- [x] Update docs for the refactored module layout.
  - Files: `README.md`
  - Goal: keep project structure and test docs current.
  - Verification: docs-only review.

- [x] Normalize episode selection failures.
  - Files: `scripts/auto_runner.py`, `scripts/test_auto_runner.py`
  - Goal: make `resolve_episode_dir()` testable without process exit.
  - Verification: `test_auto_runner.py`.

- [x] Extract gameplay runner factory.
  - Files: `scripts/auto_runner.py`, `scripts/test_auto_runner.py`
  - Goal: separate gameplay runner construction from final Play tap and runner
    execution.
  - Verification: fake-runner tests.

- [x] Decompose one-run flow.
  - Files: `scripts/auto_runner.py`
  - Goal: split `run_once()` into setup, optional boosts, gameplay, and result
    cleanup helpers.
  - Verification: full test set.

- [x] Cover gameplay-start preflight ordering.
  - Files: `scripts/test_auto_runner.py`
  - Goal: ensure levels-mode episode validation still happens before spending a
    run with the final Play tap.
  - Verification: `test_auto_runner.py`.

## Phase 3: strengthen fixture coverage before deeper refactors

- [ ] Add captcha fixture tests.
  - Files likely affected: `scripts/test_captcha.py`, `avd_runner/captcha.py`,
    captured fixtures under a small test data directory if needed.
  - Goal: lock modal detection, motion scoring, and selected-card behavior.
  - Risk: low for tests, medium if fixtures are large or brittle.
  - Verify: `test_captcha.py`.

- [ ] Add gameplay runner unit seams with fake capture/device.
  - Files likely affected: `scripts/test_levels.py`, `scripts/test_reactive.py`,
    `scripts/test_none.py`, `avd_runner/levels.py`, `avd_runner/reactive.py`,
    `avd_runner/none.py`.
  - Goal: test timing decisions and relay/result checks without real emulator
    state.
  - Status: `none` mode has fake capture/device coverage; levels/reactive loop
    seams still need coverage.
  - Risk: medium; fake time/capture can accidentally encode the current
    implementation too tightly.
  - Verify: none/levels/reactive tests plus manual run when available.

- [ ] Add capture-facing smoke docs/checklist.
  - Files likely affected: `README.md` or this document.
  - Goal: document manual WGC verification steps for Windows-only capture.
  - Risk: low.
  - Verify: manual checklist only.

## Phase 4: refactor behavior-sensitive internals

- [ ] Refactor captcha internals only after fixture coverage.
  - Proposed changes: isolate modal detection, grid/cell measurement, motion
    scoring, and tap selection into smaller pure helpers.
  - Risk: high without fixtures; medium with fixtures.
  - Verify: captcha fixtures plus live captcha run.

- [ ] Refactor level replay internals only after timing tests.
  - Proposed changes: isolate level state machine, tap scheduling, progress
    reading, and exit detection.
  - Risk: high due to timing and progress-bar sensitivity.
  - Verify: unit tests, recorded traces, manual level run.

- [ ] Refactor reactive runner internals only after fake-capture tests.
  - Proposed changes: isolate relay/result polling, obstacle detection, action
    cooldown, and debug update construction.
  - Risk: high due to latency and obstacle timing.
  - Verify: reactive tests with fixtures and manual run.

- [ ] Consider capture abstraction cleanup.
  - Proposed changes: keep `WindowCapture` as the sole capture implementation,
    but clarify lifecycle and close semantics.
  - Risk: medium/high because WGC behavior is platform-specific.
  - Verify: Windows manual capture check and compile/tests.

## Do not refactor yet

- `avd_runner/captcha.py` heuristics: too behavior-sensitive without stronger
  fixtures.
- `avd_runner/levels.py` scheduling/state machine: timing-sensitive and tied to
  recorded traces.
- `avd_runner/reactive.py` action loop: latency-sensitive.
- `avd_runner/capture.py`: WGC platform code should be changed only with manual
  Windows verification available.

## Clarifications still needed

- Whether ADB input remains the long-term input path or should be replaced by a
  Windows/emulator-native input backend later.
- Whether captured-frame fixtures should be committed to the repo or kept as
  local artifacts.
- Whether trace v4 recordings should be migrated, deleted, or left as local
  compatibility warnings.

## Recommended next PR-sized change

Add fixture-backed tests for captcha and gameplay decision points before
refactoring `captcha.py`, `levels.py`, or `reactive.py`.
