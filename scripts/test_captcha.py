import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from avd_runner import captcha
from avd_runner.captcha import _cell_motion, _pick_outliers


class FakeCapture:
    def __init__(self, frames):
        self.frames = list(frames)
        self.index = 0

    def grab(self):
        frame = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        return frame


def synthetic_captcha_frame(cell_values, *, width=1280, height=720):
    """Build a full BGR frame with controlled grayscale values per captcha cell."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    for value, (x1, y1, x2, y2) in zip(cell_values, captcha._scaled_boxes(width, height)):
        frame[y1:y2, x1:x2] = value
    return frame

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

# Captcha geometry scales from the 1280x720 reference frame.
small_frame = np.zeros((360, 640, 3), dtype=np.uint8)
assert captcha._scale(small_frame) == (0.5, 0.5)
assert captcha._scaled_centers(small_frame)[0] == (218, 150)
assert captcha._scaled_boxes(640, 360)[0] == (179, 102, 257, 198)

# Synthetic full-frame fixtures exercise crop geometry + motion scoring
# together. Cells 0 and 3 stay still; the other four move between frames.
original_wait = captcha.wait
captcha.wait = lambda _seconds: None
try:
    fixture_frames = [
        synthetic_captcha_frame([50, 20, 40, 80, 100, 120]),
        synthetic_captcha_frame([50, 80, 110, 80, 35, 160]),
        synthetic_captcha_frame([50, 140, 20, 80, 170, 50]),
    ]
    solution = captcha._solve_round(FakeCapture(fixture_frames), frame_delay=0.0, frame_count=3)
    assert set(solution.outliers) == {0, 3}
    assert solution.motion[0] == 0.0
    assert solution.motion[3] == 0.0
    assert solution.confident
finally:
    captcha.wait = original_wait

print("ok")
