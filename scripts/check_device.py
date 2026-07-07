import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2

from avd_runner.capture import WindowCapture


def main() -> None:
    capture = WindowCapture()
    try:
        frame = capture.grab()
    finally:
        capture.close()
    height, width = frame.shape[:2]
    path = Path("screenshots/check_device.png")
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), frame)

    print(f"Captured frame: {width}x{height}")
    print(f"Screenshot saved: {path}")


if __name__ == "__main__":
    main()
