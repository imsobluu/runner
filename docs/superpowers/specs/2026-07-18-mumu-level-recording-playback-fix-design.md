# MuMu Level Recording and Playback Fix Design

## Goal

Make friend-farm level traces recorded from MuMu replay immediately after the
launcher taps `play_3`.

## Confirmed Root Causes

1. The launcher shares its 960x540 menu-automation capture with
   `LevelReplayer`, whose progress-marker constants and templates use the
   existing 1280x720 logical coordinate space. Marker detection therefore
   never starts Level 1.
2. `record_levels.py` clamps raw MuMu `getevent` axis values directly to
   1280x720. MuMu reports at least one touch axis in a different raw range, so
   the current trace saved every tap at the bottom edge (`y=719`).

The existing `recordings/friend_farm/levels/level_01/level_01_001.json` is
invalid and must be replaced after the code fix. The implementation will not
delete user recordings automatically.

## Approaches Considered

### 1. Separate replay capture and normalize raw touch axes (selected)

Keep the launcher's proven 960x540 capture for menu templates. Before
`play_3`, open a second capture for the same MuMu HWND at the level system's
1280x720 logical size, construct `LevelReplayer`, then tap and replay. Read the
touch device's reported ABS min/max values and scale raw X/Y coordinates into
the same 1280x720 logical space when recording.

This fixes both root causes without changing `LevelReplayer` or launcher menu
coordinates.

### 2. Change the entire launcher capture to 1280x720

Rejected because the launcher menu flow treats captured points as 960x540
coordinates before scaling them to the device. Changing that shared capture
would risk every pre-game tap.

### 3. Recalibrate `LevelReplayer` for 960x540

Rejected because it would duplicate or parameterize all established progress
marker geometry and would not repair the invalid MuMu recording coordinates.

## Launcher Design

`run_friend_farm_levels` continues receiving the existing menu capture and
configured MuMu input size. For a real run it will:

1. Resolve the MuMu top-level HWND from the serial.
2. Open a second `WindowCapture` for that HWND with logical size 1280x720.
3. Construct an `AvdDevice` with logical size 1280x720 and the MuMu configured
   resolution as `input_size`, so recorded gestures scale correctly to the
   instance.
4. Construct `LevelReplayer` with the second capture before tapping `play_3`.
5. Tap `play_3` through the original 960x540 menu capture.
6. Run the replayer and close the second capture on success, failure, or
   exception.

Dry-run behavior remains unchanged and opens no capture. Missing HWND,
capture failure, recording validation failure, tap failure, replay failure,
or an exception returns `False` for that instance.

## Recorder Design

The touch-event utility will read the selected device's `getevent -lp`
metadata and parse min/max ranges for `ABS_MT_POSITION_X` and
`ABS_MT_POSITION_Y`. `watch_taps` will scale each raw value independently:

```text
logical = round((raw - min) * (logical_size - 1) / (max - min))
```

The result is clamped to the logical screen bounds. If usable metadata is not
available for an axis, the recorder retains the existing direct-coordinate
behavior for compatibility with devices whose event values already use screen
pixels.

No recording format changes are required; traces remain version 5 and
`LevelReplayer` remains untouched.

## Testing

- Extend the launcher self-check to prove the replay capture is 1280x720,
  input scaling uses the MuMu configured size, construction occurs before
  `play_3`, and the replay capture is always closed.
- Extend the recording self-check with representative `getevent -lp` metadata
  and raw values, proving independent X/Y scaling and fallback behavior.
- Run the existing launcher, level, recording, reactive, capture, device,
  captcha, none-runner, and auto-runner checks plus compilation and CLI help.

## Operational Follow-up

After the fix, remove the invalid `level_01_001.json` manually and record a
new run. A valid trace should contain tap coordinates throughout the play area,
not every tap at `y=719`, and the launcher should print
`Level 1: progress-driven replay ...` immediately after level detection.
