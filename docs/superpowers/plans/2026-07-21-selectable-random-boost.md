# Selectable Random Boost Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional `--random-boost` CLI value or interactive single-selection menu, then make the runner leave exactly that one in-game boost checked before Multi-Buy.

**Architecture:** Keep the feature in `scripts/auto_runner.py`: one ordered boost mapping drives CLI choices, menu display, checkbox coordinates, and reconciliation. Separate pure menu/checkbox decisions from console and device I/O so the existing plain-Python assertion suite can cover them without a live emulator.

**Tech Stack:** Python 3.12, `argparse`, Windows `msvcrt`, NumPy/OpenCV through the existing vision helpers, existing plain-Python assertion tests.

## Global Constraints

- Omitting `--random-boost` skips the complete Random Boost setup.
- `--random-boost BOOST` accepts only the 11 approved kebab-case values.
- A valueless `--random-boost` opens a single-selection menu supporting Up, Down, number keys `1` through `11`, Backspace, Enter, and Escape.
- Exactly the requested in-game checkbox may remain checked before Multi-Buy.
- Use the existing user-owned `assets/checkbox.png` and `assets/checkmark.png`; do not regenerate them or add per-boost templates.
- Add no dependency, OCR path, generic policy layer, or unrelated refactor.
- Preserve all pre-existing working-tree edits. `scripts/auto_runner.py` already contains unrelated user changes, so stage only feature hunks if committing.
- Preserve the current user-edited `FAST_START_0_TARGET.threshold == 0.98` and align its stale test assertion from `0.99` to `0.98` when first editing `scripts/test_auto_runner.py`.

## File Structure

- Modify `scripts/auto_runner.py`: boost metadata, console selector, CLI parsing, checkbox detection/reconciliation, setup orchestration, and run-flow integration.
- Modify `scripts/test_auto_runner.py`: focused assertions for selector state, parsing, checkbox exclusivity, setup sequencing, and run-flow forwarding.
- Modify `README.md`: replace `--skip-random-boost` documentation with the three supported `--random-boost` forms and accepted values.
- Use existing `assets/checkbox.png` and `assets/checkmark.png`: selected/unselected checkbox recognition.

---

### Task 1: CLI Value and Single-Selection Menu

**Files:**
- Modify: `scripts/auto_runner.py:1-110,372-454`
- Test: `scripts/test_auto_runner.py:1-60,395-412`

**Interfaces:**
- Produces: `RANDOM_BOOSTS: dict[str, tuple[str, tuple[int, int]]]`
- Produces: `_read_menu_key() -> str`
- Produces: `select_random_boost(read_key=None, write=None) -> str | None`
- Produces: `parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace` with `random_boost: str | None`

- [ ] **Step 1: Add failing selector and parser assertions**

Add these assertions before the target-policy assertions near the top of `scripts/test_auto_runner.py`, and replace the stale Fast Start threshold assertion with `0.98`:

```python
def choose_boost(keys):
    pressed = iter(keys)
    output = []
    return auto_runner.select_random_boost(
        read_key=lambda: next(pressed),
        write=output.append,
    )


assert choose_boost(["down", "\r"]) == "score-bonus"
assert choose_boost(["down", "up", "\r"]) == "double-coins"
assert choose_boost(["1", "0", "\r"]) == "magnetic-aura"
assert choose_boost(["1", "1", "\r"]) == "pit-lifts"
assert choose_boost(["9", "backspace", "2", "\r"]) == "score-bonus"
assert choose_boost(["escape"]) is None

assert auto_runner.parse_args([]).random_boost is None
assert (
    auto_runner.parse_args(["--random-boost", "magnetic-aura"]).random_boost
    == "magnetic-aura"
)

original_select_random_boost = auto_runner.select_random_boost
try:
    auto_runner.select_random_boost = lambda: "pit-lifts"
    assert auto_runner.parse_args(["--random-boost"]).random_boost == "pit-lifts"
finally:
    auto_runner.select_random_boost = original_select_random_boost

try:
    with redirect_stderr(StringIO()):
        auto_runner.parse_args(["--random-boost", "unknown"])
except SystemExit:
    pass
else:
    raise AssertionError("unknown random boost should be rejected")
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_auto_runner.py
```

Expected: FAIL because `select_random_boost` and `Namespace.random_boost` do not exist.

- [ ] **Step 3: Add the ordered boost mapping and menu**

Add this data near the asset/target constants and the menu functions before `parse_args()`:

```python
RANDOM_BOOSTS = {
    "double-coins": ("Double Coins", (284, 175)),
    "score-bonus": ("15% score bonus", (665, 175)),
    "hp-drain-reduction": ("-15% HP drain", (284, 224)),
    "revive": ("Revive once with 80 HP", (665, 224)),
    "crush-chance": ("70% Crush Chance", (284, 274)),
    "base-speed": ("+17% base speed", (665, 274)),
    "gold-coin-magic": ("Gold Coin Magic", (284, 323)),
    "collision-damage-reduction": ("-30% collision damage", (665, 323)),
    "potion-hp": ("+20% HP from potions", (284, 373)),
    "magnetic-aura": ("Magnetic Aura", (665, 373)),
    "pit-lifts": ("2 Pit Lifts", (284, 423)),
}


def _read_menu_key() -> str:
    import msvcrt

    key = msvcrt.getwch()
    if key in ("\x00", "\xe0"):
        return {"H": "up", "P": "down"}.get(msvcrt.getwch(), "")
    return {
        "\r": "\r",
        "\x08": "backspace",
        "\x1b": "escape",
    }.get(key, key)


def select_random_boost(read_key=None, write=None) -> str | None:
    read_key = _read_menu_key if read_key is None else read_key
    write = sys.stdout.write if write is None else write
    boosts = list(RANDOM_BOOSTS.items())
    selected = 0
    digits = ""
    rendered = False

    while True:
        if rendered:
            write(f"\x1b[{len(boosts) + 2}F")
        write("Select one Random Boost (arrows/numbers, Enter confirms):\n")
        for number, (_slug, (label, _xy)) in enumerate(boosts, 1):
            marker = ">" if number - 1 == selected else " "
            write(f"{marker} {number:2}. {label}\n")
        write("Esc cancels\n")
        rendered = True

        key = read_key()
        if key == "up":
            selected = max(0, selected - 1)
            digits = ""
        elif key == "down":
            selected = min(len(boosts) - 1, selected + 1)
            digits = ""
        elif key == "backspace":
            digits = ""
        elif key == "escape":
            return None
        elif key == "\r":
            return boosts[selected][0]
        elif key.isdigit():
            candidate = digits + key
            number = int(candidate)
            if 1 <= number <= len(boosts):
                digits = candidate
                selected = number - 1
            elif key != "0":
                digits = key
                selected = int(key) - 1
```

Replace `--skip-random-boost` with the optional-value argument and post-parse resolution:

```python
parser.add_argument(
    "--random-boost",
    nargs="?",
    const="",
    metavar="BOOST",
    help="Select a Random Boost by kebab-case name; omit BOOST for an interactive menu.",
)

# Immediately after parser.parse_args(argv):
if args.random_boost == "":
    try:
        args.random_boost = select_random_boost()
    except (EOFError, OSError, ImportError):
        parser.error("Interactive Random Boost selection needs a Windows console")
    if args.random_boost is None:
        parser.error("Random Boost selection cancelled")
elif args.random_boost is not None and args.random_boost not in RANDOM_BOOSTS:
    parser.error(
        "--random-boost must be one of: " + ", ".join(RANDOM_BOOSTS)
    )
```

- [ ] **Step 4: Run the test and verify GREEN**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_auto_runner.py
```

Expected: selector/parser assertions PASS and the script completes successfully.

- [ ] **Step 5: Commit only Task 1 hunks**

```powershell
git add -p scripts/auto_runner.py scripts/test_auto_runner.py
git diff --cached --check
git commit -m "feat: add random boost selector"
```

When selecting hunks, exclude pre-existing `scripts/auto_runner.py` changes other than the replaced skip/random-boost flow and exclude all unrelated files.

---

### Task 2: Exclusive Checkbox Reconciliation

**Files:**
- Modify: `scripts/auto_runner.py:27-100,155-200,471-498`
- Test: `scripts/test_auto_runner.py`
- Use: `assets/checkbox.png`
- Use: `assets/checkmark.png`

**Interfaces:**
- Consumes: `RANDOM_BOOSTS`
- Produces: `_checkbox_is_checked(crop) -> bool`
- Produces: `checked_random_boosts(screen) -> set[str]`
- Produces: `random_boosts_to_toggle(checked: set[str], desired: str) -> list[str]`
- Produces: `reconcile_random_boost_checkboxes(ctx: AutoRunnerContext, desired: str) -> None`
- Produces: `ensure_random_boost_setup(ctx: AutoRunnerContext, desired: str) -> None`

- [ ] **Step 1: Add failing checkbox and reconciliation assertions**

Add `import cv2` and these assertions to `scripts/test_auto_runner.py`:

```python
checked_template = cv2.imread(str(auto_runner.CHECKMARK_TEMPLATE))
empty_template = cv2.imread(str(auto_runner.CHECKBOX_TEMPLATE))
assert checked_template is not None
assert empty_template is not None
checked_crop = np.zeros((48, 56, 3), dtype=np.uint8)
empty_crop = np.zeros((48, 56, 3), dtype=np.uint8)
checked_crop[3:44, 6:48] = checked_template
empty_crop[4:43, 6:49] = empty_template
assert auto_runner._checkbox_is_checked(checked_crop)
assert not auto_runner._checkbox_is_checked(empty_crop)

assert auto_runner.random_boosts_to_toggle(
    {"double-coins", "magnetic-aura"},
    "magnetic-aura",
) == ["double-coins"]
assert auto_runner.random_boosts_to_toggle(set(), "pit-lifts") == ["pit-lifts"]
assert auto_runner.random_boosts_to_toggle(
    {"magnetic-aura"},
    "magnetic-aura",
) == []

class TapDevice:
    def __init__(self):
        self.taps = []

    def tap(self, x, y, label=""):
        self.taps.append((x, y, label))
        return x, y


reconcile_ctx = auto_runner.AutoRunnerContext(
    device=TapDevice(),
    capture=FakeCapture(frame),
    debug=DebugSession(),
    captcha_enabled=False,
)
states = iter([
    {"double-coins", "magnetic-aura"},
    {"magnetic-aura"},
])
original_checked_random_boosts = auto_runner.checked_random_boosts
try:
    auto_runner.checked_random_boosts = lambda _screen: next(states)
    auto_runner.reconcile_random_boost_checkboxes(reconcile_ctx, "magnetic-aura")
finally:
    auto_runner.checked_random_boosts = original_checked_random_boosts
assert reconcile_ctx.device.taps == [(284, 175, "Double Coins")]

bad_ctx = auto_runner.AutoRunnerContext(
    device=TapDevice(),
    capture=FakeCapture(frame),
    debug=DebugSession(),
    captcha_enabled=False,
)
bad_states = iter([
    {"double-coins"},
    {"double-coins"},
])
try:
    auto_runner.checked_random_boosts = lambda _screen: next(bad_states)
    try:
        auto_runner.reconcile_random_boost_checkboxes(bad_ctx, "magnetic-aura")
    except auto_runner.RunnerError:
        pass
    else:
        raise AssertionError("incorrect final checkbox set should fail")
finally:
    auto_runner.checked_random_boosts = original_checked_random_boosts

try:
    auto_runner._checkbox_is_checked(np.zeros((48, 56, 3), dtype=np.uint8))
except auto_runner.RunnerError:
    pass
else:
    raise AssertionError("ambiguous checkbox image should fail")
```

Add this setup-order assertion to prove Multi-Buy follows successful reconciliation and is skipped after reconciliation failure:

```python
setup_order = []
original_wait_for_any_template = auto_runner.wait_for_any_template
original_tap_random_boost_button = auto_runner.tap_random_boost_button
original_tap_multi_button = auto_runner.tap_multi_button
original_reconcile = auto_runner.reconcile_random_boost_checkboxes
original_tap_multi_buy_button = auto_runner.tap_multi_buy_button
try:
    screens = iter(["Random Boost", "Random Boost Selected"])
    auto_runner.wait_for_any_template = lambda *_args, **_kwargs: next(screens)
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
    ]

    setup_order.clear()
    screens = iter(["Random Boost"])
    auto_runner.reconcile_random_boost_checkboxes = (
        lambda _ctx, _boost: (_ for _ in ()).throw(auto_runner.RunnerError())
    )
    try:
        auto_runner.ensure_random_boost_setup(ctx, "magnetic-aura")
    except auto_runner.RunnerError:
        pass
    else:
        raise AssertionError("reconciliation failure should abort setup")
    assert "buy" not in setup_order
finally:
    auto_runner.wait_for_any_template = original_wait_for_any_template
    auto_runner.tap_random_boost_button = original_tap_random_boost_button
    auto_runner.tap_multi_button = original_tap_multi_button
    auto_runner.reconcile_random_boost_checkboxes = original_reconcile
    auto_runner.tap_multi_buy_button = original_tap_multi_buy_button
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_auto_runner.py
```

Expected: FAIL because the checkbox constants and reconciliation functions do not exist.

- [ ] **Step 3: Implement checkbox classification and exclusive reconciliation**

Add imports/constants:

```python
from avd_runner import AvdDevice, find_template, wait
from avd_runner.menu import debug_save_tap

CHECKBOX_TEMPLATE = ASSETS / "checkbox.png"
CHECKMARK_TEMPLATE = ASSETS / "checkmark.png"
REFERENCE_SIZE = (1280, 720)
CHECKBOX_HALF_SIZE = (28, 24)
CHECKBOX_READY_SCORE = 0.80
CHECKBOX_SCORE_MARGIN = 0.05
```

Add the classifier and deterministic toggle plan:

```python
def _checkbox_is_checked(crop) -> bool:
    checked = find_template(crop, CHECKMARK_TEMPLATE, threshold=-1.0)
    empty = find_template(crop, CHECKBOX_TEMPLATE, threshold=-1.0)
    checked_score = checked.score if checked else 0.0
    empty_score = empty.score if empty else 0.0
    if (
        max(checked_score, empty_score) < CHECKBOX_READY_SCORE
        or abs(checked_score - empty_score) < CHECKBOX_SCORE_MARGIN
    ):
        raise RunnerError(
            f"Ambiguous boost checkbox: checked={checked_score:.3f} "
            f"empty={empty_score:.3f}"
        )
    return checked_score > empty_score


def checked_random_boosts(screen) -> set[str]:
    height, width = screen.shape[:2]
    sx = width / REFERENCE_SIZE[0]
    sy = height / REFERENCE_SIZE[1]
    half_width, half_height = CHECKBOX_HALF_SIZE
    checked = set()
    for slug, (_label, (x, y)) in RANDOM_BOOSTS.items():
        x1 = round((x - half_width) * sx)
        y1 = round((y - half_height) * sy)
        x2 = round((x + half_width) * sx)
        y2 = round((y + half_height) * sy)
        if _checkbox_is_checked(screen[y1:y2, x1:x2]):
            checked.add(slug)
    return checked


def random_boosts_to_toggle(checked: set[str], desired: str) -> list[str]:
    return [
        slug
        for slug in RANDOM_BOOSTS
        if (slug == desired) != (slug in checked)
    ]


def reconcile_random_boost_checkboxes(ctx: AutoRunnerContext, desired: str) -> None:
    screen = ctx.capture.grab()
    for slug in random_boosts_to_toggle(checked_random_boosts(screen), desired):
        label, (x, y) = RANDOM_BOOSTS[slug]
        tx, ty = ctx.device.tap(x, y, label=label)
        debug_save_tap(ctx, label, screen, tx, ty)
        wait(0.2)
    final_checked = checked_random_boosts(ctx.capture.grab())
    if final_checked != {desired}:
        raise RunnerError(
            "Random Boost checkbox verification failed: "
            + ", ".join(sorted(final_checked))
        )
```

Replace `ensure_double_coins_setup()` with the generic setup:

```python
def ensure_random_boost_setup(ctx: AutoRunnerContext, desired: str) -> None:
    seen = wait_for_any_template(
        ctx,
        [
            ("Random Boost Selected", RANDOM_BOOST_SELECTED_TEMPLATE),
            ("Random Boost", RANDOM_BOOST_TEMPLATE),
        ],
        CAPTCHA_BANNER_TEMPLATE,
    )
    if seen is None:
        raise RunnerError("The boost-selection screen did not appear.")
    if not tap_random_boost_button(ctx):
        raise RunnerError("Could not select Random Boost.")
    if not tap_multi_button(ctx):
        raise RunnerError("Could not open Multi selection.")
    reconcile_random_boost_checkboxes(ctx, desired)
    if not tap_multi_buy_button(ctx):
        raise RunnerError("Could not tap Multi-Buy.")
    if wait_for_any_template(
        ctx,
        [
            ("Random Boost Selected", RANDOM_BOOST_SELECTED_TEMPLATE),
            ("Random Boost", RANDOM_BOOST_TEMPLATE),
        ],
        CAPTCHA_BANNER_TEMPLATE,
    ) is None:
        raise RunnerError("Boost store did not reappear after Multi-Buy.")
```

- [ ] **Step 4: Run the test and verify GREEN**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_auto_runner.py
```

Expected: checkbox classification, exclusive toggle planning, reconciliation, and failure-path assertions PASS.

- [ ] **Step 5: Commit only Task 2 hunks and the two approved assets**

```powershell
git add -p scripts/auto_runner.py scripts/test_auto_runner.py
git add -- assets/checkbox.png assets/checkmark.png
git diff --cached --check
git commit -m "feat: reconcile random boost checkboxes"
```

---

### Task 3: Run Flow, Documentation, and End-to-End Verification

**Files:**
- Modify: `scripts/auto_runner.py:529-548`
- Modify: `scripts/test_auto_runner.py:310-365,395-412`
- Modify: `README.md` under “The full bot” flags

**Interfaces:**
- Consumes: `args.random_boost: str | None`
- Consumes: `ensure_random_boost_setup(ctx, desired)`
- Produces: default skip flow and explicit-selection setup flow

- [ ] **Step 1: Add failing run-flow assertions**

Update the existing orchestration block so its setup stub accepts the selected boost:

```python
original_ensure_random_boost_setup = auto_runner.ensure_random_boost_setup
try:
    auto_runner.ensure_random_boost_setup = (
        lambda _ctx, boost: order.append(("random_boost", boost))
    )

    auto_runner.run_once(ctx, auto_runner.parse_args(["--mode", "none"]))
    assert order == [
        "relic",
        "play",
        "boosts",
        ("gameplay", False, None),
        "clear",
    ]

    order.clear()
    auto_runner.run_once(
        ctx,
        auto_runner.parse_args([
            "--mode",
            "none",
            "--random-boost",
            "magnetic-aura",
        ]),
    )
    assert order == [
        "relic",
        "play",
        ("random_boost", "magnetic-aura"),
        "boosts",
        ("gameplay", False, None),
        "clear",
    ]
finally:
    auto_runner.ensure_random_boost_setup = original_ensure_random_boost_setup
```

Remove assertions for `skip_random_boost`; the option no longer exists.

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_auto_runner.py
```

Expected: FAIL because `run_once()` still reads `args.skip_random_boost` and does not forward `args.random_boost`.

- [ ] **Step 3: Integrate the selected value into `run_once()`**

Replace the skip-flag branch with:

```python
if args.random_boost is None:
    wait(0.5)
else:
    ensure_random_boost_setup(ctx, args.random_boost)
```

- [ ] **Step 4: Update README CLI documentation**

Replace the `--skip-random-boost` paragraph with these examples and explanation:

````markdown
Random Boost setup is opt-in. With no `--random-boost` flag, the runner skips
Random Boost, Multi, checkbox selection, and Multi-Buy. Select directly for
unattended runs:

```powershell
.venv\Scripts\python.exe -u scripts\auto_runner.py --random-boost magnetic-aura
```

Pass `--random-boost` without a value for a single-selection terminal menu.
Use Up/Down or number keys 1-11, then press Enter. Accepted direct values are
`double-coins`, `score-bonus`, `hp-drain-reduction`, `revive`,
`crush-chance`, `base-speed`, `gold-coin-magic`,
`collision-damage-reduction`, `potion-hp`, `magnetic-aura`, and `pit-lifts`.
Before Multi-Buy, the runner unchecks every other boost and verifies that only
the requested boost remains checked.
````

- [ ] **Step 5: Run focused and repository verification**

Run:

```powershell
.venv\Scripts\python.exe scripts\test_auto_runner.py
.venv\Scripts\python.exe -m compileall -q scripts\auto_runner.py scripts\test_auto_runner.py
git diff --check
```

Expected: both Python commands exit 0; `git diff --check` emits no whitespace errors. If a live emulator is available, additionally run `--random-boost` once and confirm Up/Down, `10`, `11`, Enter, checkbox exclusivity, and return to the boost store visually.

- [ ] **Step 6: Review the feature diff without staging unrelated edits**

```powershell
git diff -- scripts/auto_runner.py scripts/test_auto_runner.py README.md assets/checkbox.png assets/checkmark.png
git status --short
```

Expected: feature changes match this plan; pre-existing edits in `assets/activate_fast_start.png` and `scripts/launch_mumu_cookierun.py` remain untouched.

- [ ] **Step 7: Commit only Task 3 hunks**

```powershell
git add -p scripts/auto_runner.py scripts/test_auto_runner.py README.md
git diff --cached --check
git commit -m "feat: select random boost per run"
```

Do not stage `assets/activate_fast_start.png`, `scripts/launch_mumu_cookierun.py`, or pre-existing unrelated hunks in `scripts/auto_runner.py`.
