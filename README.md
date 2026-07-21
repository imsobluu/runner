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

## Launch all MuMu instances into Cookie Run

```powershell
.venv\Scripts\python.exe scripts\launch_mumu_cookierun.py
```

The launcher reads MuMu's configured VM directories, starts each player through
`MuMuManager.exe`/`MuMuNxMain.exe`, verifies a live ADB transport and Android
package-manager readiness,
then opens Cookie Run (`com.devsisters.crg`) with Android `am start`. Instances
run in parallel. It waits for every Cookie Run render surface to remain in
landscape before arranging their windows across the desktop in a grid
using the Windows API before any `--friend-farm` automation begins. Pass
`--no-arrange` to preserve existing window
positions, or set an explicit layout such as `--grid 3x1`. MuMu ADB targets
are read from each VM's
`vm.nat.port_forward.adb.host_port` config and connected as
`127.0.0.1:<port>`, so the launcher does not collide with LDPlayer's
`emulator-*` serials. If MuMu is installed in a non-default location, pass
`--manager "C:\path\to\MuMuManager.exe"` or set `$env:MUMU_MANAGER_PATH`.
Use `--instances 0-3` to target a fixed range, or `--no-start-players` to only
open Cookie Run on currently connected ADB devices.

Pass `--friend-farm` to run the following image-driven sequence concurrently
on every launched instance:
`devplay_login.png → play.png → confirm.png → pause.png → quit.png → quit.png`,
then `enter nickname → confirm.png → close all x/confirm modals`. Each
instance receives a separately generated nickname. Finally, Chrome opens
`https://cookierunglobal.onelink.me/Xr0A/ohypcxa4`, then another modal-cleanup
step runs, followed by `episode.png → xp-elixir_workshop.png → enter.png`.
Modal cleanup uses the transparent `confirm_no_bg.png` and `x_no_bg.png`
glyphs with masked multi-scale matching. Its timeout is a no-progress timeout:
every successfully closed modal refreshes the budget.

Detection experiments:

```powershell
.venv\Scripts\python.exe scripts\test_modal_features.py screenshots\1.png
.venv\Scripts\python.exe scripts\test_modal_ocr.py screenshots\1.png --tesseract C:\path\to\tesseract.exe
```

The feature test compares ORB, SIFT, and AKAZE and writes annotated images plus
JSON metrics. The OCR test compares original, grayscale, Otsu, and adaptive
preprocessing through the Tesseract CLI.

Friend-farm vision uses one persistent Windows Graphics Capture session per
MuMu window. ADB is not used for screenshots; it remains responsible for
Android taps, text/key input, and app/browser intents.
Each instance's configured resolution is read from
`configs/shell_config.json`. WGC frames are matched in the templates'
960x540 reference space, then tap coordinates are scaled to that instance's
resolution.

Some MuMu installs expose the same commands through `MuMuNxMain.exe` instead:

```powershell
.venv\Scripts\python.exe scripts\launch_mumu_cookierun.py --manager "D:\Program Files\Netease\MuMuPlayer\nx_main\MuMuNxMain.exe"
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
| `levels` (default) | Replays one tap trace per level, continuously synchronized to the live progress marker. Recommended. | `recordings/episodes/<episode>/levels/level_NN/*.json` from `scripts/record_levels.py` |
| `reactive` | No recordings: detects obstacle sprites in a lookahead window and jumps/slides in response (~25 ms loop). | obstacle templates in `assets/witch_oven/` |
| `none` | Plays nothing during the run: watches the screen, taps the Activate Cookie Relay banner when it appears, and waits for the result screen. Useful to let a boosted run ride, or to play the run yourself while the bot handles menus, boosts, and results. | - |

Other flags: `--episode` (which episode's recordings to replay; defaults to
the only recorded episode), `--no-captcha` (disable the anti-bot captcha
solver), `--no-cookie-relay` (don't tap the Activate Cookie Relay banner
mid-run; `reactive` and `none` modes tap it by default),
`--fast-start` (tap Activate Fast Start once when it appears during gameplay;
recorded level replay continues),
`--skip-top-row-boosts` (don't buy the Double XP / Power Jelly / HP Extension
boosts during setup), `--debug` (save the frame of every menu and captcha-card
tap, with a red dot at the tap point and its coordinates, to
`debug/<session id>/runN/<NN>_<name>.png`; gameplay jump/slide taps are
deliberately not captured to keep their timing untouched), `--debug-window`
(a live OpenCV window showing detected template/obstacle boxes and taps as
they fire, across menu, levels, and reactive phases: menu button matches and
taps, the levels progress-marker box with replayed taps, and the
reactive lookahead region with the detected obstacle box and score).

Random Boost setup is opt-in. With no `--random-boost` flag, the runner skips
Random Boost, Multi, checkbox selection, and Multi-Buy. Select directly for
unattended runs:

```powershell
.venv\Scripts\python.exe -u scripts\auto_runner.py --random-boost magnetic-aura
```

Pass `--random-boost` without a value for a single-selection terminal menu.
Use Up/Down or number keys 1-11, then press Enter. Accepted direct values are
`double-coins`, `score-bonus`, `hp-drain-reduction`, `revive`,
`crush-chance`, `base-speed`, `gold-coin-magic`,
`collision-damage-reduction`, `potion-hp`, `magnetic-aura`, and `pit-lifts`.
Before Multi-Buy, the runner unchecks every other boost and verifies that only
the requested boost remains checked.

### How `levels` mode stays in sync

The recorder associates every tap with the progress-marker position observed
at finger-down time. Playback does not pause: it watches the marker throughout
the level and fires each moving-phase tap when that same progress is reached.
This continuously corrects start-delay and speed differences instead of
applying one timing offset at the level boundary. Taps made while the marker
is stationary or unavailable use their recorded relative time as a fallback.
Only the current nested v5 recording layout is supported; re-record older
traces.

## Recording per-level traces

The game is organized into episodes (e.g. Episode 1: Escape from the Oven),
each made of several levels. The recorder samples WGC frames for progress and
records Android touch events through ADB `getevent`, so traces use the device
coordinates and touch durations actually delivered to Android. Start it before
the first level begins, then play manually.

Record one episode at a time:

```powershell
.venv\Scripts\python.exe -u scripts\record_levels.py --episode ep01
```

Trace files live at
`recordings/episodes/<episode>/levels/level_NN/level_NN_nnn.json` as
`{t, progress, x, y, duration}` steps. Multiple recordings for the same level
can coexist; replay randomly picks one variant when that level starts.

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
  menu.py              Menu-phase screenshot/template/tap helpers shared by
                       the full bot and tests
  debug_session.py     Owns debug output state for saved tap frames and the
                       live debug window
  debugview.py         Live OpenCV overlay window used by --debug-window
  captcha.py           Anti-bot captcha solver: detects the modal, measures
                       per-cell motion across frames, picks the outlier cards
  __init__.py          Re-exports the device/vision/captcha API (capture,
                       levels and reactive are imported explicitly)

scripts/               Game-specific entry points
  auto_runner.py       The full farming bot (see modes above): orchestration,
                       menu policy, boost purchasing, mystery boxes
  launch_mumu_cookierun.py
                       Start MuMu Player instances and open Cookie Run on each
  record_levels.py     Manual trace recorder: WGC progress + ADB touch events
  record_frames.py     Save a burst of gameplay frames (JPEG) for offline
                       analysis: --seconds, --fps, --name -> captures/<name>/
  extract_sprites.py   Slice sprites out of the game APK's TexturePacker
                       atlases (assets/kakaoBC_HD/*.plist); frame names encode
                       jump/slide actions. Reference/catalog tooling.
  check_device.py      Sanity check: saves one WGC frame
  test_auto_runner.py  Self-checks for auto-runner orchestration policy
  test_capture.py      Self-checks for capture lifecycle behavior
  test_device.py       Self-checks for input-shell lifecycle behavior
  test_none.py         Self-checks for the no-gameplay runner loop
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

recordings/            (gitignored) per-level tap traces:
                       episodes/<episode>/levels/level_NN/level_NN_nnn.json
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
.venv\Scripts\python.exe scripts\test_auto_runner.py
.venv\Scripts\python.exe scripts\test_capture.py
.venv\Scripts\python.exe scripts\test_device.py
.venv\Scripts\python.exe scripts\test_none.py
```

Checks that need captured frames or recorded traces skip themselves when
those local files are absent.

## Manual capture smoke check

Run this after changing `avd_runner/capture.py`, WGC setup, emulator window
handling, or device-size assumptions:

```powershell
.venv\Scripts\python.exe scripts\check_device.py
```

Expected result:

- LDPlayer is open and not minimized.
- The command prints `Captured frame: 1280x720`.
- `screenshots/check_device.png` shows the emulator render surface only, not
  the full LDPlayer chrome.
- Move or cover the LDPlayer window and run the command again. Covered is OK;
  minimized is not.
- If using `--debug-window`, start a short `--mode none` run and confirm the
  live overlay updates and tap marks line up with emulator coordinates.

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
