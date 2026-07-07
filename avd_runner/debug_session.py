from __future__ import annotations

from pathlib import Path


class DebugSession:
    def __init__(
        self,
        *,
        capture=None,
        window: bool = False,
        root: Path | None = None,
    ):
        self._root = root
        self._run_dir: Path | None = None
        self._tap_count = 0
        self._view = None
        if window:
            from .debugview import DebugView

            self._view = DebugView(capture=capture)

    @property
    def enabled_for_tap_saves(self) -> bool:
        return self._run_dir is not None

    @property
    def view(self):
        return self._view

    def attach_device(self, device) -> None:
        if self._view is not None:
            device.on_gesture = self.mark_swipe

    def start_run(self, run_number: int) -> None:
        if self._root is None:
            self._run_dir = None
            return
        self._run_dir = self._root / f"run{run_number}"
        self._tap_count = 0

    def show(self, screen, boxes=()) -> None:
        if self._view is None:
            return
        self._view.update(screen, boxes)

    def mark_swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int,
        label: str = "",
    ) -> None:
        if self._view is None:
            return
        self._view.mark_swipe(x1, y1, x2, y2, duration_ms, label)

    def save_tap(self, name: str, screen, x: int, y: int) -> None:
        if self._run_dir is None:
            return
        import cv2

        frame = screen.copy()
        cv2.circle(frame, (x, y), 12, (0, 0, 255), -1)
        cv2.putText(frame, f"{x}, {y}", (x + 18, y + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        self._tap_count += 1
        slug = name.lower().replace(" ", "_")
        self._run_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(self._run_dir / f"{self._tap_count:02d}_{slug}.png"), frame)

    def close(self) -> None:
        if self._view is not None:
            self._view.close()
