import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avd_runner import AvdDevice, wait


def main() -> None:
    device = AvdDevice.from_env()
    width, height = device.screen_size()

    device.tap(width // 2, height // 2)
    wait(0.25)
    device.save_screenshot("screenshots/after_tap.png")

    print(f"Tapped center at {width // 2}, {height // 2}")
    print("Saved screenshots/after_tap.png")


if __name__ == "__main__":
    main()
