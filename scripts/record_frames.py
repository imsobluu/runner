"""Record a burst of gameplay frames for offline analysis.

Run it while a gameplay run is on screen:

    python scripts/record_frames.py --seconds 30 --fps 15

Frames land in captures/<name>/frame_00001.jpg (device coordinates).
"""
import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import cv2

from avd_runner import AvdDevice
from avd_runner.capture import WindowCapture


def main() -> None:
    parser = argparse.ArgumentParser(description="Record gameplay frames to disk.")
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--name", default=None, help="Capture directory name (default: timestamp).")
    args = parser.parse_args()

    out_dir = REPO_ROOT / "captures" / (args.name or time.strftime("%Y%m%d_%H%M%S"))
    out_dir.mkdir(parents=True, exist_ok=True)

    device_size = AvdDevice.from_env().screen_size()
    capture = WindowCapture(device_size=device_size)

    interval = 1.0 / args.fps
    frame_count = int(args.seconds * args.fps)
    start = time.perf_counter()
    for i in range(frame_count):
        frame = capture.grab()
        cv2.imwrite(str(out_dir / f"frame_{i + 1:05d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        # Sleep to the schedule, not a fixed interval, so writes don't drift the rate.
        next_tick = start + (i + 1) * interval
        remaining = next_tick - time.perf_counter()
        if remaining > 0:
            time.sleep(remaining)

    elapsed = time.perf_counter() - start
    capture.close()
    print(f"Saved {frame_count} frames ({elapsed:.1f}s, {frame_count / elapsed:.1f} fps) to {out_dir}")


if __name__ == "__main__":
    main()
