"""Probe progress-marker detection without recording inputs.

Writes per-frame telemetry so false progress jumps can be inspected after a
manual run:

    .venv\\Scripts\\python.exe -u scripts\\probe_progress.py --seconds 120
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import cv2

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from avd_runner.capture import WindowCapture
from avd_runner.device import DEFAULT_DEVICE_SIZE
from avd_runner.levels import ProgressTracker, load_marker, locate_marker_with_details


def draw_detection(frame, detection, label: str):
    if detection is None:
        return frame
    x1, y1, x2, y2 = detection.box
    annotated = frame.copy()
    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
    cv2.putText(
        annotated,
        label,
        (x1, max(20, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 255, 0),
        2,
    )
    return annotated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Log progress-marker detection telemetry.")
    parser.add_argument("--seconds", type=float, default=120.0, help="How long to probe.")
    parser.add_argument("--fps", type=float, default=30.0, help="Sampling rate.")
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "captures" / "progress_probe",
        help="Output directory for telemetry and snapshots.",
    )
    parser.add_argument(
        "--snapshot-jump",
        type=float,
        default=0.25,
        help="Save a frame when progress jumps by at least this amount.",
    )
    parser.add_argument(
        "--snapshot-drops",
        action="store_true",
        help="Save frames where detection drops out after being visible.",
    )
    parser.add_argument(
        "--snapshot-rejections",
        action="store_true",
        help="Save frames where the tracker rejects raw detection.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / f"progress_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    frame_dir = args.out / "frames"
    frame_dir.mkdir(exist_ok=True)

    marker = load_marker(REPO_ROOT / "assets")
    capture = WindowCapture(device_size=DEFAULT_DEVICE_SIZE)
    interval = 1.0 / max(1.0, args.fps)
    started = time.perf_counter()
    last_progress: float | None = None
    last_tracked_progress: float | None = None
    last_seen = False
    frame_index = 0
    tracker = ProgressTracker()

    print(f"Writing telemetry -> {csv_path}")
    print("Play manually. This script only captures WGC frames; it sends no inputs.")

    try:
        with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow([
                "frame",
                "t",
                "detected",
                "progress",
                "score",
                "method",
                "x1",
                "y1",
                "x2",
                "y2",
                "delta",
                "tracked_progress",
                "tracked_delta",
                "tracked_source",
                "tracked_reason",
                "tracked_rate",
                "event",
            ])

            while True:
                now = time.perf_counter()
                elapsed = now - started
                if elapsed >= args.seconds:
                    break

                frame = capture.grab()
                detection = locate_marker_with_details(frame, marker)
                progress = detection.progress if detection is not None else None
                tracked = tracker.update(elapsed, progress)
                delta = (
                    progress - last_progress
                    if progress is not None and last_progress is not None
                    else None
                )
                tracked_delta = (
                    tracked.progress - last_tracked_progress
                    if tracked.progress is not None and last_tracked_progress is not None
                    else None
                )
                event = ""
                if delta is not None and abs(delta) >= args.snapshot_jump:
                    event = "jump"
                elif detection is None and last_seen:
                    event = "drop"
                elif detection is not None and not last_seen:
                    event = "appear"
                if tracked.reason.startswith("rejected"):
                    event = f"{event}+reject" if event else "reject"

                if detection is None:
                    writer.writerow([
                        frame_index,
                        round(elapsed, 4),
                        0,
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "" if delta is None else round(delta, 6),
                        "" if tracked.progress is None else round(tracked.progress, 6),
                        "" if tracked_delta is None else round(tracked_delta, 6),
                        tracked.source,
                        tracked.reason,
                        "" if tracked.rate is None else round(tracked.rate, 6),
                        event,
                    ])
                else:
                    x1, y1, x2, y2 = detection.box
                    writer.writerow([
                        frame_index,
                        round(elapsed, 4),
                        1,
                        round(progress, 6),
                        round(detection.score, 6),
                        detection.method,
                        x1,
                        y1,
                        x2,
                        y2,
                        "" if delta is None else round(delta, 6),
                        "" if tracked.progress is None else round(tracked.progress, 6),
                        "" if tracked_delta is None else round(tracked_delta, 6),
                        tracked.source,
                        tracked.reason,
                        "" if tracked.rate is None else round(tracked.rate, 6),
                        event,
                    ])

                should_snapshot = (
                    "jump" in event
                    or (event == "drop" and args.snapshot_drops)
                    or ("reject" in event and args.snapshot_rejections)
                )
                if should_snapshot:
                    label = (
                        "no detection"
                        if detection is None
                        else (
                            f"raw {progress:.3f} {detection.method} {detection.score:.3f} "
                            f"tracked {tracked.progress if tracked.progress is not None else 'None'} "
                            f"{tracked.reason}"
                        )
                    )
                    cv2.imwrite(
                        str(frame_dir / f"{frame_index:06d}_{event}.png"),
                        draw_detection(frame, detection, label),
                    )

                if progress is not None:
                    last_progress = progress
                if tracked.progress is not None:
                    last_tracked_progress = tracked.progress
                last_seen = detection is not None
                frame_index += 1
                time.sleep(interval)
    finally:
        capture.close()

    print(f"Done. Frames sampled: {frame_index}")


if __name__ == "__main__":
    main()
