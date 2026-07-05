"""Reactive gameplay runner: watch the screen, jump or slide as obstacles approach.

Replaces recorded-tap playback for the side-scrolling run itself. Obstacle
sprites are template-matched in a lookahead region ahead of the cookie; the
filename of each template encodes the response: ``<name>_slide.png`` or
``<name>_jump.png``. To handle a new obstacle, crop its sprite from a
captured frame (scripts/record_frames.py) into the theme directory - no
code change needed.
"""
from __future__ import annotations

import random
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .device import AvdDevice
from .vision import find_template

# Geometry (device px, 1280x720). The cookie runs at x~300; the lookahead
# region sits ahead of it, between the HUD and the control bar.
LOOK_X1, LOOK_Y1, LOOK_X2, LOOK_Y2 = 420, 170, 780, 620
MATCH_SCALE = 0.5  # match at half resolution: ~4x faster, scores barely move
MATCH_THRESHOLD = 0.75

JUMP_XY = (165, 625)
SLIDE_XY = (1115, 625)
HOLD_MS = {"jump": 60, "slide": 500}
# An obstacle crosses the lookahead region in ~0.45s at run speed; the
# cooldown stops the same one from firing twice.
# ponytail: single cooldown assumes obstacles are >0.6s apart, which holds in
# the captured level; shrink the region or track matches if that changes.
ACTION_COOLDOWN = 0.6
CHECK_EVERY = 15  # frames between full-frame exit/relay template checks


@dataclass(frozen=True)
class Obstacle:
    name: str
    action: str  # "jump" | "slide"
    template: np.ndarray  # BGR, pre-scaled by MATCH_SCALE


def load_obstacles(theme_dir: Path) -> list[Obstacle]:
    obstacles = []
    for path in sorted(Path(theme_dir).glob("*.png")):
        name, _, action = path.stem.rpartition("_")
        if action not in HOLD_MS:
            raise ValueError(
                f"{path.name}: obstacle templates must be named <name>_jump.png or <name>_slide.png"
            )
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(f"Could not read template: {path}")
        template = cv2.resize(image, None, fx=MATCH_SCALE, fy=MATCH_SCALE)
        obstacles.append(Obstacle(name=name, action=action, template=template))
    if not obstacles:
        raise ValueError(f"No obstacle templates in {theme_dir}")
    return obstacles


def detect_obstacle(
    frame: np.ndarray,
    obstacles: list[Obstacle],
) -> tuple[Obstacle | None, float]:
    """Best obstacle match in the lookahead region of a full BGR frame."""
    region = frame[LOOK_Y1:LOOK_Y2, LOOK_X1:LOOK_X2]
    region = cv2.resize(region, None, fx=MATCH_SCALE, fy=MATCH_SCALE)
    best: Obstacle | None = None
    best_score = MATCH_THRESHOLD
    for obstacle in obstacles:
        result = cv2.matchTemplate(region, obstacle.template, cv2.TM_CCOEFF_NORMED)
        _, score, _, _ = cv2.minMaxLoc(result)
        if score >= best_score:
            best, best_score = obstacle, score
    return best, best_score


class ReactiveRunner:
    """Capture-detect-act loop for one gameplay run.

    Exits when ``exit_template`` (the result screen) appears. If
    ``relay_template`` is given, taps it when it shows up mid-run and keeps
    playing.
    """

    def __init__(
        self,
        device: AvdDevice,
        capture,  # WindowCapture; untyped to keep this module importable without it
        theme_dir: Path,
        exit_template: Path,
        relay_template: Path | None = None,
    ):
        self._device = device
        self._capture = capture
        self._obstacles = load_obstacles(theme_dir)
        self._exit_template = exit_template
        self._relay_template = relay_template

    def run(self, max_seconds: float = 900.0) -> bool:
        """Play until the result screen appears. False on timeout."""
        shell = subprocess.Popen(
            self._device.command("shell"),
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert shell.stdin is not None
        deadline = time.perf_counter() + max_seconds
        cooldown_until = 0.0
        frame_count = 0
        try:
            while time.perf_counter() < deadline:
                frame = self._capture.grab()
                frame_count += 1

                if frame_count % CHECK_EVERY == 0:
                    if find_template(frame, self._exit_template, threshold=0.85):
                        print("Result screen detected; reactive run finished.")
                        return True
                    if self._relay_template is not None:
                        match = find_template(frame, self._relay_template, threshold=0.85)
                        if match:
                            self._tap(shell, match.center_x, match.center_y, 80)
                            print("Tapped Activate Cookie Relay.")

                now = time.perf_counter()
                if now >= cooldown_until:
                    obstacle, score = detect_obstacle(frame, self._obstacles)
                    if obstacle is not None:
                        x, y = JUMP_XY if obstacle.action == "jump" else SLIDE_XY
                        self._tap(shell, x, y, HOLD_MS[obstacle.action])
                        print(f"{obstacle.action} for {obstacle.name} score={score:.2f}")
                        cooldown_until = now + ACTION_COOLDOWN

                time.sleep(0.005)

            print("Reactive run timed out without seeing the result screen.")
            return False
        finally:
            shell.stdin.close()
            try:
                shell.wait(timeout=2)
            except subprocess.TimeoutExpired:
                shell.terminate()

    def _tap(self, shell: subprocess.Popen, x: int, y: int, hold_ms: int) -> None:
        # Jitter position and dwell; identical taps run after run look robotic.
        x += random.randint(-25, 25)
        y += random.randint(-20, 20)
        hold = max(40, round(hold_ms * random.uniform(0.85, 1.15)))
        assert shell.stdin is not None
        shell.stdin.write(f"input swipe {x} {y} {x} {y} {hold}\n")
        shell.stdin.flush()
