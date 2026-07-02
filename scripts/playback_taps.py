import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avd_runner import AvdDevice
from avd_runner.recording import play_taps


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay recorded device taps.")
    parser.add_argument(
        "recording",
        nargs="?",
        default="recordings/taps.json",
        help="Path to a recording JSON file.",
    )
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier.")
    args = parser.parse_args()

    play_taps(AvdDevice.from_env(), args.recording, speed=args.speed)


if __name__ == "__main__":
    main()
