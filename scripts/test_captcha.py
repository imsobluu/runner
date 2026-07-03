import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from avd_runner.captcha import _cell_motion, _pick_outliers

# Motion is the mean absolute pixel diff per cell, summed across frame pairs.
still = np.zeros((4, 4), dtype=np.uint8)
frames = [
    [still, still, still],
    [still, still + 10, still + 2],
]
assert _cell_motion(frames) == [0.0, 10.0, 2.0]

# The two quietest cells are the outliers; confident when the gap to the
# quietest runner is wide (second <= 0.6 * third).
s = _pick_outliers([0.5, 9.0, 8.0, 0.4, 10.0, 12.0])
assert set(s.outliers) == {0, 3}
assert s.confident

# No clear gap between outliers and runners -> mid-transition, not confident.
s = _pick_outliers([5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
assert set(s.outliers) == {0, 1}
assert not s.confident

# A frozen screen (all cells still) must never read as confident.
assert not _pick_outliers([0.0] * 6).confident

print("ok")
