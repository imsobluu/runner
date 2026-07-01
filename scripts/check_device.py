import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avd_runner import AvdDevice


def main() -> None:
    device = AvdDevice.from_env()
    width, height = device.screen_size()
    path = device.save_screenshot("screenshots/check_device.png")

    print(f"Device screen: {width}x{height}")
    print(f"Screenshot saved: {path}")


if __name__ == "__main__":
    main()
