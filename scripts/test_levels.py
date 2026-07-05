import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import cv2

from avd_runner.levels import load_levels, load_marker, read_progress

# Progress reading against real frames (skipped if the burst isn't present).
captures = REPO_ROOT / "captures" / "probe1"
if captures.exists():
    marker = load_marker(REPO_ROOT / "assets")
    cutscene = read_progress(cv2.imread(str(captures / "frame_00016.jpg")), marker)
    assert cutscene is None, f"cutscene should have no progress bar, got {cutscene}"
    early = read_progress(cv2.imread(str(captures / "frame_00091.jpg")), marker)
    late = read_progress(cv2.imread(str(captures / "frame_00436.jpg")), marker)
    assert early is not None and late is not None
    assert 0 <= early < 0.1 < 0.7 < late < 0.85, f"early={early}, late={late}"

# The marker-speed fit used for freeze compensation.
from avd_runner.levels import fit_progress_slope

times = [10 + i * 0.05 for i in range(100)]
progresses = [(t - 8.0) / 40.0 for t in times]  # 40s level -> slope 0.025/s
slope = fit_progress_slope(times, progresses)
assert abs(slope - 0.025) < 1e-6, slope

# Freeze compensation: replay froze 1.2% further into the level than the
# recording did -> its schedule must shift earlier by dp/slope seconds.
offset = (0.045 - 0.033) / slope
assert abs(offset - 0.48) < 0.001, offset

# Recorded traces load and are well-formed (skipped if none recorded yet).
# One folder per episode: recordings/levels/<episode>/level_NN.json
levels_root = REPO_ROOT / "recordings" / "levels"
if levels_root.exists():
    for episode_dir in sorted(p for p in levels_root.iterdir() if p.is_dir()):
        try:
            levels = load_levels(episode_dir)
        except ValueError as exc:
            print(f"episode {episode_dir.name}: {exc}")
            continue
        assert levels, f"no traces loaded for episode {episode_dir.name}"
        for number, data in levels.items():
            assert data["p_freeze"] is None or -0.05 < data["p_freeze"] < 1
            assert data["slope"] is None or data["slope"] > 0
            times = [tap["t"] for tap in data["taps"]]
            assert times == sorted(times), f"{episode_dir.name} level {number} taps out of order"
            assert all(tap["duration"] >= 0 for tap in data["taps"])
        print(f"validated episode {episode_dir.name}: levels {sorted(levels)}")

print("ok")
