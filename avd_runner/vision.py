from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

_template_cache: dict[str, Any] = {}


@dataclass(frozen=True)
class TemplateMatch:
    x: int
    y: int
    width: int
    height: int
    score: float

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2


def find_template(
    screenshot: bytes | Any,
    template_path: str | Path,
    threshold: float = 0.9,
) -> TemplateMatch | None:
    """Find template_path in a screenshot given as PNG bytes or a BGR array."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "Template matching requires opencv-python and numpy. "
            "Install them with: python3 -m pip install opencv-python numpy"
        ) from exc

    if isinstance(screenshot, bytes):
        screen_array = np.frombuffer(screenshot, dtype=np.uint8)
        screen = cv2.imdecode(screen_array, cv2.IMREAD_COLOR)
        if screen is None:
            raise ValueError("Could not decode screenshot PNG bytes")
    else:
        screen = screenshot

    key = str(template_path)
    template = _template_cache.get(key)
    if template is None:
        template = cv2.imread(key, cv2.IMREAD_COLOR)
        if template is None:
            raise ValueError(f"Could not read template image: {template_path}")
        _template_cache[key] = template

    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_value, _, max_location = cv2.minMaxLoc(result)
    if max_value < threshold:
        return None

    height, width = template.shape[:2]
    return TemplateMatch(
        x=int(max_location[0]),
        y=int(max_location[1]),
        width=int(width),
        height=int(height),
        score=float(max_value),
    )


def find_template_multiscale(
    screenshot: bytes | Any,
    template_path: str | Path,
    threshold: float = 0.9,
    *,
    min_scale: int = 50,
    max_scale: int = 150,
    step: int = 5,
) -> TemplateMatch | None:
    """Find a non-transparent template across multiple rendered scales."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "Template matching requires opencv-python and numpy. "
            "Install them with: python3 -m pip install opencv-python numpy"
        ) from exc

    if isinstance(screenshot, bytes):
        screen_array = np.frombuffer(screenshot, dtype=np.uint8)
        screen = cv2.imdecode(screen_array, cv2.IMREAD_COLOR)
        if screen is None:
            raise ValueError("Could not decode screenshot PNG bytes")
    else:
        screen = screenshot

    key = str(template_path)
    template = _template_cache.get(key)
    if template is None:
        template = cv2.imread(key, cv2.IMREAD_COLOR)
        if template is None:
            raise ValueError(f"Could not read template image: {template_path}")
        _template_cache[key] = template

    screen_height, screen_width = screen.shape[:2]
    template_height, template_width = template.shape[:2]
    best: TemplateMatch | None = None
    scale_percents = sorted(
        range(min_scale, max_scale + 1, step),
        key=lambda value: abs(value - 100),
    )

    for scale_percent in scale_percents:
        scale = scale_percent / 100
        width = round(template_width * scale)
        height = round(template_height * scale)
        if (
            width < 4
            or height < 4
            or width > screen_width
            or height > screen_height
        ):
            continue

        resized = cv2.resize(
            template,
            (width, height),
            interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
        )
        result = cv2.matchTemplate(screen, resized, cv2.TM_CCOEFF_NORMED)
        _, max_value, _, max_location = cv2.minMaxLoc(result)
        if best is None or max_value > best.score:
            best = TemplateMatch(
                x=int(max_location[0]),
                y=int(max_location[1]),
                width=int(width),
                height=int(height),
                score=float(max_value),
            )
        if max_value >= 0.98:
            break

    if best is None or best.score < threshold:
        return None
    return best
