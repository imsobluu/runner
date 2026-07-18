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
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import math
import numpy as np

from .device import AvdDevice
from .vision import find_template

# Geometry (device px, 1280x720). The cookie runs at x~300; the lookahead
# region sits ahead of it, between the HUD and the control bar.
LOOK_X1, LOOK_Y1, LOOK_X2, LOOK_Y2 = 360, 170, 1040, 620
ACTION_TRIGGER_X = 600  # 1280x720 ref; 450px in the 960x540 debug frame
MATCH_SCALE = 0.5  # match at half resolution: ~4x faster, scores barely move
MATCH_THRESHOLD = 0.85
OBSTACLE_TEMPLATE_SCALES = (1.10,)

JUMP_XY = (165, 625)
SLIDE_XY = (1115, 625)
HOLD_MS = {"jump": 60, "slide": 500}
DOUBLE_JUMP_GAP_SECONDS = 0.12
# An obstacle crosses the lookahead region in ~0.45s at run speed; the
# cooldown stops the same one from firing twice.
# ponytail: single cooldown assumes obstacles are >0.6s apart, which holds in
# the captured level; shrink the region or track matches if that changes.
ACTION_COOLDOWN = 0.6
CHECK_EVERY = 15  # frames between full-frame exit/activation template checks


@dataclass(frozen=True)
class Obstacle:
    name: str
    action: str  # "jump" | "slide"
    template: np.ndarray  # BGR, pre-scaled by MATCH_SCALE
    mask: np.ndarray | None = None  # alpha mask, pre-scaled with the template
    scale: float = 1.0


@dataclass
class ReactiveState:
    cooldown_until: float = 0.0
    frame_count: int = 0


def load_obstacles(
    theme_dir: Path,
    *,
    frame_scale: tuple[float, float] = (1.0, 1.0),
) -> list[Obstacle]:
    obstacles = []
    for path in sorted(Path(theme_dir).glob("*.png")):
        name, _, action = path.stem.rpartition("_")
        if action not in HOLD_MS:
            raise ValueError(
                f"{path.name}: obstacle templates must be named <name>_jump.png or <name>_slide.png"
            )
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError(f"Could not read template: {path}")
        mask = None
        if image.ndim == 3 and image.shape[2] == 4:
            alpha = image[:, :, 3]
            non_empty = cv2.findNonZero(alpha)
            if non_empty is not None:
                x, y, w, h = cv2.boundingRect(non_empty)
                mask = alpha[y:y + h, x:x + w]
                image = image[y:y + h, x:x + w, :3]
            else:
                image = image[:, :, :3]
        base_template = cv2.resize(
            image,
            None,
            fx=MATCH_SCALE * frame_scale[0],
            fy=MATCH_SCALE * frame_scale[1],
        )
        if mask is not None:
            mask = cv2.resize(
                mask,
                (base_template.shape[1], base_template.shape[0]),
                interpolation=cv2.INTER_NEAREST,
            )
        for scale in OBSTACLE_TEMPLATE_SCALES:
            template = cv2.resize(
                base_template,
                None,
                fx=scale,
                fy=scale,
            )
            scaled_mask = None
            if mask is not None:
                scaled_mask = cv2.resize(
                    mask,
                    (template.shape[1], template.shape[0]),
                    interpolation=cv2.INTER_NEAREST,
                )
            obstacles.append(
                Obstacle(
                    name=name,
                    action=action,
                    template=template,
                    mask=scaled_mask,
                    scale=scale,
                )
            )
    if not obstacles:
        raise ValueError(f"No obstacle templates in {theme_dir}")
    return obstacles


def detect_obstacle(
    frame: np.ndarray,
    obstacles: list[Obstacle],
    look_region: tuple[int, int, int, int] = (LOOK_X1, LOOK_Y1, LOOK_X2, LOOK_Y2),
) -> tuple[Obstacle | None, float, tuple[int, int, int, int] | None]:
    """Best obstacle match in the lookahead region of a full BGR frame.

    Returns (obstacle, score, box) where box is the match rectangle in
    full-frame device pixels, or None when nothing matched.
    """
    best, best_score, best_box = best_obstacle_candidate(frame, obstacles, look_region)
    if best_score < MATCH_THRESHOLD:
        return None, best_score, None
    return best, best_score, best_box


def best_obstacle_candidate(
    frame: np.ndarray,
    obstacles: list[Obstacle],
    look_region: tuple[int, int, int, int] = (LOOK_X1, LOOK_Y1, LOOK_X2, LOOK_Y2),
) -> tuple[Obstacle | None, float, tuple[int, int, int, int] | None]:
    """Best raw obstacle candidate, even when below the action threshold."""
    look_x1, look_y1, look_x2, look_y2 = look_region
    region = frame[look_y1:look_y2, look_x1:look_x2]
    region = cv2.resize(region, None, fx=MATCH_SCALE, fy=MATCH_SCALE)
    best: Obstacle | None = None
    best_score = float("-inf")
    best_box: tuple[int, int, int, int] | None = None
    for obstacle in obstacles:
        region_h, region_w = region.shape[:2]
        template_h, template_w = obstacle.template.shape[:2]
        if template_h > region_h or template_w > region_w:
            continue
        if obstacle.mask is None:
            result = cv2.matchTemplate(region, obstacle.template, cv2.TM_CCOEFF_NORMED)
        else:
            result = cv2.matchTemplate(
                region,
                obstacle.template,
                cv2.TM_CCOEFF_NORMED,
                mask=obstacle.mask,
            )
        _, score, _, loc = cv2.minMaxLoc(result)
        if not math.isfinite(score):
            continue
        if score >= best_score:
            x1 = look_x1 + round(loc[0] / MATCH_SCALE)
            y1 = look_y1 + round(loc[1] / MATCH_SCALE)
            best = obstacle
            best_score = score
            best_box = (
                x1,
                y1,
                x1 + round(template_w / MATCH_SCALE),
                y1 + round(template_h / MATCH_SCALE),
            )
    return best, best_score, best_box


class ReactiveRunner:
    """Capture-detect-act loop for one gameplay run.

    Exits when ``exit_template`` (the result screen) appears. If
    ``relay_template`` is given, taps it when it shows up mid-run and keeps
    playing. If ``fast_start_template`` is given, taps it once.
    """

    def __init__(
        self,
        device: AvdDevice,
        capture,  # WindowCapture; untyped to keep this module importable without it
        theme_dir: Path,
        exit_template: Path,
        relay_template: Path | None = None,
        fast_start_template: Path | None = None,
        debug_view=None,  # DebugView; draws lookahead/detection/taps live
        reference_size: tuple[int, int] = (1280, 720),
        frame_size: tuple[int, int] | None = None,
    ):
        self._device = device
        self._capture = capture
        if frame_size is None:
            frame_size = reference_size
        self._frame_scale = (
            frame_size[0] / reference_size[0],
            frame_size[1] / reference_size[1],
        )
        self._tap_scale = (
            device.screen_size()[0] / reference_size[0],
            device.screen_size()[1] / reference_size[1],
        )
        self._look_region = (
            round(LOOK_X1 * self._frame_scale[0]),
            round(LOOK_Y1 * self._frame_scale[1]),
            round(LOOK_X2 * self._frame_scale[0]),
            round(LOOK_Y2 * self._frame_scale[1]),
        )
        self._obstacles = load_obstacles(theme_dir, frame_scale=self._frame_scale)
        self._exit_template = exit_template
        self._relay_template = relay_template
        self._fast_start_template = fast_start_template
        self._fast_start_handled = False
        self._debug_view = debug_view

    def _check_exit_or_relay(self, frame, shell) -> bool:
        if find_template(frame, self._exit_template, threshold=0.85):
            print("Result screen detected; reactive run finished.")
            return True
        if not self._fast_start_handled and self._fast_start_template is not None:
            match = find_template(frame, self._fast_start_template, threshold=0.85)
            if match:
                self._tap(shell, match.center_x, match.center_y, 80, "fast_start")
                self._fast_start_handled = True
                print("Tapped Activate Fast Start.")
        if self._relay_template is not None:
            match = find_template(frame, self._relay_template, threshold=0.85)
            if match:
                self._tap(shell, match.center_x, match.center_y, 80, "relay")
                print("Tapped Activate Cookie Relay.")
        return False

    def _handle_obstacle(
        self,
        state: ReactiveState,
        shell,
        obstacle: Obstacle | None,
        score: float,
        now: float,
        box: tuple[int, int, int, int] | None = None,
    ) -> None:
        if obstacle is None or now < state.cooldown_until:
            return
        if box is not None and not self._obstacle_reached_trigger(box):
            return
        x, y = JUMP_XY if obstacle.action == "jump" else SLIDE_XY
        tap_scale = getattr(self, "_tap_scale", (1.0, 1.0))
        x = round(x * tap_scale[0])
        y = round(y * tap_scale[1])
        self._tap(shell, x, y, HOLD_MS[obstacle.action], obstacle.action)
        if obstacle.action == "jump" and "_jp2" in obstacle.name:
            time.sleep(DOUBLE_JUMP_GAP_SECONDS)
            self._tap(shell, x, y, HOLD_MS[obstacle.action], "double_jump")
            label = "double_jump"
        else:
            label = obstacle.action
        print(f"{label} for {obstacle.name} score={score:.2f} scale={obstacle.scale:.2f}")
        state.cooldown_until = now + ACTION_COOLDOWN

    def _trigger_x(self) -> int:
        frame_scale = getattr(self, "_frame_scale", (1.0, 1.0))
        return round(ACTION_TRIGGER_X * frame_scale[0])

    def _obstacle_reached_trigger(self, box: tuple[int, int, int, int]) -> bool:
        center_x = (box[0] + box[2]) // 2
        return center_x <= self._trigger_x()

    def _update_debug_view(
        self,
        frame,
        obstacle: Obstacle | None,
        score: float,
        box: tuple[int, int, int, int] | None,
        candidate: Obstacle | None = None,
        candidate_score: float | None = None,
        candidate_box: tuple[int, int, int, int] | None = None,
    ) -> None:
        if self._debug_view is None:
            return
        look_region = getattr(
            self,
            "_look_region",
            (LOOK_X1, LOOK_Y1, LOOK_X2, LOOK_Y2),
        )
        boxes = [(*look_region, "lookahead", (0, 255, 0))]
        trigger_x = self._trigger_x()
        boxes.append((trigger_x - 2, look_region[1], trigger_x + 2, look_region[3], "trigger", (255, 255, 0)))
        if box is not None and obstacle is not None:
            boxes.append((*box, f"{obstacle.name} {score:.2f} s={obstacle.scale:.2f}", (0, 0, 255)))
        elif candidate_box is not None and candidate is not None and candidate_score is not None:
            color = (255, 255, 0) if candidate_score >= MATCH_THRESHOLD else (0, 255, 255)
            prefix = "wait" if candidate_score >= MATCH_THRESHOLD else "best"
            boxes.append((
                *candidate_box,
                f"{prefix} {candidate.name} {candidate_score:.2f} s={candidate.scale:.2f}",
                color,
            ))
        self._debug_view.update(frame, boxes)

    def run(self, max_seconds: float = 900.0) -> bool:
        """Play until the result screen appears. False on timeout."""
        deadline = time.perf_counter() + max_seconds
        state = ReactiveState()
        last_stats = time.perf_counter() if self._debug_view is not None else 0.0
        with self._device.input_shell() as shell:
            while time.perf_counter() < deadline:
                loop_started = time.perf_counter() if self._debug_view is not None else 0.0
                frame = self._capture.grab()
                state.frame_count += 1

                if state.frame_count % CHECK_EVERY == 0:
                    if self._check_exit_or_relay(frame, shell):
                        return True

                now = time.perf_counter()
                look_region = getattr(
                    self,
                    "_look_region",
                    (LOOK_X1, LOOK_Y1, LOOK_X2, LOOK_Y2),
                )
                candidate = None
                candidate_score = None
                candidate_box = None
                if self._debug_view is not None:
                    candidate, raw_score, candidate_box = best_obstacle_candidate(
                        frame,
                        self._obstacles,
                        look_region,
                    )
                    candidate_score = raw_score
                    if (
                        candidate is not None
                        and raw_score >= MATCH_THRESHOLD
                        and candidate_box is not None
                        and self._obstacle_reached_trigger(candidate_box)
                    ):
                        obstacle, score, box = candidate, raw_score, candidate_box
                    else:
                        obstacle, score, box = None, raw_score, None
                    if state.frame_count % 30 == 0 and candidate is not None:
                        elapsed = max(1e-6, time.perf_counter() - last_stats)
                        fps = 30 / elapsed
                        last_stats = time.perf_counter()
                        print(
                            f"best candidate {candidate.name} "
                            f"score={raw_score:.2f} scale={candidate.scale:.2f} "
                            f"loop={1000 * (time.perf_counter() - loop_started):.1f}ms "
                            f"fps={fps:.1f}"
                        )
                else:
                    try:
                        obstacle, score, box = detect_obstacle(
                            frame,
                            self._obstacles,
                            look_region,
                        )
                    except TypeError:
                        obstacle, score, box = detect_obstacle(frame, self._obstacles)
                self._handle_obstacle(state, shell, obstacle, score, now, box)
                self._update_debug_view(
                    frame,
                    obstacle,
                    score,
                    box,
                    candidate,
                    candidate_score,
                    candidate_box,
                )

                time.sleep(0.005)

            print("Reactive run timed out without seeing the result screen.")
            return False

    def _tap(self, shell, x: int, y: int, hold_ms: int, label: str = "") -> None:
        # Jitter position, dwell, and add a few px of down->up drift; identical
        # zero-travel taps run after run look robotic.
        x += random.randint(-25, 25)
        y += random.randint(-20, 20)
        x2 = x + random.randint(-3, 3)
        y2 = y + random.randint(-3, 3)
        hold = max(40, round(hold_ms * random.uniform(0.85, 1.15)))
        shell.swipe(x, y, x2, y2, hold, label=label)
