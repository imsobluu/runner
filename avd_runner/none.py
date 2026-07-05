from __future__ import annotations

import random
import subprocess
import time
from pathlib import Path

from .device import AvdDevice
from .vision import find_template

CHECK_EVERY = 15  # frames between full-frame exit/relay template checks

class NoneRunner:
    """Do nothing for one gameplay run.

    Exits when ``exit_template`` (the result screen) appears. If
    ``relay_template`` is given, taps it when it shows up mid-run and keeps
    playing.
    """

    def __init__(
        self,
        device: AvdDevice,
        capture,  # WindowCapture; untyped to keep this module importable without it
        exit_template: Path,
        relay_template: Path | None = None,
    ):
        self._device = device
        self._capture = capture
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
        frame_count = 0
        try:
            while time.perf_counter() < deadline:
                frame = self._capture.grab()
                frame_count += 1

                if frame_count % CHECK_EVERY == 0:
                    if find_template(frame, self._exit_template, threshold=0.85):
                        print("Result screen detected; run finished.")
                        return True
                    if self._relay_template is not None:
                        match = find_template(frame, self._relay_template, threshold=0.85)
                        if match:
                            self._tap(shell, match.center_x, match.center_y, 80)
                            print("Tapped Activate Cookie Relay.")

                time.sleep(0.005)

            print("Run timed out without seeing the result screen.")
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
