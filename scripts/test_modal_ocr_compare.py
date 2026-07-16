"""Compare OCR engines on saved game UI screenshots.

The goal is not document OCR quality. This script measures whether an OCR
engine can find short modal/action words in CookieRun screenshots, and how long
it takes to do so on the same inputs.

Optional engines are skipped when their package/binary is not installed.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import cv2


DEFAULT_WORDS = (
    "confirm",
    "close",
    "ok",
    "yes",
    "continue",
    "enter",
)
PREPROCESS_VARIANTS = ("original", "gray2x", "otsu2x", "adaptive2x")


@dataclass
class OcrRow:
    text: str
    confidence: float | None
    box: list[int] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "box": self.box,
        }


@dataclass
class EngineResult:
    engine: str
    variant: str
    elapsed_seconds: float
    rows: list[OcrRow]
    error: str | None = None

    def to_dict(self, words: set[str], fuzzy_threshold: float) -> dict[str, Any]:
        rows = [row.to_dict() for row in self.rows]
        targets = []
        for row in rows:
            match = target_match(row["text"], words, fuzzy_threshold)
            if match is not None:
                target = dict(row)
                target["target_match"] = match
                targets.append(target)
        return {
            "engine": self.engine,
            "variant": self.variant,
            "elapsed_seconds": self.elapsed_seconds,
            "error": self.error,
            "targets": targets,
            "all_text": rows,
        }


def normalize_text(text: str) -> str:
    return text.casefold().strip(".,!?:;()[]{}'\"")


def target_match(text: str, words: set[str], fuzzy_threshold: float) -> dict[str, Any] | None:
    normalized = normalize_text(text)
    if normalized in words:
        return {"word": normalized, "mode": "exact", "score": 1.0}
    if len(normalized) < 4:
        return None
    scored = [
        (SequenceMatcher(None, normalized, word).ratio(), word)
        for word in words
        if len(word) >= 4
    ]
    if not scored:
        return None
    score, word = max(scored)
    if score >= fuzzy_threshold:
        return {"word": word, "mode": "fuzzy", "score": score}
    return None


def preprocess(image, variant: str):
    if variant == "original":
        return image
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    if variant == "gray2x":
        return gray
    if variant == "otsu2x":
        return cv2.threshold(
            gray,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU,
        )[1]
    if variant == "adaptive2x":
        return cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            7,
        )
    raise ValueError(f"Unknown preprocessing variant: {variant}")


def box_from_points(points: Any) -> list[int] | None:
    try:
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
    except (TypeError, ValueError, IndexError):
        return None
    left = round(min(xs))
    top = round(min(ys))
    right = round(max(xs))
    bottom = round(max(ys))
    return [left, top, right - left, bottom - top]


def scale_box(box: list[int] | None, scale: float) -> list[int] | None:
    if box is None or scale == 1.0:
        return box
    x, y, width, height = box
    return [
        round(x / scale),
        round(y / scale),
        round(width / scale),
        round(height / scale),
    ]


def rows_from_tesseract_tsv(tsv: str) -> list[OcrRow]:
    rows: list[OcrRow] = []
    for row in csv.DictReader(tsv.splitlines(), delimiter="\t"):
        text = row.get("text", "").strip()
        if not text:
            continue
        try:
            confidence = float(row["conf"])
            left = int(row["left"])
            top = int(row["top"])
            width = int(row["width"])
            height = int(row["height"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append(OcrRow(text=text, confidence=confidence, box=[left, top, width, height]))
    return rows


def run_tesseract(executable: str, image_path: Path, psm: int) -> list[OcrRow]:
    result = subprocess.run(
        [
            executable,
            str(image_path),
            "stdout",
            "--psm",
            str(psm),
            "tsv",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Tesseract failed")
    return rows_from_tesseract_tsv(result.stdout)


def make_rapidocr_runner() -> Callable[[Path, Any], list[OcrRow]]:
    from rapidocr import RapidOCR

    engine = RapidOCR()

    def run(image_path: Path, _image) -> list[OcrRow]:
        result = engine(str(image_path))
        return parse_rapidocr_result(result)

    return run


def parse_rapidocr_result(result: Any) -> list[OcrRow]:
    if hasattr(result, "txts") and hasattr(result, "boxes"):
        scores = getattr(result, "scores", [None] * len(result.txts))
        return [
            OcrRow(
                text=str(text),
                confidence=None if score is None else float(score) * 100,
                box=box_from_points(box),
            )
            for box, text, score in zip(result.boxes, result.txts, scores, strict=False)
        ]
    if isinstance(result, tuple) and result:
        return parse_rapidocr_result(result[0])
    if isinstance(result, list):
        return parse_ocr_triplets(result)
    if hasattr(result, "__iter__") and not isinstance(result, (str, bytes, dict)):
        return parse_ocr_triplets(list(result))
    raise RuntimeError(f"Unsupported RapidOCR result type: {type(result).__name__}")


def make_easyocr_runner(gpu: bool) -> Callable[[Path, Any], list[OcrRow]]:
    import easyocr

    reader = easyocr.Reader(["en"], gpu=gpu)

    def run(_image_path: Path, image) -> list[OcrRow]:
        result = reader.readtext(image)
        return parse_ocr_triplets(result)

    return run


def make_paddleocr_runner() -> Callable[[Path, Any], list[OcrRow]]:
    from paddleocr import PaddleOCR

    try:
        engine = PaddleOCR(lang="en", use_angle_cls=False, show_log=False)
    except TypeError:
        engine = PaddleOCR(lang="en")

    def run(image_path: Path, _image) -> list[OcrRow]:
        if hasattr(engine, "ocr"):
            try:
                result = engine.ocr(str(image_path), cls=False)
            except TypeError:
                result = engine.ocr(str(image_path))
            return parse_paddleocr_result(result)
        if hasattr(engine, "predict"):
            result = engine.predict(str(image_path))
            return parse_paddleocr_result(result)
        raise RuntimeError("PaddleOCR object has neither ocr() nor predict()")

    return run


def parse_paddleocr_result(result: Any) -> list[OcrRow]:
    rows: list[OcrRow] = []
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], list):
        result = result[0]
    if isinstance(result, list):
        rows.extend(parse_ocr_triplets(result))
        for item in result:
            if isinstance(item, dict):
                rows.extend(rows_from_mapping(item))
    elif isinstance(result, dict):
        rows.extend(rows_from_mapping(result))
    elif hasattr(result, "__iter__") and not isinstance(result, (str, bytes)):
        rows.extend(parse_ocr_triplets(list(result)))
    if not rows:
        raise RuntimeError(f"Unsupported PaddleOCR result type: {type(result).__name__}")
    return rows


def rows_from_mapping(item: dict[str, Any]) -> list[OcrRow]:
    texts = item.get("rec_texts") or item.get("texts")
    scores = item.get("rec_scores") or item.get("scores")
    boxes = item.get("rec_boxes") or item.get("dt_polys") or item.get("boxes")
    if not texts:
        return []
    if scores is None:
        scores = [None] * len(texts)
    if boxes is None:
        boxes = [None] * len(texts)
    return [
        OcrRow(
            text=str(text),
            confidence=None if score is None else float(score) * 100,
            box=box_from_points(box) if box is not None else None,
        )
        for text, score, box in zip(texts, scores, boxes, strict=False)
    ]


def parse_ocr_triplets(result: Iterable[Any]) -> list[OcrRow]:
    rows: list[OcrRow] = []
    for item in result:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        box = box_from_points(item[0])
        text_payload = item[1]
        confidence = None
        if isinstance(text_payload, (list, tuple)) and text_payload:
            text = str(text_payload[0])
            if len(text_payload) > 1:
                confidence = float(text_payload[1]) * 100
        else:
            text = str(text_payload)
            if len(item) > 2 and item[2] is not None:
                confidence = float(item[2]) * 100
        if text.strip():
            rows.append(OcrRow(text=text.strip(), confidence=confidence, box=box))
    return rows


def annotate(image, rows: list[OcrRow], words: set[str], fuzzy_threshold: float):
    output = image.copy()
    for row in rows:
        if row.box is None:
            continue
        is_target = target_match(row.text, words, fuzzy_threshold) is not None
        x, y, width, height = row.box
        color = (0, 0, 255) if is_target else (0, 180, 0)
        cv2.rectangle(output, (x, y), (x + width, y + height), color, 2)
        confidence = "" if row.confidence is None else f" {row.confidence:.0f}"
        cv2.putText(
            output,
            f"{row.text}{confidence}",
            (x, max(18, y - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2.LINE_AA,
        )
    return output


def engine_names(value: str) -> list[str]:
    if value.casefold() == "all":
        return ["tesseract", "rapidocr", "easyocr", "paddleocr"]
    return [engine.strip().casefold() for engine in value.split(",") if engine.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare OCR engines for CookieRun modal/button screenshots.",
    )
    parser.add_argument("screenshots", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, default=Path("debug/modal_ocr_compare"))
    parser.add_argument(
        "--engines",
        default="all",
        help="Comma-separated engines: tesseract,rapidocr,easyocr,paddleocr, or all.",
    )
    parser.add_argument(
        "--variants",
        default="original,gray2x",
        help=f"Comma-separated preprocessing variants from: {','.join(PREPROCESS_VARIANTS)}",
    )
    parser.add_argument(
        "--words",
        default=",".join(DEFAULT_WORDS),
        help="Comma-separated target words.",
    )
    parser.add_argument("--psm", type=int, default=11)
    parser.add_argument(
        "--fuzzy-threshold",
        type=float,
        default=0.78,
        help="Minimum SequenceMatcher ratio for fuzzy target-word matching.",
    )
    parser.add_argument(
        "--tesseract",
        default=shutil.which("tesseract"),
        help="Path to tesseract.exe.",
    )
    parser.add_argument(
        "--easyocr-gpu",
        action="store_true",
        help="Use EasyOCR GPU mode. Default is CPU mode.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    words = {
        word.strip().casefold()
        for word in args.words.split(",")
        if word.strip()
    }
    variants = [variant.strip() for variant in args.variants.split(",") if variant.strip()]
    invalid_variants = sorted(set(variants) - set(PREPROCESS_VARIANTS))
    if invalid_variants:
        raise SystemExit(f"Unknown preprocessing variants: {', '.join(invalid_variants)}")

    args.out.mkdir(parents=True, exist_ok=True)
    engines = engine_names(args.engines)
    runners: dict[str, Callable[[Path, Any], list[OcrRow]]] = {}
    skipped: dict[str, str] = {}

    if "tesseract" in engines:
        if args.tesseract:
            runners["tesseract"] = lambda path, _image: run_tesseract(args.tesseract, path, args.psm)
        else:
            skipped["tesseract"] = "tesseract executable was not found"
    if "rapidocr" in engines:
        try:
            runners["rapidocr"] = make_rapidocr_runner()
        except Exception as exc:
            skipped["rapidocr"] = str(exc)
    if "easyocr" in engines:
        try:
            runners["easyocr"] = make_easyocr_runner(args.easyocr_gpu)
        except Exception as exc:
            skipped["easyocr"] = str(exc)
    if "paddleocr" in engines:
        try:
            runners["paddleocr"] = make_paddleocr_runner()
        except Exception as exc:
            skipped["paddleocr"] = str(exc)

    report: list[dict[str, Any]] = []
    for engine, reason in skipped.items():
        print(f"{engine}: skipped ({reason})")

    for screenshot in args.screenshots:
        image = cv2.imread(str(screenshot))
        if image is None:
            print(f"{screenshot}: skipped (could not read image)")
            continue
        shot_out = args.out / screenshot.stem
        shot_out.mkdir(parents=True, exist_ok=True)

        for variant in variants:
            prepared = preprocess(image, variant)
            prepared_path = shot_out / f"{variant}.png"
            cv2.imwrite(str(prepared_path), prepared)
            scale = 1.0 if variant == "original" else 2.0

            for engine, runner in runners.items():
                started = time.perf_counter()
                error = None
                rows: list[OcrRow] = []
                try:
                    rows = runner(prepared_path, prepared)
                    rows = [
                        OcrRow(
                            text=row.text,
                            confidence=row.confidence,
                            box=scale_box(row.box, scale),
                        )
                        for row in rows
                    ]
                except Exception as exc:
                    error = str(exc)
                elapsed = time.perf_counter() - started
                result = EngineResult(
                    engine=engine,
                    variant=variant,
                    elapsed_seconds=elapsed,
                    rows=rows,
                    error=error,
                )
                result_dict = result.to_dict(words, args.fuzzy_threshold)
                result_dict["screenshot"] = str(screenshot)
                report.append(result_dict)

                if error is None:
                    annotated = annotate(image, rows, words, args.fuzzy_threshold)
                    cv2.imwrite(str(shot_out / f"{variant}_{engine}_annotated.png"), annotated)
                    print(
                        f"{screenshot.name} {variant} {engine}: "
                        f"{elapsed:.3f}s, {len(rows)} words, "
                        f"{len(result_dict['targets'])} targets"
                    )
                else:
                    print(f"{screenshot.name} {variant} {engine}: failed ({error})")

    report_path = args.out / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
