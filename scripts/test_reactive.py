import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import cv2

from avd_runner.reactive import detect_obstacle, load_obstacles

obstacles = load_obstacles(REPO_ROOT / "assets" / "witch_oven")
assert {(o.name, o.action) for o in obstacles} == {
    ("fork", "slide"),
    ("ham_fork", "slide"),
    ("ground_spike", "jump"),
}

# Real-frame checks against a recorded burst (skipped if not present locally).
captures = REPO_ROOT / "captures" / "probe1"
if captures.exists():
    for frame_name, expected in [
        ("frame_00226.jpg", "slide"),  # hanging fork
        ("frame_00294.jpg", "jump"),   # ground spike
        ("frame_00118.jpg", None),     # jellies only: no action
        ("frame_00082.jpg", None),     # coin/bear wall: no action
    ]:
        frame = cv2.imread(str(captures / frame_name))
        obstacle, score = detect_obstacle(frame, obstacles)
        got = obstacle.action if obstacle else None
        assert got == expected, f"{frame_name}: expected {expected}, got {got} (score={score:.2f})"
else:
    print("captures/probe1 missing; skipped real-frame checks")

print("ok")
