# AVD Game Automation Runner

A Python framework for automating a Cookie Run bonus-stage farming loop on
LDPlayer on Windows. The menu/setup phase is driven closed-loop over Windows
Graphics Capture frames and template matching; the gameplay phase is driven
either by per-level tap replay re-synced on the in-game progress bar, or by a
fully reactive obstacle-detection loop.

## Requirements

- Windows (frame capture uses the Windows Graphics Capture API)
- LDPlayer with ADB available for input injection
- Python 3.12+ with the packages in `requirements.txt` plus `windows-capture`

```powershell
uv venv .venv
uv pip install -r requirements.txt
uv pip install windows-capture
```

Environment variables for input injection (optional):

```powershell
$env:ANDROID_SERIAL = "emulator-5554"   # target device if several are connected
$env:ADB_PATH = "C:\path\to\adb.exe"    # adb binary if not on PATH
```

## The full bot

```powershell
.venv\Scripts\python.exe -u scripts\auto_runner.py --mode levels
```

One run = menu setup (Play, boost purchases, captcha solving) -> gameplay ->
result screen -> mystery boxes. Add `--loop` to repeat forever or
`--loop-count N` for a fixed number of runs.

### Gameplay modes (`--mode`)

| Mode | Gameplay driver | Needs |
|------|-----------------|-------|
| `levels` (default) | Replays one tap trace per level, continuously synchronized to the live progress marker. Recommended. | `recordings/levels/<episode>/*.json` from `scripts/record_levels.py` |
| `reactive` | No recordings: detects obstacle sprites in a lookahead window and jumps/slides in response (~25 ms loop). | obstacle templates in `assets/witch_oven/` |
| `none` | Plays nothing during the run: watches the screen, taps the Activate Cookie Relay banner when it appears, and waits for the result screen. Useful to let a boosted run ride, or to play the run yourself while the bot handles menus, boosts, and results. | - |

Other flags: `--episode` (which episode's recordings to replay; defaults to
the only recorded episode), `--no-captcha` (disable the anti-bot captcha
solver), `--no-cookie-relay` (don't tap the Activate Cookie Relay banner
mid-run; `reactive` and `none` modes tap it by default),
`--skip-top-row-boosts` (don't buy the Double XP / Power Jelly / HP Extension
boosts during setup), `--debug` (save the frame of every menu and captcha-card
tap, with a red dot at the tap point and its coordinates, to
`debug/<session id>/runN/<NN>_<name>.png`; gameplay jump/slide taps are
deliberately not captured to keep their timing untouched), `--debug-window`
(a live OpenCV window showing detected template/obstacle boxes and taps as
they fire, across menu, levels, and reactive phases: menu button matches and
taps, the levels progress-marker box with replayed taps, and the
reactive lookahead region with the detected obstacle box and score).

### How `levels` mode stays in sync

The recorder associates every tap with the progress-marker position observed
at finger-down time. Playback does not pause: it watches the marker throughout
the level and fires each moving-phase tap when that same progress is reached.
This continuously corrects start-delay and speed differences instead of
applying one timing offset at the level boundary. Taps made while the marker
is stationary or unavailable use their recorded relative time as a fallback.
Trace format is v5; older recordings are rejected with a message to re-record.

## Recording per-level traces

The game is organized into episodes (e.g. Episode 1: Escape from the Oven),
each made of several levels. Recording is currently unavailable after removing
the old touch-event backend; `scripts/record_levels.py` is a placeholder until
a Windows-native input recorder is added.

Record one episode at a time once recording is re-enabled:

```powershell
.venv\Scripts\python.exe -u scripts\record_levels.py --episode ep01
```

Trace files live at `recordings/levels/<episode>/level_NN.json` as
`{t, progress, x, y, duration}` steps.

## Project structure

```
avd_runner/            Reusable library (device I/O, vision, capture, gameplay drivers)
  device.py            AvdDevice: ADB input injection only; screenshots use WGC
  vision.py            find_template(screenshot, template) -> TemplateMatch;
                       accepts PNG bytes or BGR numpy frames; caches templates
  capture.py           WindowCapture: ~4 ms frame grabs of the emulator window
                       via Windows Graphics Capture; works while occluded (not
                       minimized); crops the render area, returns device-space
                       BGR frames. Import directly, not via the package.
  levels.py            Per-level replay: progress-bar reading (read_progress),
                       level trace loading, LevelReplayer (pause/continue
                       handshake + scheduled tap playback per level)
  reactive.py          ReactiveRunner: capture -> detect obstacle template in
                       lookahead region -> jump/slide via ADB input;
                       obstacle templates are data (see assets/witch_oven)
  none.py              NoneRunner: plays nothing; taps the relay banner and
                       waits for the result screen (--mode none)
  captcha.py           Anti-bot captcha solver: detects the modal, measures
                       per-cell motion across frames, picks the outlier cards
  __init__.py          Re-exports the device/vision/captcha API (capture,
                       levels and reactive are imported explicitly)

scripts/               Game-specific entry points
  auto_runner.py       The full farming bot (see modes above). Also contains
                       the menu-phase helpers (tap_template, wait_for_template,
                       boost purchasing, mystery boxes)
  record_levels.py     Placeholder for a future Windows-native trace recorder
  record_frames.py     Save a burst of gameplay frames (JPEG) for offline
                       analysis: --seconds, --fps, --name -> captures/<name>/
  extract_sprites.py   Slice sprites out of the game APK's TexturePacker
                       atlases (assets/kakaoBC_HD/*.plist); frame names encode
                       jump/slide actions. Reference/catalog tooling.
  check_device.py      Sanity check: saves one WGC frame
  test_levels.py       Self-checks for progress reading + recorded trace shape
  test_reactive.py     Self-checks for obstacle template loading + detection
                       against captured frames
  test_captcha.py      Self-checks for the captcha cell-motion picker

assets/                Menu-phase button templates (play, boosts, result OK,
                       mystery boxes, captcha banner, ...) - PNG crops at
                       1280x720 device resolution
  level_banners/       Level-sync templates: progress_marker.png (the
                       gingerbread marker the progress bar is read with),
                       continue_button.png (pause-menu verification),
                       pause_button.png, level_01.png
  witch_oven/          Reactive-mode obstacle templates, named
                       <name>_jump.png / <name>_slide.png - the filename
                       suffix IS the action; drop in a new crop to teach the
                       bot a new obstacle (no code change)

examples/              Minimal library usage samples (tap_center, template
                       matching)

recordings/            (gitignored) per-level tap traces, one folder per
                       episode: levels/<episode>/level_NN.json
captures/              (gitignored) frame bursts and recording-session
                       screenshots (boundary/pause-menu shots)
screenshots/           (gitignored) ad-hoc debug screenshots
extracted_sprites/     (gitignored) APK sprite catalog from extract_sprites.py
```

## Tests

Plain-Python assert scripts, no framework:

```powershell
.venv\Scripts\python.exe scripts\test_levels.py
.venv\Scripts\python.exe scripts\test_reactive.py
.venv\Scripts\python.exe scripts\test_captcha.py
```

Checks that need captured frames or recorded traces skip themselves when
those local files are absent.

## Notes

- All coordinates are physical device pixels at 1280x720; templates were
  cropped at that resolution. A different emulator resolution needs recropped
  templates and recalibrated geometry in `avd_runner/levels.py` /
  `avd_runner/reactive.py`.
- `WindowCapture` needs the LDPlayer window visible (it may be covered by
  other windows, but not minimized).
- Run long sessions with `python -u` when redirecting output to a file,
  otherwise prints sit in Python's block buffer.
- Keep game-specific behavior in `scripts/`; keep reusable primitives in
  `avd_runner/`.
