# AVD Game Automation Runner

A small Python scripting framework for automating an Android Virtual Device with
ADB. The core layer handles device I/O: screenshots, taps, swipes, text, and
key events. Your game scripts can then implement simple loops:

1. Capture the screen.
2. Inspect pixels or match an image.
3. Tap/swipe/type.
4. Wait and repeat.

## Quick Start

Install dependencies into a local environment:

```sh
uv venv .venv
uv pip install -r requirements.txt
```

Run scripts with the environment Python:

```sh
.venv\Scripts\python.exe examples\tap_center.py
```

If more than one Android device is connected, set the target:

```sh
$env:ANDROID_SERIAL = "emulator-5554"
.venv\Scripts\python.exe examples\tap_center.py
```

## Example Script

```python
from avd_runner import AvdDevice, wait

device = AvdDevice.from_env()
width, height = device.screen_size()

device.tap(width // 2, height // 2)
wait(0.5)
device.swipe(width // 2, int(height * 0.8), width // 2, int(height * 0.2), duration_ms=400)
```

## Auto Runner Bot

Start the bot by scanning for the Play button and tapping it:

```sh
$env:ANDROID_SERIAL = "emulator-5554"
$env:ADB_PATH = "E:\scrcpy-win64-v3.3.4\adb.exe"
.venv\Scripts\python.exe scripts\auto_runner.py
```

By default the bot replays the exported LDPlayer script at
`recordings\my_script(4).record` after starting the run. The `recordings/`
folder is not tracked in git, so export or record your own script first.
Use a different LDPlayer export with:

```sh
.venv\Scripts\python.exe scripts\auto_runner.py --mode ldplayer --recording recordings\my_other_script.record
```

Record a new JSON run instead with:

```sh
.venv\Scripts\python.exe scripts\auto_runner.py --mode record
```

Replay that JSON recording with:

```sh
.venv\Scripts\python.exe scripts\auto_runner.py --mode playback
```

Slow replay down when needed:

```sh
.venv\Scripts\python.exe scripts\auto_runner.py --speed 0.85
```

The Play button template is stored at `assets/play_button.png`.

## Tap Recording

Record taps from the device:

```sh
.venv\Scripts\python.exe scripts\record_taps.py recordings\run.json
```

Press `Ctrl+C` to stop recording. Replay the taps with:

```sh
.venv\Scripts\python.exe scripts\playback_taps.py recordings\run.json
```

Recordings include the delay before each tap and how long the tap was held.
Older recordings without hold durations still replay as normal taps.

## Scrcpy Screen Stream

For a real-time device view, install `scrcpy` and launch it through the runner:

```python
from avd_runner import AvdDevice

device = AvdDevice.from_env()
process = device.start_scrcpy("--window-title", "AVD Runner", no_control=True)
process.wait()
```

Run the included example:

```sh
.venv\Scripts\python.exe examples\launch_scrcpy.py
```

Use `SCRCPY_PATH` if `scrcpy` is not on `PATH`, and `ANDROID_SERIAL` when more
than one device is connected.

```sh
$env:SCRCPY_PATH = "E:\scrcpy-win64-v3.3.4\scrcpy.exe"
```

## Optional Image Matching

The framework works without third-party packages. Template matching uses the
packages from `requirements.txt`:

```sh
uv pip install -r requirements.txt
```

Then use `find_template`:

```python
from avd_runner import AvdDevice, find_template

device = AvdDevice.from_env()
screen = device.screenshot_bytes()
match = find_template(screen, "assets/play_button.png", threshold=0.9)

if match:
    device.tap(match.center_x, match.center_y)
```

## Notes

- Coordinates are physical screen pixels reported by the emulator.
- Prefer short waits after actions; games often need a few frames to settle.
- Keep game-specific behavior in `scripts/` or `examples/`; keep reusable ADB
  primitives in `avd_runner/`.
