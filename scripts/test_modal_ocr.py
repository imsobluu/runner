"""Evaluate OCR-based modal-control detection on a saved screenshot."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import time
from pathlib import Path

import cv2


DEFAULT_WORDS = ("confirm", "close", "ok", "yes", "continue")


def preprocess(image, variant: str):
    if variant == "original":
        return image
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    if variant == "gray2x":
        return gray
    if variant == "otsu2x":
        return cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
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


def run_tesseract(
    executable: str,
    image_path: Path,
    psm: int,
) -> tuple[list[dict], float]:
    started = time.perf_counter()
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
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Tesseract failed")

    rows = []
    for row in csv.DictReader(result.stdout.splitlines(), delimiter="\t"):
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
        rows.append(
            {
                "text": text,
                "confidence": confidence,
                "box": [left, top, width, height],
            }
        )
    return rows, elapsed


def annotate(image, rows: list[dict], words: set[str], scale: float):
    output = image.copy()
    for row in rows:
        normalized = row["text"].casefold().strip(".,!?:;()[]{}")
        is_target = normalized in words
        x, y, width, height = row["box"]
        x = round(x / scale)
        y = round(y / scale)
        width = round(width / scale)
        height = round(height / scale)
        color = (0, 0, 255) if is_target else (0, 180, 0)
        cv2.rectangle(output, (x, y), (x + width, y + height), color, 2)
        cv2.putText(
            output,
            f"{row['text']} {row['confidence']:.0f}",
            (x, max(18, y - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2.LINE_AA,
        )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark Tesseract OCR for modal buttons.",
    )
    parser.add_argument("screenshot", type=Path)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("debug/modal_ocr"),
    )
    parser.add_argument(
        "--words",
        default=",".join(DEFAULT_WORDS),
        help="Comma-separated target words.",
    )
    parser.add_argument("--psm", type=int, default=11)
    parser.add_argument(
        "--tesseract",
        default=shutil.which("tesseract"),
        help="Path to tesseract.exe.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.tesseract:
        raise SystemExit(
            "Tesseract was not found. Install Tesseract OCR or pass "
            "--tesseract C:\\path\\to\\tesseract.exe"
        )

    image = cv2.imread(str(args.screenshot))
    if image is None:
        raise SystemExit(f"Could not read screenshot: {args.screenshot}")
    args.out.mkdir(parents=True, exist_ok=True)
    words = {
        word.strip().casefold()
        for word in args.words.split(",")
        if word.strip()
    }
    report = []

    for variant in ("original", "gray2x", "otsu2x", "adaptive2x"):
        prepared = preprocess(image, variant)
        prepared_path = args.out / f"{variant}.png"
        cv2.imwrite(str(prepared_path), prepared)
        rows, elapsed = run_tesseract(
            args.tesseract,
            prepared_path,
            args.psm,
        )
        scale = 1.0 if variant == "original" else 2.0
        targets = [
            row
            for row in rows
            if row["text"].casefold().strip(".,!?:;()[]{}") in words
        ]
        annotated = annotate(image, rows, words, scale)
        cv2.imwrite(str(args.out / f"{variant}_annotated.png"), annotated)
        report.append(
            {
                "variant": variant,
                "elapsed_seconds": elapsed,
                "targets": targets,
                "all_text": rows,
            }
        )
        print(
            f"{variant}: {elapsed:.3f}s, "
            f"{len(rows)} words, {len(targets)} targets"
        )

    report_path = args.out / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
