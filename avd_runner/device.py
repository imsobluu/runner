from __future__ import annotations

import os
import random
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Callable


class DeviceInputError(RuntimeError):
    pass


def wait(seconds: float) -> None:
    time.sleep(seconds)


# The templates and gameplay geometry in this repo are calibrated at 1280x720.
DEFAULT_DEVICE_SIZE = (1280, 720)

# Humanized tap tuning. Position jitter is a small Gaussian (buttons and
# captcha cards are >120px, so this never leaves the target); the down->up
# drift stays within touch slop so it still registers as a click, not a swipe.
_TAP_JITTER_SIGMA = 3.0
_TAP_DRIFT_PX = 3
_TAP_DWELL_MS = (55, 130)


def humanized_tap_path(x: int, y: int) -> tuple[int, int, int, int, int]:
    """A (x1, y1, x2, y2, dwell_ms) tap that no two calls reproduce exactly."""
    x1 = max(0, x + round(random.gauss(0, _TAP_JITTER_SIGMA)))
    y1 = max(0, y + round(random.gauss(0, _TAP_JITTER_SIGMA)))
    x2 = max(0, x1 + random.randint(-_TAP_DRIFT_PX, _TAP_DRIFT_PX))
    y2 = max(0, y1 + random.randint(-_TAP_DRIFT_PX, _TAP_DRIFT_PX))
    return x1, y1, x2, y2, random.randint(*_TAP_DWELL_MS)


class InputShell:
    def __init__(self, device: "AvdDevice"):
        self._device = device
        self._process: subprocess.Popen | None = None

    def __enter__(self) -> "InputShell":
        self._process = self._device.open_input_shell()
        return self

    def __exit__(self, *exc) -> None:
        if self._process is None:
            return
        if self._process.stdin:
            self._process.stdin.close()
        try:
            self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._process.terminate()

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int,
        *,
        background: bool = False,
        label: str = "",
    ) -> None:
        if self._process is None:
            raise DeviceInputError("Input shell is not open")
        self._device.write_swipe(
            self._process,
            x1,
            y1,
            x2,
            y2,
            duration_ms,
            background=background,
            label=label,
        )


@dataclass
class AvdDevice:
    """Windows capture + ADB input device abstraction.

    Screenshots are handled by ``avd_runner.capture.WindowCapture``. ADB is
    used only to inject device input.
    """

    serial: str | None = None
    adb_path: str = "adb"
    device_size: tuple[int, int] = DEFAULT_DEVICE_SIZE
    on_gesture: Callable[[int, int, int, int, int, str], None] | None = None

    @classmethod
    def from_env(cls) -> "AvdDevice":
        return cls(
            serial=os.environ.get("ANDROID_SERIAL"),
            adb_path=os.environ.get("ADB_PATH", "adb"),
        )

    def screen_size(self) -> tuple[int, int]:
        return self.device_size

    def tap(self, x: int, y: int, label: str = "") -> tuple[int, int]:
        x1, y1, x2, y2, dwell = humanized_tap_path(x, y)
        self.swipe(x1, y1, x2, y2, duration_ms=dwell, label=label)
        return x1, y1

    def long_press(self, x: int, y: int, duration_ms: int = 700, label: str = "") -> None:
        self.swipe(x, y, x, y, duration_ms=duration_ms, label=label)

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
        label: str = "",
    ) -> None:
        self.input(
            "swipe",
            str(x1),
            str(y1),
            str(x2),
            str(y2),
            str(duration_ms),
        )
        self._emit_gesture(x1, y1, x2, y2, duration_ms, label)

    def keyevent(self, key: str | int) -> None:
        self.input("keyevent", str(key))

    def text(self, value: str) -> None:
        escaped = shlex.quote(value.replace(" ", "%s"))
        self.input("text", escaped)

    def input(self, *args: str) -> str:
        return self._adb("shell", "input", *args, text=True)

    def open_input_shell(self) -> subprocess.Popen:
        return subprocess.Popen(
            self._command("shell"),
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def input_shell(self) -> InputShell:
        return InputShell(self)

    def write_swipe(
        self,
        shell: subprocess.Popen,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int,
        *,
        background: bool = False,
        label: str = "",
    ) -> None:
        assert shell.stdin is not None
        suffix = " &" if background else ""
        shell.stdin.write(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}{suffix}\n")
        shell.stdin.flush()
        self._emit_gesture(x1, y1, x2, y2, duration_ms, label)

    def _emit_gesture(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int,
        label: str = "",
    ) -> None:
        if self.on_gesture is not None:
            self.on_gesture(x1, y1, x2, y2, duration_ms, label)

    def _command(self, *args: str) -> list[str]:
        command = [self.adb_path]
        if self.serial:
            command.extend(["-s", self.serial])
        command.extend(args)
        return command

    def _adb(self, *args: str, text: bool = True) -> str | bytes:
        command = self._command(*args)
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=text,
        )
        if completed.returncode != 0:
            stderr = completed.stderr if text else completed.stderr.decode("utf-8", "replace")
            raise DeviceInputError(f"ADB input command failed: {' '.join(command)}\n{stderr}")
        return completed.stdout
