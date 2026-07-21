# Coordinate Gameplay Play Tap Design

## Goal

Replace the Double Coins-specific template lookup used to start gameplay with a direct tap on the final Play button.

## Behavior

The final Play button uses the fixed 1280x720 reference coordinate `(920, 616)`, taken from `screenshots/current.png`. `AvdDevice.tap()` already scales reference coordinates to the active device input size.

Rename `tap_play_with_double_coins_button(ctx, attempts=5)` to `tap_gameplay_play_button(ctx)`. The new helper calls:

```python
ctx.device.tap(*GAMEPLAY_PLAY_XY, label="Play")
```

It returns `None`. Device input failures continue to propagate from `AvdDevice.tap()`; there is no template lookup, retry loop, or synthetic success value.

`run_after_start()` calls the helper after resolving level recordings and before constructing the gameplay runner, preserving the existing rule that invalid level configuration cannot spend a run.

## Cleanup

Remove `PLAY_WITH_DOUBLE_COINS_TEMPLATE` and `PLAY_WITH_DOUBLE_COINS_TARGET`, which become unused. Keep the asset file itself because deleting repository assets is outside this change.

## Tests

Update `scripts/test_auto_runner.py` to verify:

- `GAMEPLAY_PLAY_XY == (920, 616)`;
- the helper sends exactly one device tap at `(920, 616)` with label `"Play"`;
- `run_after_start()` invokes the renamed helper;
- invalid level recordings still fail before the coordinate tap.

Existing CLI, Random Boost selection, optional boosts, gameplay runners, and result cleanup remain unchanged.
