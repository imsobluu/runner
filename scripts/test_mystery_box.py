import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2

from avd_runner.mystery_box import (
    MysteryBoxCapture,
    MysteryBoxTargetReached,
    read_mystery_box_count,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
frame = cv2.imread(str(REPO_ROOT / "screenshots" / "current.png"), cv2.IMREAD_COLOR)
assert frame is not None


class OCRResult:
    txts = ["x1"]


seen_crops = []


def fake_ocr(crop, **kwargs):
    seen_crops.append(crop)
    assert kwargs == {"use_det": False, "use_cls": False, "use_rec": True}
    return OCRResult()


assert read_mystery_box_count(
    frame,
    REPO_ROOT / "assets" / "mystery_box.png",
    fake_ocr,
) == 1
assert seen_crops and seen_crops[0].size


class FakeCapture:
    def __init__(self):
        self.frames = 0

    def grab(self):
        self.frames += 1
        return f"frame-{self.frames}"


capture = FakeCapture()
wrapper = MysteryBoxCapture(
    capture,
    Path("mystery.png"),
    2,
    ocr=fake_ocr,
    check_every=1,
)
readings = iter([2, None, 2, 2])
wrapper._read_count = lambda _frame: next(readings)
assert wrapper.grab() == "frame-1"
assert wrapper.grab() == "frame-2"
assert wrapper.grab() == "frame-3"
try:
    wrapper.grab()
except MysteryBoxTargetReached as exc:
    assert exc.count == 2
else:
    raise AssertionError("two consecutive target readings should trigger")

print("ok")
