from __future__ import annotations

import re
from pathlib import Path

from .vision import find_template


class MysteryBoxTargetReached(RuntimeError):
    def __init__(self, count: int):
        super().__init__(f"Collected {count} mystery boxes.")
        self.count = count


def _ocr_text(result) -> str:
    texts = getattr(result, "txts", None) or []
    return " ".join(
        str(item[0] if isinstance(item, (list, tuple)) else item)
        for item in texts
    )


def read_mystery_box_count(frame, template_path: Path, ocr) -> int | None:
    match = find_template(frame, template_path, threshold=0.85)
    if match is None:
        return None

    frame_height, frame_width = frame.shape[:2]
    x1 = match.x + match.width
    x2 = min(frame_width, x1 + match.width)
    y1 = max(0, match.y)
    y2 = min(frame_height, match.y + match.height)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None

    result = ocr(crop, use_det=False, use_cls=False, use_rec=True)
    number = re.search(r"\d+", _ocr_text(result))
    return int(number.group()) if number else None


class MysteryBoxCapture:
    def __init__(
        self,
        capture,
        template_path: Path,
        target: int,
        *,
        ocr=None,
        check_every: int = 15,
    ):
        self._capture = capture
        self._template_path = template_path
        self._target = target
        self._ocr = ocr
        self._check_every = check_every
        self._frame_count = 0
        self._confirmations = 0

    def _get_ocr(self):
        if self._ocr is None:
            try:
                from rapidocr import RapidOCR
            except ImportError as exc:
                raise RuntimeError(
                    "Mystery-box counting requires OCR dependencies. "
                    "Install them with: .venv\\Scripts\\python.exe -m pip "
                    "install -r requirements-ocr.txt"
                ) from exc
            self._ocr = RapidOCR(params={"Global.log_level": "critical"})
        return self._ocr

    def _read_count(self, frame) -> int | None:
        return read_mystery_box_count(frame, self._template_path, self._get_ocr())

    def grab(self):
        frame = self._capture.grab()
        self._frame_count += 1
        if self._frame_count % self._check_every:
            return frame

        count = self._read_count(frame)
        self._confirmations = self._confirmations + 1 if count == self._target else 0
        if self._confirmations >= 2:
            raise MysteryBoxTargetReached(count)
        return frame
