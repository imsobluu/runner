import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avd_runner import AvdDevice


def main() -> None:
    device = AvdDevice.from_env()
    process = device.start_scrcpy("--window-title", "AVD Runner", no_control=True)
    print(f"Started scrcpy with PID {process.pid}")
    process.wait()


if __name__ == "__main__":
    main()
