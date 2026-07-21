# Selectable Random Boost Design

## Goal

Replace the Double Coins-specific setup with an optional random-boost selection. Omitting `--random-boost` skips the entire Random Boost setup. Passing a kebab-case value selects that boost directly; passing the flag without a value opens a single-selection terminal menu.

## Command-Line Interface

The supported forms are:

```text
python scripts/auto_runner.py
python scripts/auto_runner.py --random-boost magnetic-aura
python scripts/auto_runner.py --random-boost
```

The first form skips Random Boost setup. The second is non-interactive. The third opens a single-selection terminal menu before device automation starts.

### Interactive Menu

The menu renders all 11 boosts in display order with exactly one highlighted row. It starts on Double Coins. Up and Down move the highlight one row without moving past the first or last item. Number keys build a selection from `1` through `11` and move the highlight to that numbered item; this permits `10` and `11` without special key mappings. Backspace clears the numeric input. Enter confirms the highlighted boost, while Escape cancels with a clear argparse error.

The menu reads individual keys through the native Windows console API, so arrow keys work without requiring Enter and no third-party terminal dependency is added. Direct kebab-case values remain the non-interactive path for automation and redirected input.

The accepted values are:

1. `double-coins`
2. `score-bonus`
3. `hp-drain-reduction`
4. `revive`
5. `crush-chance`
6. `base-speed`
7. `gold-coin-magic`
8. `collision-damage-reduction`
9. `potion-hp`
10. `magnetic-aura`
11. `pit-lifts`

Invalid explicit values, Escape, and unavailable interactive console input fail with an argparse error that lists the valid choices. The old `--skip-random-boost` flag is removed because skipping is now the default.

## Boost Model and Selection

`scripts/auto_runner.py` keeps one ordered mapping from each CLI value to its display label and checkbox center in the existing 1280x720 reference coordinate system. The device layer already scales logical coordinates for other input sizes, so no separate scaling abstraction is needed.

`ensure_double_coins_setup(ctx)` becomes `ensure_random_boost_setup(ctx, boost)`. It opens Random Boost and Multi as before, then captures the checkbox modal and determines the state of all 11 checkbox regions with the existing `checkbox.png` and `checkmark.png` templates.

Multiple boosts may initially be checked. The helper toggles every checked boost other than the requested one off and toggles the requested boost on when necessary. It then captures the modal again and verifies that the complete checked set is exactly `{requested boost}`. Multi-Buy is not tapped unless this invariant holds.

Multi-Buy repeatedly rolls among the selected boosts until the requested boost is obtained. The existing boost-store templates do not describe that lifecycle, so they are not a valid completion signal.

After tapping Multi-Buy, the helper first waits for `stop.png` to appear, proving that rolling started. It then waits up to 120 seconds for `stop.png` to disappear, proving that rolling finished. Requiring the appearance transition prevents an initial frame without the Stop button from being mistaken for successful completion. Any missing screen, failed tap, ambiguous checkbox state, incorrect final checked set, failure to start rolling, or failure to finish rolling raises `RunnerError` with a stage-specific message.

## Run Flow

`run_once()` calls `ensure_random_boost_setup(ctx, args.random_boost)` only when `args.random_boost` is not `None`. Optional boosts, gameplay start, gameplay, and result cleanup remain unchanged. The existing start-button helper already accepts both the Double Coins-specific and ordinary Play screens.

## Tests

Extend `scripts/test_auto_runner.py` with focused checks for:

- no flag producing `None` and skipping Random Boost setup;
- every explicit kebab-case value being accepted and an invalid value being rejected;
- a valueless flag invoking the single-selection menu;
- Up/Down keys moving the highlight, number sequences selecting all entries including 10 and 11, Enter confirming, and Escape cancelling;
- explicit values not invoking interactive input;
- `run_once()` forwarding the selected value to `ensure_random_boost_setup()`;
- checkbox reconciliation unchecking all undesired boosts, checking the desired boost, and accepting an already-correct modal without extra taps;
- verification rejecting ambiguous states or any final checked set other than the requested singleton;
- the setup sequence tapping Multi-Buy only after checkbox verification succeeds;
- post-purchase confirmation waiting for Stop to appear before waiting for it to disappear;
- failure paths when Stop never appears or remains visible past the completion timeout.

No new dependency, OCR path, per-boost image set, or generic policy abstraction is added.
