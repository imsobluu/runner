# Skip Random Boost Design

## Goal

Add an opt-in `--skip-random-boost` command-line flag to the full auto-runner. When enabled, the setup flow must not select Random Boost if it is currently unselected. If Random Boost is already selected, the bot leaves it selected.

## Design

`scripts/auto_runner.py` remains the only production file involved. Argument parsing adds a boolean `--skip-random-boost` flag. `run_once()` passes that value to `ensure_double_coins_setup()`, which omits the existing `tap_random_boost_button()` call when the flag is true and continues with Multi, Double Coins, Multi Buy, and the Double Coins banner wait unchanged.

The default is false, preserving current behavior. No generic boost-policy object or launcher integration is needed.

## Failure Behavior

Skipping Random Boost introduces no new failure path. Failures in the remaining required Double Coins setup steps continue to raise `RunnerError` as they do today.

## Tests

Extend `scripts/test_auto_runner.py` with focused checks that:

- `parse_args(["--skip-random-boost"])` enables the flag and the default leaves it disabled.
- setup with skipping enabled does not call the Random Boost tap, but still performs Multi, Double Coins, Multi Buy, and the final banner wait.

Update `README.md` to list the new flag and its already-selected behavior.
