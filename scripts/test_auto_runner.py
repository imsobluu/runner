import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from auto_runner import split_taps_at_anchors

taps = list(range(1, 11))  # stand-ins for RecordedTap

# No anchors: one segment, everything plays as before.
assert split_taps_at_anchors(taps, []) == [(taps, None)]

# after_tap is 1-based: anchor after tap 3 splits [1,2,3] | [4..10].
a = {"after_tap": 3, "template": "x.png"}
b = {"after_tap": 7, "template": "y.png"}
assert split_taps_at_anchors(taps, [b, a]) == [  # unsorted input is fine
    ([1, 2, 3], a),
    ([4, 5, 6, 7], b),
    ([8, 9, 10], None),
]

# Out-of-range or overlapping indices clamp instead of crashing.
assert split_taps_at_anchors(taps, [{"after_tap": 99, "template": "x.png"}])[0][0] == taps
assert split_taps_at_anchors([], [a]) == [([], a), ([], None)]

print("ok")
