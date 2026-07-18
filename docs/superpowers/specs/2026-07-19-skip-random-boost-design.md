# Skip Random Boost Design

## Goal

Add an opt-in `--skip-random-boost` command-line flag to the full auto-runner. When enabled, the run bypasses the entire required boost setup performed by `ensure_double_coins_setup()`.

## Design

`scripts/auto_runner.py` remains the only production file involved. Argument parsing adds a boolean `--skip-random-boost` flag. When the flag is true, `run_once()` does not call `ensure_double_coins_setup()`. It continues with optional boost handling, gameplay, and result cleanup unchanged.

The default is false, preserving current behavior. No generic boost-policy object or launcher integration is needed.

## Failure Behavior

Skipping required boost setup introduces no new error handling. The bot proceeds from the current screen, and failures in the unchanged later steps continue to raise `RunnerError` as they do today.

## Tests

Extend `scripts/test_auto_runner.py` with focused checks that:

- `parse_args(["--skip-random-boost"])` enables the flag and the default leaves it disabled.
- `run_once()` with skipping enabled does not call `ensure_double_coins_setup()`, but still performs optional boost handling, gameplay, and result cleanup.

Update `README.md` to state that the new flag skips the entire Random Boost, Multi, Double Coins, and Multi Buy setup sequence.
