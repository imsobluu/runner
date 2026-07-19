# Friend-Farm Continuous Trace Replay Design

## Goal

Replace friend-farm's progress-synchronized per-level replay with one
time-based trace. Trace time starts when
`assets/friend-farm/earn_xp.png` is first detected and the run succeeds when
`assets/result_ok_button.png` appears.

## Trace Compatibility

Reuse the existing v5 recording files under
`recordings/friend_farm/levels/level_01/`. The replay needs only each tap's
`t`, `x`, `y`, and `duration`; it ignores `progress`. Fixed coordinates are
valid because a trace may repeatedly tap the same spot.

The newest filename in `level_01` is the single trace used for a run. No new
recording format, migration, or recorder change is required.

## Runtime Flow

The launcher keeps its existing friend-farm menu flow and 960x540 menu
capture. Before tapping `play_3`, it validates and loads the newest v5 trace
and prepares the existing 1280x720 replay device and capture.

After `play_3` is tapped, the launcher polls the menu capture for
`earn_xp.png`. The first successful match establishes `t=0`. It then injects
each recorded gesture when its relative `t` is due, using the recorded
coordinates and duration. Result detection runs throughout playback. After
the last tap, the launcher continues watching without injecting input until
`result_ok_button.png` appears.

## Failure and Cleanup

Missing or invalid v5 recordings fail before `play_3`. Failure to detect
`earn_xp.png`, input errors, capture errors, or failure to detect the result
button before the existing replay timeout returns failure for that instance.
The replay capture and input shell are closed on every exit path. Dry-run
continues to open no capture and require no recording.

## Scope

Implement the time-based behavior only for the MuMu friend-farm launcher.
Do not change the general `LevelReplayer`, the v5 trace schema, the recorder,
or other gameplay modes. Reuse existing capture, template matching, device
input, and trace validation code wherever practical.

## Testing

Extend the focused launcher self-check to prove that:

- the newest v5 `level_01` trace is selected and validated before `play_3`;
- no trace tap fires before `earn_xp.png` is detected;
- detection establishes the replay clock and recorded taps fire in order with
  their recorded coordinates and durations;
- repeated identical coordinates remain unchanged;
- result detection ends the run, including after all taps have fired;
- missing or invalid traces and trigger/result timeouts return failure; and
- replay resources are closed on success and failure.

Run the focused launcher and level self-checks plus compilation and CLI-help
checks after implementation.
