from __future__ import annotations

import time
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
    screen,
    banner_template: str | Path = BANNER_TEMPLATE,
    threshold: float = 0.9,
) -> bool:
    return find_template(screen, banner_template, threshold=threshold) is not None


def solve_captcha(
    device: AvdDevice,
    capture,
    max_rounds: int = 120,
    frame_delay: float = 0.2,
    frame_count: int = 4,
    banner_template: str | Path = BANNER_TEMPLATE,
    on_tap=None,
) -> bool:
    """Solve the anti-bot popup until it disappears.

    Each round the four running cookies animate a lot while the two outliers
    (jumping or sliding) stay nearly still, so the two cards with the least
    motion between frames are the answer. Returns True once the popup is gone.

    on_tap(name, screen, x, y), when given, is called for every card tap with
    a pre-tap frame.
    """
    for round_number in range(1, max_rounds + 1):
        if not is_captcha_present(capture.grab(), banner_template):
            print("Captcha dismissed.")
            return True

        solution = _solve_round(capture, frame_delay, frame_count)
        if not solution.confident:
            # Likely captured mid-transition. One re-capture is far cheaper
            # than a wrong answer, which resets round progress to 3/3.
            solution = _solve_round(capture, frame_delay, frame_count)
        centers = _scaled_centers(capture.grab())
        debug_screen = capture.grab() if on_tap else None
        for index in solution.outliers:
            x, y = centers[index]
            tx, ty = device.tap(x, y, label=f"captcha_card_{index + 1}")
            if on_tap:
                on_tap(f"captcha_card_{index + 1}", debug_screen, tx, ty)
            # A tapped card plays a disappear animation and the popup ignores
            # the next tap until it finishes; wait for the cell to change
            # instead of guessing a delay.
            if not _wait_card_gone(capture, index):
                print(f"Captcha card {index + 1} never disappeared; continuing anyway.")

        confidence = "confident" if solution.confident else "LOW CONFIDENCE"
        print(
            f"Captcha round {round_number}: tapped cards "
            f"{solution.outliers[0] + 1} and {solution.outliers[1] + 1} "
            f"({confidence})"
        )
        # Don't solve again until new cards are dealt into the emptied cells:
        # an empty cell is motionless and reads as an outlier.
        _wait_new_round(capture, solution.outliers, banner_template)

    still_present = is_captcha_present(capture.grab(), banner_template)
    if still_present:
        print(f"Captcha still present after {max_rounds} rounds; giving up.")
        return False
    return True


def _wait_card_gone(
    capture,
    cell_index: int,
    timeout: float = 3.0,
    threshold: float = 20.0,
) -> bool:
    """Wait until a tapped card's cell no longer looks like it did post-tap.

    The tapped outlier card is nearly still, so its cell only changes this
    much when the disappear animation replaces it with background.
    # ponytail: threshold 20 (mean abs gray diff) eyeballed with margin - the
    # still card differs by <3 frame to frame, a vanished card by >30.
    """
    import cv2
    import numpy as np

    baseline = None
    boxes = None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        screen = cv2.cvtColor(capture.grab(), cv2.COLOR_BGR2GRAY)
        if boxes is None:
            height, width = screen.shape[:2]
            boxes = _scaled_boxes(width, height)
        x1, y1, x2, y2 = boxes[cell_index]
        crop = screen[y1:y2, x1:x2].astype("int16")
        if baseline is None:
            baseline = crop
        elif float(np.abs(crop - baseline).mean()) > threshold:
            return True
        wait(0.05)
    return False


def _wait_new_round(
    capture,
    tapped_cells: tuple[int, int],
    banner_template: str | Path,
    timeout: float = 5.0,
    threshold: float = 20.0,
) -> None:
    """Wait until new cards are dealt into the cells the taps just emptied.

    Returns early when the popup disappears entirely (the final round has no
    new deal). On timeout the caller just solves against whatever is shown.
    """
    import cv2
    import numpy as np

    baselines: dict[int, np.ndarray] = {}
    boxes = None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        frame = capture.grab()
        if find_template(frame, banner_template, threshold=0.9) is None:
            return  # popup dismissed; the round loop confirms and exits
        screen = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if boxes is None:
            height, width = screen.shape[:2]
            boxes = _scaled_boxes(width, height)
        changed = 0
        for cell in tapped_cells:
            x1, y1, x2, y2 = boxes[cell]
            crop = screen[y1:y2, x1:x2].astype("int16")
            if cell not in baselines:
                baselines[cell] = crop
            elif float(np.abs(crop - baselines[cell]).mean()) > threshold:
                changed += 1
        if changed == len(tapped_cells):
            return
        wait(0.1)
    print("Captcha board did not re-deal within timeout; solving current state.")


def _solve_round(
    capture,
    frame_delay: float,
    frame_count: int,
) -> CaptchaSolution:
    frames = _capture_cell_frames(capture, frame_delay, frame_count)
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
    capture,
    frame_delay: float,
    frame_count: int,
) -> list[list[np.ndarray]]:
    import cv2

    boxes: list[tuple[int, int, int, int]] | None = None
    frames: list[list[np.ndarray]] = []
    for frame_index in range(frame_count):
        if frame_index:
            wait(frame_delay)
        screen = cv2.cvtColor(capture.grab(), cv2.COLOR_BGR2GRAY)
        if boxes is None:
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


def _scaled_centers(frame: np.ndarray) -> list[tuple[int, int]]:
    sx, sy = _scale(frame)
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


def _scale(frame: np.ndarray) -> tuple[float, float]:
    height, width = frame.shape[:2]
    return width / REFERENCE_WIDTH, height / REFERENCE_HEIGHT
