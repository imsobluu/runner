"""Slice obstacle sprites out of the game's texture atlases.

The base APK ships TexturePacker atlases per episode theme
(assets/kakaoBC_HD/epN01_tm01.{png,plist} ...). Frame names encode the
required action: 'jp' sprites are jump obstacles, 'sd' are slide obstacles.

    python scripts/extract_sprites.py path/to/base.apk --episode epN01

Sprites land in extracted_sprites/<atlas>/<frame>.png (RGBA).
"""
import argparse
import plistlib
import re
import sys
import zipfile
from io import BytesIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import cv2
import numpy as np


def parse_rect(text: str) -> tuple[int, int, int, int]:
    x, y, w, h = (int(n) for n in re.findall(r"-?\d+", text))
    return x, y, w, h


def slice_atlas(png_bytes: bytes, plist_bytes: bytes, out_dir: Path) -> int:
    data = plistlib.loads(plist_bytes)
    atlas = cv2.imdecode(np.frombuffer(png_bytes, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for name, frame in data["frames"].items():
        rect = frame.get("frame") or frame.get("textureRect")
        rotated = frame.get("rotated", frame.get("textureRotated", False))
        x, y, w, h = parse_rect(rect)
        if rotated:
            sprite = atlas[y : y + w, x : x + h]
            sprite = cv2.rotate(sprite, cv2.ROTATE_90_COUNTERCLOCKWISE)
        else:
            sprite = atlas[y : y + h, x : x + w]
        cv2.imwrite(str(out_dir / name), sprite)
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract sprites from game atlases.")
    parser.add_argument("apk", type=Path)
    parser.add_argument("--episode", default="epN01", help="Atlas name prefix to extract.")
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "extracted_sprites", help="Output directory."
    )
    args = parser.parse_args()

    with zipfile.ZipFile(args.apk) as apk:
        plists = [
            n
            for n in apk.namelist()
            if n.startswith(f"assets/kakaoBC_HD/{args.episode}") and n.endswith(".plist")
        ]
        if not plists:
            raise SystemExit(f"No atlases matching {args.episode!r} in {args.apk}")
        total = 0
        for plist_name in sorted(plists):
            png_name = plist_name.removesuffix(".plist") + ".png"
            atlas_stem = Path(plist_name).stem
            count = slice_atlas(
                apk.read(png_name), apk.read(plist_name), args.out / atlas_stem
            )
            print(f"{atlas_stem}: {count} sprites")
            total += count
    print(f"Extracted {total} sprites to {args.out}")


if __name__ == "__main__":
    main()
