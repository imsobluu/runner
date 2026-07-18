# Skip Random Boost Design

## Goal

Add an opt-in `--skip-random-boost` command-line flag to the full auto-runner. When enabled, the run bypasses the entire required boost setup performed by `ensure_double_coins_setup()`.

## Design

`scripts/auto_runner.py` remains the only production file involved. Argument parsing adds a boolean `--skip-random-boost` flag. When the flag is true, `run_once()` does not call `ensure_double_coins_setup()`. The later gameplay-start step taps the existing plain `PLAY_TARGET` instead of `PLAY_WITH_DOUBLE_COINS_TARGET`. Optional boost handling, gameplay, and result cleanup otherwise remain unchanged.

The default is false, preserving current behavior. No generic boost-policy object or launcher integration is needed.

## Failure Behavior

Skipping required boost setup introduces no new error handling. If the plain Play button cannot be tapped, the run raises `RunnerError`, matching the existing Double Coins play-button failure behavior. Failures in the other unchanged later steps continue to raise `RunnerError` as they do today.

## Tests

Extend `scripts/test_auto_runner.py` with focused checks that:

- `parse_args(["--skip-random-boost"])` enables the flag and the default leaves it disabled.
- `run_once()` with skipping enabled does not call `ensure_double_coins_setup()`, uses the plain Play target rather than the Double Coins Play target, and still performs optional boost handling, gameplay, and result cleanup.
- the default path still performs Double Coins setup and uses the Double Coins Play target.

Update `README.md` to state that the new flag skips the entire Random Boost, Multi, Double Coins, and Multi Buy setup sequence and starts the run with the plain Play button.
