# Quit Gameplay After Collecting Mystery Boxes

## Goal

Add `--quit-on-collect-mystery-box N` to `scripts/auto_runner.py`. During gameplay, the runner reads the mystery-box count displayed beside `assets/mystery_box.png`. When the count equals `N`, it exits the active gameplay by tapping Pause at the logical coordinate `(1194, 37)`, then template-matching `assets/quit.png` twice before continuing through the existing result-screen cleanup and loop behavior.

## Command-Line Interface

- The option is disabled when omitted.
- `N` must be an integer greater than or equal to 1.
- Invalid values are rejected by `argparse` before device or capture setup begins.
- The option applies to all gameplay modes: `levels`, `reactive`, and `none`.

## Detection

A gameplay-only capture wrapper delegates to the existing capture object. At a throttled interval, it:

1. Finds `assets/mystery_box.png` in the frame.
2. Crops the small `xN` counter region immediately to the right of the matched icon.
3. Uses the already-installed RapidOCR dependency to read the numeric value.
4. Requires the same target value in two consecutive inspected frames before triggering.

OCR is initialized lazily, so runs without the option do not pay its startup cost. Missing icons, unreadable text, and nonnumeric OCR output are treated as no reading and gameplay continues.

## Control Flow

The capture wrapper raises a private target-reached signal after two confirmed readings equal `N`. This unwinds the active gameplay runner without changing the three runner implementations.

`run_after_start` catches that signal and performs these actions consecutively, with no explicit waits between them:

1. Tap Pause at logical coordinate `(1194, 37)`. The device layer scales this coordinate for the active input resolution.
2. `assets/quit.png`
3. `assets/quit.png`

Failure to find either Quit button follows the existing `RunnerError` failure path. After the coordinate tap and both template taps complete, `run_after_start` returns normally. `run_once` then invokes the existing `clear_results` flow, and configured loop behavior remains unchanged.

## Testing

Tests will verify:

- CLI parsing and rejection of values below 1.
- Reading `x1` from `screenshots/current.png`.
- One matching reading does not trigger.
- Two consecutive readings equal to the configured target trigger once.
- Missing or unreadable counters do not trigger.
- The post-trigger action order is the Pause coordinate, Quit template, and Quit template, with no wait calls before normal result cleanup resumes.

Existing gameplay-runner tests and the full script-based test suite will be run after implementation.
