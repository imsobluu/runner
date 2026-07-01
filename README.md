# AVD Game Automation Runner

A small Python scripting framework for automating an Android Virtual Device with
ADB. The core layer handles device I/O: screenshots, taps, swipes, text, and
key events. Your game scripts can then implement simple loops:

1. Capture the screen.
2. Inspect pixels or match an image.
3. Tap/swipe/type.
4. Wait and repeat.

## Quick Start

```sh
python3 examples/tap_center.py
```

If more than one Android device is connected, set the target:

```sh
ANDROID_SERIAL=emulator-5554 python3 examples/tap_center.py
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

## Optional Image Matching

The framework works without third-party packages. For template matching, install:

```sh
python3 -m pip install opencv-python numpy
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
