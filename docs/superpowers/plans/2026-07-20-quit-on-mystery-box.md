# Quit on Mystery Box Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional mystery-box counter that quits the active gameplay at an exact collected-box target and then resumes normal result handling.

**Architecture:** A focused `avd_runner.mystery_box` module wraps gameplay capture, detects the mystery-box icon, OCRs the adjacent counter, and raises a private signal after two confirmed target readings. `scripts/auto_runner.py` catches that signal, taps pause/quit/quit through its existing template-target machinery, and then continues its current result cleanup and loop flow.

**Tech Stack:** Python 3, argparse, OpenCV template matching, RapidOCR/ONNX Runtime, existing script-style assertion tests.

## Global Constraints

- The option name is exactly `--quit-on-collect-mystery-box` and accepts one integer `N >= 1`.
- The option is disabled when omitted and must not import or initialize RapidOCR in that case.
- Trigger only when the recognized counter equals `N` in two consecutive inspected frames.
- The gameplay exit order is exactly `assets/pause.png`, `assets/quit.png`, `assets/quit.png`.
- After quitting, continue through the existing result cleanup and configured loop behavior.
- Preserve the unrelated local edit in `scripts/launch_mumu_cookierun.py` and the user-provided image assets.

---

### Task 1: Mystery-box counter capture wrapper

**Files:**
- Create: `avd_runner/mystery_box.py`
- Create: `scripts/test_mystery_box.py`

**Interfaces:**
- Consumes: `avd_runner.vision.find_template(frame, template_path, threshold=0.85)` and a capture object exposing `grab()`.
- Produces: `MysteryBoxTargetReached`, `read_mystery_box_count(frame, template_path, ocr) -> int | None`, and `MysteryBoxCapture(capture, template_path, target, *, ocr=None, check_every=15)`.

- [ ] **Step 1: Write the failing counter-reading test**

Create `scripts/test_mystery_box.py` with a real screenshot and an injected OCR seam:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2

from avd_runner.mystery_box import read_mystery_box_count


REPO_ROOT = Path(__file__).resolve().parents[1]
frame = cv2.imread(str(REPO_ROOT / "screenshots" / "current.png"), cv2.IMREAD_COLOR)
assert frame is not None


class OCRResult:
    txts = ["x1"]


seen_crops = []


def fake_ocr(crop, **kwargs):
    seen_crops.append(crop)
    assert kwargs == {"use_det": False, "use_cls": False, "use_rec": True}
    return OCRResult()


assert read_mystery_box_count(
    frame,
    REPO_ROOT / "assets" / "mystery_box.png",
    fake_ocr,
) == 1
assert seen_crops and seen_crops[0].size
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.venv\Scripts\python.exe scripts/test_mystery_box.py`

Expected: FAIL with `ModuleNotFoundError: No module named 'avd_runner.mystery_box'`.

- [ ] **Step 3: Add failing confirmation and error-tolerance tests**

Append capture doubles and assertions:

```python
from avd_runner.mystery_box import MysteryBoxCapture, MysteryBoxTargetReached


class FakeCapture:
    def __init__(self):
        self.frames = 0

    def grab(self):
        self.frames += 1
        return f"frame-{self.frames}"


capture = FakeCapture()
wrapper = MysteryBoxCapture(
    capture,
    Path("mystery.png"),
    2,
    ocr=lambda _crop, **_kwargs: OCRResult(),
    check_every=1,
)
readings = iter([2, None, 2, 2])
wrapper._read_count = lambda _frame: next(readings)
assert wrapper.grab() == "frame-1"
assert wrapper.grab() == "frame-2"
assert wrapper.grab() == "frame-3"
try:
    wrapper.grab()
except MysteryBoxTargetReached as exc:
    assert exc.count == 2
else:
    raise AssertionError("two consecutive target readings should trigger")
```

- [ ] **Step 4: Implement the minimal detector and wrapper**

Create `avd_runner/mystery_box.py`:

```python
from __future__ import annotations

import re
from pathlib import Path

from .vision import find_template


class MysteryBoxTargetReached(RuntimeError):
    def __init__(self, count: int):
        super().__init__(f"Collected {count} mystery boxes.")
        self.count = count


def _ocr_text(result) -> str:
    texts = getattr(result, "txts", None) or []
    return " ".join(
        str(item[0] if isinstance(item, (list, tuple)) else item)
        for item in texts
    )


def read_mystery_box_count(frame, template_path: Path, ocr) -> int | None:
    match = find_template(frame, template_path, threshold=0.85)
    if match is None:
        return None
    frame_height, frame_width = frame.shape[:2]
    x1 = match.x + match.width
    x2 = min(frame_width, x1 + match.width)
    y1 = max(0, match.y)
    y2 = min(frame_height, match.y + match.height)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    result = ocr(crop, use_det=False, use_cls=False, use_rec=True)
    number = re.search(r"\d+", _ocr_text(result))
    return int(number.group()) if number else None


class MysteryBoxCapture:
    def __init__(
        self,
        capture,
        template_path: Path,
        target: int,
        *,
        ocr=None,
        check_every: int = 15,
    ):
        self._capture = capture
        self._template_path = template_path
        self._target = target
        self._ocr = ocr
        self._check_every = check_every
        self._frame_count = 0
        self._confirmations = 0

    def _get_ocr(self):
        if self._ocr is None:
            try:
                from rapidocr import RapidOCR
            except ImportError as exc:
                raise RuntimeError(
                    "Mystery-box counting requires OCR dependencies. "
                    "Install them with: .venv\\Scripts\\python.exe -m pip "
                    "install -r requirements-ocr.txt"
                ) from exc
            self._ocr = RapidOCR(params={"Global.log_level": "critical"})
        return self._ocr

    def _read_count(self, frame) -> int | None:
        return read_mystery_box_count(frame, self._template_path, self._get_ocr())

    def grab(self):
        frame = self._capture.grab()
        self._frame_count += 1
        if self._frame_count % self._check_every:
            return frame
        count = self._read_count(frame)
        self._confirmations = self._confirmations + 1 if count == self._target else 0
        if self._confirmations >= 2:
            raise MysteryBoxTargetReached(count)
        return frame
```

- [ ] **Step 5: Run the focused test and verify GREEN**

Run: `.venv\Scripts\python.exe scripts/test_mystery_box.py`

Expected: exit code 0.

- [ ] **Step 6: Commit the detector**

```powershell
git add avd_runner/mystery_box.py scripts/test_mystery_box.py
git commit -m "feat: detect mystery-box collection target"
```

---

### Task 2: CLI and gameplay quit sequence

**Files:**
- Modify: `scripts/auto_runner.py:22-114`
- Modify: `scripts/auto_runner.py:266-340`
- Modify: `scripts/auto_runner.py:343-415`
- Modify: `scripts/auto_runner.py:483-497`
- Modify: `scripts/test_auto_runner.py:1-330`

**Interfaces:**
- Consumes: `MysteryBoxCapture(capture, template_path, target)` and `MysteryBoxTargetReached` from Task 1.
- Produces: parsed `args.quit_on_collect_mystery_box: int | None`; `run_after_start(..., quit_on_collect_mystery_box: int | None) -> None`; `quit_gameplay(ctx) -> None`.

- [ ] **Step 1: Write failing CLI tests**

Add beside the existing parse tests in `scripts/test_auto_runner.py`:

```python
mystery_args = auto_runner.parse_args(["--quit-on-collect-mystery-box", "3"])
assert mystery_args.quit_on_collect_mystery_box == 3
assert auto_runner.parse_args([]).quit_on_collect_mystery_box is None

try:
    with redirect_stderr(StringIO()):
        auto_runner.parse_args(["--quit-on-collect-mystery-box", "0"])
except SystemExit:
    pass
else:
    raise AssertionError("mystery-box target 0 should be rejected")
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.venv\Scripts\python.exe scripts/test_auto_runner.py`

Expected: FAIL because `--quit-on-collect-mystery-box` is unrecognized.

- [ ] **Step 3: Add failing quit-order and wrapper-flow tests**

Add target definitions to the existing target-policy assertions and test the exact tap sequence:

```python
assert auto_runner.PAUSE_TARGET.path == auto_runner.ASSETS / "pause.png"
assert auto_runner.QUIT_TARGET.path == auto_runner.ASSETS / "quit.png"

original_tap_target = auto_runner.tap_target
quit_sequence = []
try:
    auto_runner.tap_target = (
        lambda _ctx, target, **_kwargs: quit_sequence.append(target.name) or True
    )
    auto_runner.quit_gameplay(ctx)
    assert quit_sequence == ["Pause", "Quit", "Quit"]
finally:
    auto_runner.tap_target = original_tap_target
```

Add a target-trigger case around the existing five-argument gameplay-runner builder seam:

```python
class TargetRunner:
    def run(self):
        raise auto_runner.MysteryBoxTargetReached(2)


original_quit_gameplay = auto_runner.quit_gameplay
original_build_gameplay_runner = auto_runner.build_gameplay_runner
quit_calls = []
captures = []
try:
    auto_runner.tap_play_with_double_coins_button = lambda _ctx: True
    auto_runner.quit_gameplay = lambda _ctx: quit_calls.append("quit")
    auto_runner.build_gameplay_runner = (
        lambda runner_ctx, _mode, _relay, _fast_start, _episode: (
            captures.append(runner_ctx.capture) or TargetRunner()
        )
    )
    auto_runner.run_after_start(ctx, "none", False, False, None, 2)
    assert isinstance(captures[0], auto_runner.MysteryBoxCapture)
    assert quit_calls == ["quit"]
finally:
    auto_runner.quit_gameplay = original_quit_gameplay
    auto_runner.build_gameplay_runner = original_build_gameplay_runner
```

- [ ] **Step 4: Implement CLI validation, target definitions, and flow**

Import `replace` and the Task 1 interfaces:

```python
from dataclasses import dataclass, replace

from avd_runner.mystery_box import MysteryBoxCapture, MysteryBoxTargetReached
```

Add paths and targets beside the existing result targets:

```python
MYSTERY_BOX_TEMPLATE = ASSETS / "mystery_box.png"
PAUSE_TEMPLATE = ASSETS / "pause.png"
QUIT_TEMPLATE = ASSETS / "quit.png"

PAUSE_TARGET = TemplateTarget("Pause", PAUSE_TEMPLATE, attempts=120)
QUIT_TARGET = TemplateTarget("Quit", QUIT_TEMPLATE, attempts=120)
```

Add the CLI option before debug options and validate it with the parser:

```python
parser.add_argument(
    "--quit-on-collect-mystery-box",
    type=int,
    help="Pause and quit gameplay after collecting exactly this many mystery boxes.",
)

if (
    args.quit_on_collect_mystery_box is not None
    and args.quit_on_collect_mystery_box < 1
):
    parser.error("--quit-on-collect-mystery-box must be at least 1")
```

Add the sequence helper:

```python
def quit_gameplay(ctx: AutoRunnerContext) -> None:
    for target in (PAUSE_TARGET, QUIT_TARGET, QUIT_TARGET):
        if not tap_target(ctx, target):
            raise RunnerError(f"Could not tap {target.path.name} while quitting gameplay.")
```

Extend `run_after_start` with `quit_on_collect_mystery_box: int | None = None`, preserving existing direct callers, wrap only the gameplay runner context, and catch only the target signal:

```python
runner_ctx = ctx
if quit_on_collect_mystery_box is not None:
    runner_ctx = replace(
        ctx,
        capture=MysteryBoxCapture(
            ctx.capture,
            MYSTERY_BOX_TEMPLATE,
            quit_on_collect_mystery_box,
        ),
    )
runner = build_gameplay_runner(
    runner_ctx,
    mode,
    relay_template,
    fast_start_template,
    episode_dir,
)
try:
    completed = runner.run()
except MysteryBoxTargetReached as exc:
    print(str(exc))
    quit_gameplay(ctx)
    completed = True
if not completed:
    raise RunnerError()
```

Pass `args.quit_on_collect_mystery_box` from `run_once` as the sixth `run_after_start` argument. Update the `run_once` ordering test's replacement lambda to accept `_mystery_target`, include that value in its recorded tuple, and add `quit_on_collect_mystery_box=None` to its manually constructed `skip_args` namespace.

- [ ] **Step 5: Run the focused flow tests and verify GREEN**

Run: `.venv\Scripts\python.exe scripts/test_auto_runner.py`

Expected: output ends in `ok`, exit code 0.

- [ ] **Step 6: Run all gameplay runner regression tests**

Run:

```powershell
.venv\Scripts\python.exe scripts/test_none.py
.venv\Scripts\python.exe scripts/test_reactive.py
.venv\Scripts\python.exe scripts/test_levels.py
```

Expected: each command outputs `ok` and exits 0.

- [ ] **Step 7: Commit the CLI and flow**

```powershell
git add scripts/auto_runner.py scripts/test_auto_runner.py
git commit -m "feat: quit gameplay at mystery-box target"
```

---

### Task 3: Full verification

**Files:**
- Verify only; no production files are added in this task.

**Interfaces:**
- Consumes: the completed CLI, detector, capture wrapper, and quit flow.
- Produces: fresh evidence that all script tests pass and the diff contains only intended changes.

- [ ] **Step 1: Install the declared optional OCR dependencies if absent**

Run: `.venv\Scripts\python.exe -m pip install -r requirements-ocr.txt`

Expected: RapidOCR 3.9.1 and ONNX Runtime 1.27.0 are installed successfully. If package download needs network approval, request it rather than changing dependency versions.

- [ ] **Step 2: Exercise real OCR against the supplied screenshot**

Run:

```powershell
.venv\Scripts\python.exe -c "import cv2; from pathlib import Path; from rapidocr import RapidOCR; from avd_runner.mystery_box import read_mystery_box_count; frame=cv2.imread('screenshots/current.png'); value=read_mystery_box_count(frame, Path('assets/mystery_box.png'), RapidOCR(params={'Global.log_level':'critical'})); print(value); assert value == 1"
```

Expected: prints `1` and exits 0.

- [ ] **Step 3: Run every repository test script**

Run:

```powershell
Get-ChildItem scripts/test_*.py | ForEach-Object { & .venv\Scripts\python.exe $_.FullName; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }
```

Expected: every script exits 0; scripts with status output end in `ok`.

- [ ] **Step 4: Inspect the final diff**

Run:

```powershell
git diff --check
git status --short
git diff -- avd_runner/mystery_box.py scripts/auto_runner.py scripts/test_mystery_box.py scripts/test_auto_runner.py
```

Expected: no whitespace errors; the existing `scripts/launch_mumu_cookierun.py` edit and user assets remain preserved; feature changes match the approved design.
