# Selectable Random Boost Design

## Goal

Replace the Double Coins-specific setup with an optional random-boost selection. Omitting `--random-boost` skips the entire Random Boost setup. Passing a kebab-case value selects that boost directly; passing the flag without a value opens a numbered terminal selector.

## Command-Line Interface

The supported forms are:

```text
python scripts/auto_runner.py
python scripts/auto_runner.py --random-boost magnetic-aura
python scripts/auto_runner.py --random-boost
```

The first form skips Random Boost setup. The second is non-interactive. The third prints the 11 boosts in display order and prompts for a number from 1 through 11 before device automation starts.

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

Invalid explicit values and invalid or unavailable interactive input fail with an argparse error that lists the valid choices. The old `--skip-random-boost` flag is removed because skipping is now the default.

## Boost Model and Selection

`scripts/auto_runner.py` keeps one ordered mapping from each CLI value to its display label and checkbox center in the existing 1280x720 reference coordinate system. The device layer already scales logical coordinates for other input sizes, so no separate scaling abstraction is needed.

`ensure_double_coins_setup(ctx)` becomes `ensure_random_boost_setup(ctx, boost)`. It opens Random Boost and Multi as before, then captures the checkbox modal and determines the state of all 11 checkbox regions with the existing `checkbox.png` and `checkmark.png` templates.

Multiple boosts may initially be checked. The helper toggles every checked boost other than the requested one off and toggles the requested boost on when necessary. It then captures the modal again and verifies that the complete checked set is exactly `{requested boost}`. Multi-Buy is not tapped unless this invariant holds.

After Multi-Buy, the helper waits for the selection modal to close and the boost store to reappear. Any missing screen, failed tap, ambiguous checkbox state, incorrect final checked set, or missing return to the boost store raises `RunnerError`.

## Run Flow

`run_once()` calls `ensure_random_boost_setup(ctx, args.random_boost)` only when `args.random_boost` is not `None`. Optional boosts, gameplay start, gameplay, and result cleanup remain unchanged. The existing start-button helper already accepts both the Double Coins-specific and ordinary Play screens.

## Tests

Extend `scripts/test_auto_runner.py` with focused checks for:

- no flag producing `None` and skipping Random Boost setup;
- every explicit kebab-case value being accepted and an invalid value being rejected;
- a valueless flag invoking the numbered selector;
- explicit values not invoking interactive input;
- `run_once()` forwarding the selected value to `ensure_random_boost_setup()`;
- checkbox reconciliation unchecking all undesired boosts, checking the desired boost, and accepting an already-correct modal without extra taps;
- verification rejecting ambiguous states or any final checked set other than the requested singleton;
- the setup sequence tapping Multi-Buy only after checkbox verification succeeds.

No new dependency, OCR path, per-boost image set, or generic policy abstraction is added.
