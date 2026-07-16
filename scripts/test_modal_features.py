"""Compare ORB, SIFT, and AKAZE for modal-control feature matching."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np


METHODS = ("orb", "sift", "akaze")


def create_detector(name: str):
    if name == "orb":
        return cv2.ORB_create(nfeatures=2000), cv2.NORM_HAMMING
    if name == "sift":
        return cv2.SIFT_create(nfeatures=2000), cv2.NORM_L2
    if name == "akaze":
        return cv2.AKAZE_create(), cv2.NORM_HAMMING
    raise ValueError(name)


def load_template(path: Path):
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"Could not read template: {path}")
    if image.ndim == 3 and image.shape[2] == 4:
        mask = image[:, :, 3]
        color = image[:, :, :3]
    else:
        mask = None
        color = image
    return color, mask


def evaluate_method(
    screenshot,
    template,
    template_mask,
    method: str,
    ratio: float,
    min_matches: int,
):
    detector, norm = create_detector(method)
    screenshot_gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
    template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

    started = time.perf_counter()
    template_points, template_descriptors = detector.detectAndCompute(
        template_gray,
        template_mask,
    )
    screen_points, screen_descriptors = detector.detectAndCompute(
        screenshot_gray,
        None,
    )

    good = []
    if template_descriptors is not None and screen_descriptors is not None:
        matcher = cv2.BFMatcher(norm)
        for pair in matcher.knnMatch(
            template_descriptors,
            screen_descriptors,
            k=2,
        ):
            if len(pair) == 2 and pair[0].distance < ratio * pair[1].distance:
                good.append(pair[0])

    polygon = None
    inliers = 0
    homography = None
    inlier_mask = None
    if len(good) >= min_matches:
        source = np.float32(
            [template_points[match.queryIdx].pt for match in good]
        ).reshape(-1, 1, 2)
        destination = np.float32(
            [screen_points[match.trainIdx].pt for match in good]
        ).reshape(-1, 1, 2)
        homography, mask = cv2.findHomography(
            source,
            destination,
            cv2.RANSAC,
            4.0,
        )
        if homography is not None and mask is not None:
            inlier_mask = mask.ravel().tolist()
            inliers = int(mask.sum())
            height, width = template_gray.shape
            corners = np.float32(
                [[0, 0], [width, 0], [width, height], [0, height]]
            ).reshape(-1, 1, 2)
            polygon = cv2.perspectiveTransform(corners, homography)

    elapsed = time.perf_counter() - started
    annotated = screenshot.copy()
    if polygon is not None:
        cv2.polylines(
            annotated,
            [np.int32(polygon)],
            True,
            (0, 0, 255),
            3,
            cv2.LINE_AA,
        )
    status = (
        f"{method.upper()} kp={len(template_points)}/{len(screen_points)} "
        f"good={len(good)} inliers={inliers} {elapsed:.3f}s"
    )
    cv2.putText(
        annotated,
        status,
        (12, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )

    match_view = cv2.drawMatches(
        template,
        template_points,
        screenshot,
        screen_points,
        good,
        None,
        matchesMask=inlier_mask,
        flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS,
    )
    return {
        "method": method,
        "elapsed_seconds": elapsed,
        "template_keypoints": len(template_points),
        "screenshot_keypoints": len(screen_points),
        "good_matches": len(good),
        "inliers": inliers,
        "detected": polygon is not None and inliers >= min_matches,
        "polygon": (
            np.squeeze(polygon).round(2).tolist()
            if polygon is not None
            else None
        ),
    }, annotated, match_view


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare ORB/SIFT/AKAZE modal-control matching.",
    )
    parser.add_argument("screenshot", type=Path)
    parser.add_argument(
        "templates",
        nargs="*",
        type=Path,
        default=[
            Path("assets/friend-farm/x_no_bg.png"),
            Path("assets/friend-farm/confirm_no_bg.png"),
        ],
    )
    parser.add_argument(
        "--methods",
        default=",".join(METHODS),
        help="Comma-separated subset of orb,sift,akaze.",
    )
    parser.add_argument("--ratio", type=float, default=0.75)
    parser.add_argument("--min-matches", type=int, default=4)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("debug/modal_features"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    screenshot = cv2.imread(str(args.screenshot))
    if screenshot is None:
        raise SystemExit(f"Could not read screenshot: {args.screenshot}")
    methods = [method.strip().lower() for method in args.methods.split(",")]
    invalid = sorted(set(methods) - set(METHODS))
    if invalid:
        raise SystemExit(f"Unknown methods: {', '.join(invalid)}")
    args.out.mkdir(parents=True, exist_ok=True)

    report = []
    for template_path in args.templates:
        template, mask = load_template(template_path)
        for method in methods:
            result, annotated, match_view = evaluate_method(
                screenshot,
                template,
                mask,
                method,
                args.ratio,
                args.min_matches,
            )
            result["template"] = str(template_path)
            report.append(result)
            stem = f"{template_path.stem}_{method}"
            cv2.imwrite(
                str(args.out / f"{stem}_annotated.png"),
                annotated,
            )
            cv2.imwrite(
                str(args.out / f"{stem}_matches.png"),
                match_view,
            )
            print(
                f"{template_path.name} {method.upper()}: "
                f"{result['elapsed_seconds']:.3f}s, "
                f"{result['good_matches']} good, "
                f"{result['inliers']} inliers, "
                f"detected={result['detected']}"
            )

    report_path = args.out / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
