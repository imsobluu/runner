import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avd_runner import AvdDevice
from avd_runner.recording import record_taps


def main() -> None:
    parser = argparse.ArgumentParser(description="Record device taps to JSON.")
    parser.add_argument(
        "output",
        nargs="?",
        default="recordings/taps.json",
        help="Path to write the recording JSON.",
    )
    parser.add_argument("--duration", type=float, help="Stop after this many seconds.")
    parser.add_argument("--max-taps", type=int, help="Stop after this many taps.")
    parser.add_argument("--event-device", help="Specific /dev/input/eventX device to read.")
    args = parser.parse_args()

    record_taps(
        AvdDevice.from_env(),
        args.output,
        duration_seconds=args.duration,
        max_taps=args.max_taps,
        event_device=args.event_device,
    )


if __name__ == "__main__":
    main()
