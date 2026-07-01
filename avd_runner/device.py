from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


class AdbError(RuntimeError):
    pass


def wait(seconds: float) -> None:
    time.sleep(seconds)


@dataclass(frozen=True)
class AvdDevice:
    serial: str | None = None
    adb_path: str = "adb"

    @classmethod
    def from_env(cls) -> "AvdDevice":
        return cls(
            serial=os.environ.get("ANDROID_SERIAL"),
            adb_path=os.environ.get("ADB_PATH", "adb"),
        )

    def tap(self, x: int, y: int) -> None:
        self.shell("input", "tap", str(x), str(y))

    def long_press(self, x: int, y: int, duration_ms: int = 700) -> None:
        self.swipe(x, y, x, y, duration_ms=duration_ms)

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
    ) -> None:
        self.shell(
            "input",
            "swipe",
            str(x1),
            str(y1),
            str(x2),
            str(y2),
            str(duration_ms),
        )

    def keyevent(self, key: str | int) -> None:
        self.shell("input", "keyevent", str(key))

    def text(self, value: str) -> None:
        # ADB input text uses %s for spaces.
        escaped = value.replace(" ", "%s")
        self.shell("input", "text", escaped)

    def screen_size(self) -> tuple[int, int]:
        output = self.shell("wm", "size")
        match = re.search(r"Physical size:\s*(\d+)x(\d+)", output)
        if not match:
            raise AdbError(f"Could not parse screen size from: {output!r}")
        return int(match.group(1)), int(match.group(2))

    def screenshot_bytes(self) -> bytes:
        return self.adb("exec-out", "screencap", "-p", text=False)

    def save_screenshot(self, path: str | Path) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(self.screenshot_bytes())
        return output_path

    def shell(self, *args: str) -> str:
        return self.adb("shell", *args, text=True)

    def adb(self, *args: str, text: bool = True) -> str | bytes:
        command = [self.adb_path]
        if self.serial:
            command.extend(["-s", self.serial])
        command.extend(args)

        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=text,
        )
        if completed.returncode != 0:
            stderr = completed.stderr if text else completed.stderr.decode("utf-8", "replace")
            raise AdbError(f"ADB command failed: {' '.join(command)}\n{stderr}")
        return completed.stdout
