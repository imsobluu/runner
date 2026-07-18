# Skip Random Boost Design

## Goal

Add an opt-in `--skip-random-boost` command-line flag to the full auto-runner. When enabled, the run bypasses the entire required boost setup performed by `ensure_double_coins_setup()`.

## Design

`scripts/auto_runner.py` remains the only production file involved. Argument parsing adds a boolean `--skip-random-boost` flag. When the flag is true, `run_once()` does not call `ensure_double_coins_setup()`.

The existing Double Coins-specific gameplay-start function becomes a general start-button function. It uses `wait_for_any_template()` to look for `PLAY_WITH_DOUBLE_COINS_TARGET` first and `PLAY_TARGET` second, then taps whichever target was detected. Double Coins stays first because the plain Play crop can also appear within the Double Coins screen. `run_after_start()` always uses this function, independent of the skip flag. Optional boost handling, gameplay, and result cleanup otherwise remain unchanged.

The default is false, preserving current behavior. No generic boost-policy object or launcher integration is needed.

## Failure Behavior

Skipping required boost setup introduces no new error handling. If neither play template appears or the detected target cannot be tapped, the run raises `RunnerError`, matching the existing play-button failure behavior. Failures in the other unchanged later steps continue to raise `RunnerError` as they do today.

## Tests

Extend `scripts/test_auto_runner.py` with focused checks that:

- `parse_args(["--skip-random-boost"])` enables the flag and the default leaves it disabled.
- `run_once()` with skipping enabled does not call `ensure_double_coins_setup()` and still performs optional boost handling, gameplay, and result cleanup.
- the gameplay-start function accepts and taps either play template, preferring the Double Coins target when both match.
- the default path still performs Double Coins setup.

Update `README.md` to state that the new flag skips the entire Random Boost, Multi, Double Coins, and Multi Buy setup sequence; gameplay start automatically accepts either play-button screen.
