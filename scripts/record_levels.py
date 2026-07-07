"""Record gameplay taps per level.

This workflow needs a Windows-native input hook before it can be enabled again.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from avd_runner.levels import TRACE_VERSION

PROGRESS_SAMPLE_MAX_GAP = 0.25


def progress_at_time(
    samples: list[tuple[float, float]], tap_time: float
) -> float | None:
    """Interpolate marker progress at a tap, rejecting stale observations."""
    before = next((sample for sample in reversed(samples) if sample[0] <= tap_time), None)
    after = next((sample for sample in samples if sample[0] >= tap_time), None)
    if before is None or after is None:
        nearest = before or after
        if nearest is None or abs(nearest[0] - tap_time) > PROGRESS_SAMPLE_MAX_GAP:
            return None
        return nearest[1]
    if after[0] == before[0]:
        return before[1]
    if (
        tap_time - before[0] > PROGRESS_SAMPLE_MAX_GAP
        or after[0] - tap_time > PROGRESS_SAMPLE_MAX_GAP
    ):
        return None
    fraction = (tap_time - before[0]) / (after[0] - before[0])
    return before[1] + fraction * (after[1] - before[1])


def save_level(
    episode_dir: Path,
    level: int,
    t0: float,
    taps: list[dict],
    samples: list[tuple[float, float]],
    until: float,
) -> None:
    """Save taps keyed to interpolated progress at finger-down time."""
    level_samples = [(t, p) for t, p in samples if t0 <= t <= until]

    steps = []
    for tap in taps:
        if not (t0 < tap["t"] <= until):
            continue
        progress = progress_at_time(level_samples, tap["t"])
        steps.append({
            "t": round(tap["t"] - t0, 3),
            "progress": None if progress is None else round(progress, 5),
            "x": tap["x"],
            "y": tap["y"],
            "duration": round(tap["duration"], 3),
        })
    episode_dir.mkdir(parents=True, exist_ok=True)
    path = episode_dir / f"level_{level:02d}.json"
    path.write_text(
        json.dumps(
            {
                "version": TRACE_VERSION,
                "level": level,
                "taps": steps,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Saved level {level}: {len(steps)} taps -> {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Record gameplay taps per level.")
    parser.add_argument(
        "--episode",
        help="Episode id; becomes the folder under recordings/levels/.",
    )
    parser.add_argument("--level", type=int, default=1, help="Number of the first level that will start.")
    parser.parse_args()
    raise SystemExit(
        "Level recording is unavailable until a Windows-native input recorder is added. "
        "Add a Windows-native input recorder to re-enable this script."
    )


if __name__ == "__main__":
    main()
