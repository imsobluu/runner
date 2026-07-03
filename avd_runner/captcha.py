from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .device import AvdDevice, wait
from .vision import find_template

if TYPE_CHECKING:
    import numpy as np

# The anti-bot popup is a fixed, centred modal. These coordinates are measured
# on the reference 1280x720 frame and scaled to the live device resolution.
REFERENCE_WIDTH = 1280
REFERENCE_HEIGHT = 720

# Centre of each of the six cards, in reading order (top row, then bottom row).
_CELL_CENTERS = (
    (437, 300),
    (633, 300),
    (829, 300),
    (437, 555),
    (633, 555),
    (829, 555),
)
# Half-width / half-height of the crop taken around each centre. Kept tight to
# the animated cookie so card borders and the mascot beside card 6 stay out.
_CROP_HALF_WIDTH = 78
_CROP_HALF_HEIGHT = 95

BANNER_TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "captcha_banner.png"


@dataclass(frozen=True)
class CaptchaSolution:
    outliers: tuple[int, int]
    motion: tuple[float, ...]
    confident: bool


def is_captcha_present(
    device: AvdDevice,
    banner_template: str | Path = BANNER_TEMPLATE,
    threshold: float = 0.9,
) -> bool:
    screen = device.screenshot_bytes()
    return find_template(screen, banner_template, threshold=threshold) is not None


def solve_captcha(
    device: AvdDevice,
    max_rounds: int = 120,
    frame_delay: float = 0.2,
    frame_count: int = 4,
    banner_template: str | Path = BANNER_TEMPLATE,
    settle_seconds: float = 1.2,
) -> bool:
    """Solve the anti-bot popup until it disappears.

    Each round the four running cookies animate a lot while the two outliers
    (jumping or sliding) stay nearly still, so the two cards with the least
    motion between frames are the answer. Returns True once the popup is gone.
    """
    for round_number in range(1, max_rounds + 1):
        if not is_captcha_present(device, banner_template):
            print("Captcha dismissed.")
            return True

        solution = _solve_round(device, frame_delay, frame_count)
        if not solution.confident:
            # Likely captured mid-transition. One re-capture is far cheaper
            # than a wrong answer, which resets round progress to 3/3.
            solution = _solve_round(device, frame_delay, frame_count)
        centers = _scaled_centers(device)
        for index in solution.outliers:
            x, y = centers[index]
            device.tap(x, y)
            wait(0.2)

        confidence = "confident" if solution.confident else "LOW CONFIDENCE"
        print(
            f"Captcha round {round_number}: tapped cards "
            f"{solution.outliers[0] + 1} and {solution.outliers[1] + 1} "
            f"({confidence})"
        )
        wait(settle_seconds)

    still_present = is_captcha_present(device, banner_template)
    if still_present:
        print(f"Captcha still present after {max_rounds} rounds; giving up.")
        return False
    return True


def _solve_round(
    device: AvdDevice,
    frame_delay: float,
    frame_count: int,
) -> CaptchaSolution:
    frames = _capture_cell_frames(device, frame_delay, frame_count)
    return _pick_outliers(_cell_motion(frames))


def _pick_outliers(motion: list[float]) -> CaptchaSolution:
    order = sorted(range(len(motion)), key=lambda i: motion[i])
    outliers = (order[0], order[1])

    # The two outliers should move far less than the quietest runner. If the
    # gap is small the popup may have been mid-transition when captured.
    second = motion[order[1]]
    third = motion[order[2]]
    confident = third > 0 and second <= 0.6 * third

    return CaptchaSolution(
        outliers=outliers,
        motion=tuple(motion),
        confident=confident,
    )


def _capture_cell_frames(
    device: AvdDevice,
    frame_delay: float,
    frame_count: int,
) -> list[list[np.ndarray]]:
    import cv2
    import numpy as np

    boxes: list[tuple[int, int, int, int]] | None = None
    frames: list[list[np.ndarray]] = []
    for frame_index in range(frame_count):
        if frame_index:
            wait(frame_delay)
        array = np.frombuffer(device.screenshot_bytes(), dtype=np.uint8)
        screen = cv2.imdecode(array, cv2.IMREAD_GRAYSCALE)
        if screen is None:
            raise ValueError("Could not decode screenshot PNG bytes")
        if boxes is None:
            # Crop in screenshot pixels: screencap may return the physical
            # resolution while `wm size` reports an override, so scale from
            # the image itself rather than from device.screen_size().
            height, width = screen.shape[:2]
            boxes = _scaled_boxes(width, height)
        frames.append([screen[y1:y2, x1:x2] for (x1, y1, x2, y2) in boxes])
    return frames


def _cell_motion(frames: list[list[np.ndarray]]) -> list[float]:
    import numpy as np

    cell_count = len(frames[0])
    motion = [0.0] * cell_count
    for previous, current in zip(frames, frames[1:]):
        for cell in range(cell_count):
            diff = np.abs(current[cell].astype("int16") - previous[cell].astype("int16"))
            motion[cell] += float(diff.mean())
    return motion


def _scaled_centers(device: AvdDevice) -> list[tuple[int, int]]:
    sx, sy = _scale(device)
    return [(round(x * sx), round(y * sy)) for (x, y) in _CELL_CENTERS]


def _scaled_boxes(width: int, height: int) -> list[tuple[int, int, int, int]]:
    sx = width / REFERENCE_WIDTH
    sy = height / REFERENCE_HEIGHT
    hw = round(_CROP_HALF_WIDTH * sx)
    hh = round(_CROP_HALF_HEIGHT * sy)
    boxes = []
    for x, y in _CELL_CENTERS:
        cx = round(x * sx)
        cy = round(y * sy)
        boxes.append((cx - hw, cy - hh, cx + hw, cy + hh))
    return boxes


def _scale(device: AvdDevice) -> tuple[float, float]:
    width, height = device.screen_size()
    return width / REFERENCE_WIDTH, height / REFERENCE_HEIGHT
