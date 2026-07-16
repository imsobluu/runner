# MuMu Friend-Farm Level Replay Design

## Goal

Run the existing progress-synchronized level replayer after MuMu friend-farm
automation taps `play_3`.

## Scope

Change only the MuMu launcher and its focused self-check. Reuse
`avd_runner.levels.LevelReplayer` without modifying it, `auto_runner`, or any
existing episode recordings.

The launcher always reads one friend-farm recording set from:

```text
recordings/friend_farm/levels/level_NN/level_NN_nnn.json
```

There is no `--episode` option and no fallback to
`recordings/episodes/ing01`.

## Runtime Flow

Each MuMu instance continues through the existing image-driven friend-farm
steps. Immediately before `play_3`, the launcher constructs one
`LevelReplayer` with:

- the instance's existing `AvdDevice` and WGC capture;
- the repository `assets` directory;
- `recordings/friend_farm` as the level-recording root;
- `assets/result_ok_button.png` as the exit template;
- no Cookie Relay template; and
- the existing `LevelReplayer` 20-minute default timeout.

Constructing the replayer loads and validates the v5 recordings. Only after
construction succeeds does the launcher tap `play_3` and call
`LevelReplayer.run()`. Existing per-instance concurrency, WGC lifetime, and
aggregate exit-code behavior remain unchanged.

## Failure Behavior

A missing WGC capture, missing or empty friend-farm recording folder, invalid
trace, failed `play_3` tap, replay exception, or replay timeout makes that
instance return failure. The launcher reports the error without allowing an
exception from one worker to bypass capture cleanup.

Missing or invalid recordings fail before `play_3`, so the launcher never
starts a run it cannot replay.

Dry-run mode prints the planned friend-farm level replay and returns success
without requiring WGC or recordings on disk.

## Compatibility

Do not change `LevelReplayer`, its nested recording format, `auto_runner`,
`recordings/episodes/ing01`, the remaining general reactive runner, or its
tests and timing harness.

## Testing

Add one focused plain-Python launcher self-check using fake capture, device,
and replayer seams. It verifies:

- the replayer is prepared before `play_3`;
- replay starts only after a successful `play_3` tap;
- construction, tap, replay, and timeout failures propagate as `False`;
- exceptions are converted to instance failure; and
- dry-run does not read the recording folder.

Also run launcher compilation and help checks, `scripts/test_levels.py`, the
full non-interactive self-check suite, and the staged whitespace check.
