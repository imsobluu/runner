import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avd_runner import AvdDevice, wait
from avd_runner.capture import WindowCapture


def main() -> None:
    device = AvdDevice.from_env()
    width, height = device.screen_size()

    device.tap(width // 2, height // 2)
    wait(0.25)
    capture = WindowCapture(device_size=(width, height))
    try:
        frame = capture.grab()
    finally:
        capture.close()

    import cv2

    cv2.imwrite("screenshots/after_tap.png", frame)

    print(f"Tapped center at {width // 2}, {height // 2}")
    print("Saved screenshots/after_tap.png")


if __name__ == "__main__":
    main()
