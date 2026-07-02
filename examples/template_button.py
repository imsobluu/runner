import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from avd_runner import AvdDevice, find_template


def main() -> None:
    device = AvdDevice.from_env()
    screen = device.screenshot_bytes()
    match = find_template(screen, REPO_ROOT / "assets" / "button.png", threshold=0.9)

    if not match:
        print("Button not found")
        return

    device.tap(match.center_x, match.center_y)
    print(f"Tapped button at {match.center_x}, {match.center_y} score={match.score:.3f}")


if __name__ == "__main__":
    main()
