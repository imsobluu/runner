# AVD Game Automation Runner

A Python framework for automating a Cookie Run bonus-stage farming loop on an
Android emulator (LDPlayer). The menu/setup phase is driven closed-loop over
ADB screenshots and template matching; the gameplay phase is driven either by
per-level tap replay re-synced on the in-game progress bar, or by a fully
reactive obstacle-detection loop.

## Requirements

- Windows (frame capture uses the Windows Graphics Capture API)
- LDPlayer (or another emulator visible to `adb`)
- Python 3.12+ with the packages in `requirements.txt` plus `windows-capture`

```powershell
uv venv .venv
uv pip install -r requirements.txt
uv pip install windows-capture
```

Environment variables (all optional):

```powershell
$env:ANDROID_SERIAL = "emulator-5554"   # target device if several are connected
$env:ADB_PATH = "C:\path\to\adb.exe"    # adb binary if not on PATH
$env:SCRCPY_PATH = "C:\path\to\scrcpy.exe"
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
| `levels` (default) | Replays one tap trace per level, re-synced at every level start via the progress bar and a pause/continue handshake. Recommended. | `recordings/levels/<episode>/*.json` from `scripts/record_levels.py` |
| `reactive` | No recordings: detects obstacle sprites in a lookahead window and jumps/slides in response (~25 ms loop). | obstacle templates in `assets/witch_oven/` |
| `none` | Plays nothing during the run: watches the screen, taps the Activate Cookie Relay banner when it appears, and waits for the result screen. Useful to let a boosted run ride, or to play the run yourself while the bot handles menus, boosts, and results. | - |

Other flags: `--episode` (which episode's recordings to replay; defaults to
the only recorded episode), `--no-captcha` (disable the anti-bot captcha
solver), `--no-cookie-relay` (don't tap the Activate Cookie Relay banner
mid-run; `reactive` and `none` modes tap it by default),
`--skip-top-row-boosts` (don't buy the Double XP / Power Jelly / HP
Extension boosts during setup).

### How `levels` mode stays in sync

Recording and playback perform the IDENTICAL sequence at every level start:
detect the level on the progress bar, tap pause, tap Continue, and take t=0
from the frame where the pause menu disappears. Because both sides interact
with the game the same way, every latency and any game side-effect of
pausing appears on both sides and cancels. (An earlier design that replayed
without pausing - treating the progress bar as a linear clock - desynced
badly; the symmetry is load-bearing, don't break it.)

The one remaining asymmetry is WHERE in the level the freeze lands:
detection can be late by a variable amount when a transition hides the
marker (0-7% observed). Both sides therefore read the marker's exact
position while frozen - it stays readable behind the pause menu - and the
replayer shifts its schedule by (p_replay - p_record) / marker speed, a
local correction that is zero when the freeze points match. Obstacle hits
only cost HP - timing is unaffected - so a trace recorded on a clean run
stays valid unless the cookie dies. Trace format is v4; older recordings
are rejected with a message to re-record.

## Recording per-level traces

The game is organized into episodes (e.g. Episode 1: Escape from the Oven),
each made of several levels. Record one episode at a time:

```powershell
.venv\Scripts\python.exe -u scripts\record_levels.py --episode ep01
```

(`--episode` is prompted interactively if omitted; the id is just the folder
name under `recordings/levels/`.) Start a run of that episode and play it
yourself. At each level start the tool pauses the game, beeps, and asks in
the console: `Enter` = record the level, `s` = play it unrecorded (use this
to skip ahead to a level you want to redo), `q` = quit. After answering, tap
the game's own Continue button - that tap is t=0. Traces are saved to
`recordings/levels/<episode>/level_NN.json` as `{t, x, y, duration}` steps
(slide holds keep their duration); re-recording a level overwrites its file.
Dying mid-level discards that level's partial trace; finished levels are
kept. Boundary and pause-menu screenshots land in
`captures/levels_<episode>_<timestamp>/`.

## Project structure

```
avd_runner/            Reusable library (device I/O, vision, capture, gameplay drivers)
  device.py            AvdDevice: adb wrapper - tap, swipe, keyevent, text,
                       screenshots, screen size, scrcpy launcher
  vision.py            find_template(screenshot, template) -> TemplateMatch;
                       accepts PNG bytes or BGR numpy frames; caches templates
  capture.py           WindowCapture: ~4 ms frame grabs of the emulator window
                       via Windows Graphics Capture; works while occluded (not
                       minimized); crops the render area, returns device-space
                       BGR frames. Import directly, not via the package.
  recording.py         getevent touch-stream utilities: find the touch input
                       device, parse raw tap events (used by record_levels.py)
  levels.py            Per-level replay: progress-bar reading (read_progress),
                       level trace loading, LevelReplayer (pause/continue
                       handshake + scheduled tap playback per level)
  reactive.py          ReactiveRunner: capture -> detect obstacle template in
                       lookahead region -> jump/slide via persistent shell;
                       obstacle templates are data (see assets/witch_oven)
  none.py              NoneRunner: plays nothing; taps the relay banner and
                       waits for the result screen (--mode none)
  captcha.py           Anti-bot captcha solver: detects the modal, measures
                       per-cell motion across frames, picks the outlier cards
  __init__.py          Re-exports the ADB/vision/captcha API (capture, levels,
                       reactive, and recording are imported explicitly)

scripts/               Game-specific entry points
  auto_runner.py       The full farming bot (see modes above). Also contains
                       the menu-phase helpers (tap_template, wait_for_template,
                       boost purchasing, mystery boxes)
  record_levels.py     Interactive per-level trace recorder (see above)
  record_frames.py     Save a burst of gameplay frames (JPEG) for offline
                       analysis: --seconds, --fps, --name -> captures/<name>/
  extract_sprites.py   Slice sprites out of the game APK's TexturePacker
                       atlases (assets/kakaoBC_HD/*.plist); frame names encode
                       jump/slide actions. Reference/catalog tooling.
  check_device.py      Sanity check: prints screen size, saves a screenshot
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
                       matching, scrcpy launch)

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
