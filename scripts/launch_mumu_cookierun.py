import argparse
import concurrent.futures
import ctypes
import json
import math
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from avd_runner import AvdDevice
from avd_runner.capture import WindowCapture, find_render_window_in
from avd_runner.device import DEFAULT_DEVICE_SIZE
from avd_runner.levels import load_levels
from avd_runner.vision import TemplateMatch, find_template, find_template_multiscale


DEFAULT_PACKAGE = "com.devsisters.crg"
VISION_REFERENCE_SIZE = (960, 540)
FRIEND_FARM_URL = "https://cookierunglobal.onelink.me/Xr0A/ohypcxa4"
ASSETS = REPO_ROOT / "assets"
FRIEND_FARM_ASSETS = ASSETS / "friend-farm"
FRIEND_FARM_RECORDINGS_DIR = REPO_ROOT / "recordings" / "friend_farm"
RESULT_OK_BUTTON_TEMPLATE = ASSETS / "result_ok_button.png"
FRIEND_FARM_INITIAL_SEQUENCE = [
    FRIEND_FARM_ASSETS / name
    for name in (
        "devplay_login.png",
        "play.png",
        "confirm.png",
        "pause.png",
        "quit.png",
        "quit.png",
    )
]
FRIEND_FARM_WORKSHOP_SEQUENCE = [
    FRIEND_FARM_ASSETS / name
    for name in ("episode.png", "xp-elixir_workshop.png", "enter.png")
]
FRIEND_FARM_PLAY_3_TEMPLATE = FRIEND_FARM_ASSETS / "play_3.png"
FRIEND_FARM_EARN_XP_TEMPLATE = FRIEND_FARM_ASSETS / "earn_xp.png"
_transparent_template_cache: dict[str, object] = {}

COMMON_MUMU_MANAGER_PATHS = [
    r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\MuMuManager.exe",
    r"C:\Program Files\Netease\MuMu Player 12\shell\MuMuManager.exe",
    r"C:\Program Files\Netease\MuMuPlayerGlobal-12.0\shell\MuMuManager.exe",
    r"C:\Program Files (x86)\Netease\MuMuPlayer-12.0\shell\MuMuManager.exe",
    r"C:\Program Files (x86)\Netease\MuMu Player 12\shell\MuMuManager.exe",
    r"C:\Program Files (x86)\Netease\MuMuPlayerGlobal-12.0\shell\MuMuManager.exe",
]


def parse_instance_list(value: str) -> list[int]:
    instances: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if end < start:
                raise argparse.ArgumentTypeError(f"invalid descending range: {part}")
            instances.extend(range(start, end + 1))
        else:
            instances.append(int(part))
    return sorted(set(instances))


def parse_grid(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", value)
    if match is None:
        raise argparse.ArgumentTypeError("grid must use COLUMNSxROWS, for example 3x2")
    columns, rows = (int(part) for part in match.groups())
    if columns < 1 or rows < 1:
        raise argparse.ArgumentTypeError("grid dimensions must be at least 1")
    return columns, rows


def run_command(command: list[str], *, dry_run: bool = False, timeout: float | None = None) -> subprocess.CompletedProcess:
    print(" ".join(command))
    if dry_run:
        return subprocess.CompletedProcess(command, 0, "", "")
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def find_mumu_manager(explicit_path: str | None) -> Path | None:
    if explicit_path:
        path = Path(explicit_path)
        return path if path.exists() else None

    env_path = os.environ.get("MUMU_MANAGER_PATH")
    if env_path:
        path = Path(env_path)
        if path.exists():
            return path

    found = shutil.which("MuMuManager.exe")
    if found:
        return Path(found)

    for candidate in COMMON_MUMU_MANAGER_PATHS:
        path = Path(candidate)
        if path.exists():
            return path

    return None


def mumu_root(manager: Path) -> Path:
    if manager.parent.name.lower() in {"nx_main", "shell"}:
        return manager.parent.parent
    return manager.parent


def find_mumu_adb(manager: Path, explicit_path: str | None) -> str | None:
    if explicit_path:
        return explicit_path
    if os.environ.get("ADB_PATH"):
        return os.environ["ADB_PATH"]

    root = mumu_root(manager)
    candidates = [
        root / "nx_main" / "adb.exe",
        root / "nx_device" / "15.0" / "shell" / "adb.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return shutil.which("adb")


def configured_instances(manager: Path) -> list[int]:
    root = mumu_root(manager)
    vms_dir = root / "vms"
    if not vms_dir.exists():
        return []

    instances: list[int] = []
    for path in vms_dir.iterdir():
        if not path.is_dir():
            continue
        match = re.search(r"-(\d+)$", path.name)
        if match:
            instances.append(int(match.group(1)))
    return sorted(set(instances))


def instance_vm_dir(manager: Path, instance: int) -> Path | None:
    root = mumu_root(manager)
    vms_dir = root / "vms"
    if not vms_dir.exists():
        return None

    for path in vms_dir.iterdir():
        if path.is_dir() and path.name.endswith(f"-{instance}"):
            return path
    return None


def instance_adb_serial(manager: Path, instance: int) -> str | None:
    vm_dir = instance_vm_dir(manager, instance)
    if vm_dir is None:
        return None

    config_path = vm_dir / "configs" / "vm_config.json"
    if not config_path.exists():
        return None

    with config_path.open(encoding="utf-8") as f:
        config = json.load(f)

    port = (
        config.get("vm", {})
        .get("nat", {})
        .get("port_forward", {})
        .get("adb", {})
        .get("host_port")
    )
    if not port:
        return None
    return f"127.0.0.1:{port}"


def instance_device_size(
    manager: Path,
    instance: int,
) -> tuple[int, int] | None:
    vm_dir = instance_vm_dir(manager, instance)
    if vm_dir is None:
        return None
    config_path = vm_dir / "configs" / "shell_config.json"
    if not config_path.exists():
        return None

    with config_path.open(encoding="utf-8") as config_file:
        config = json.load(config_file)
    resolution = config.get("renderer", {}).get("resolution", {})
    try:
        width = round(float(resolution["width"]))
        height = round(float(resolution["height"]))
    except (KeyError, TypeError, ValueError):
        return None
    if width < 1 or height < 1:
        return None
    return max(width, height), min(width, height)


def scale_vision_point(
    x: int,
    y: int,
    device_size: tuple[int, int],
) -> tuple[int, int]:
    reference_width, reference_height = VISION_REFERENCE_SIZE
    device_width, device_height = device_size
    return (
        round(x * device_width / reference_width),
        round(y * device_height / reference_height),
    )


def tcp_listener_pids() -> dict[int, int]:
    if os.name != "nt":
        return {}

    class TcpRowOwnerPid(ctypes.Structure):
        _fields_ = [
            ("state", wintypes.DWORD),
            ("local_address", wintypes.DWORD),
            ("local_port", wintypes.DWORD),
            ("remote_address", wintypes.DWORD),
            ("remote_port", wintypes.DWORD),
            ("owning_pid", wintypes.DWORD),
        ]

    iphlpapi = ctypes.windll.iphlpapi
    size = wintypes.DWORD()
    iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, 2, 3, 0)
    buffer = ctypes.create_string_buffer(size.value)
    result = iphlpapi.GetExtendedTcpTable(
        buffer,
        ctypes.byref(size),
        False,
        2,
        3,
        0,
    )
    if result != 0:
        return {}

    count = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value
    rows_address = ctypes.addressof(buffer) + ctypes.sizeof(wintypes.DWORD)
    rows = ctypes.cast(
        rows_address,
        ctypes.POINTER(TcpRowOwnerPid),
    )
    return {
        socket.ntohs(rows[index].local_port & 0xFFFF): rows[index].owning_pid
        for index in range(count)
    }


def main_window_for_pid(pid: int) -> int | None:
    user32 = ctypes.windll.user32
    candidates: list[tuple[int, int]] = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )

    @callback_type
    def collect(hwnd: int, _lparam: int) -> bool:
        window_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        if window_pid.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        rect = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            area = max(0, rect.right - rect.left) * max(
                0, rect.bottom - rect.top
            )
            candidates.append((area, hwnd))
        return True

    user32.EnumWindows(collect, 0)
    return max(candidates)[1] if candidates else None


def mumu_window_for_serial(serial: str) -> int | None:
    try:
        port = int(serial.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None
    pid = tcp_listener_pids().get(port)
    return None if pid is None else main_window_for_pid(pid)


def wait_for_landscape_window(
    serial: str,
    timeout_seconds: float,
    *,
    dry_run: bool,
) -> bool:
    if dry_run:
        print(f"{serial}: wait for stable landscape window")
        return True

    deadline = time.monotonic() + timeout_seconds
    stable_checks = 0
    while time.monotonic() < deadline:
        hwnd = mumu_window_for_serial(serial)
        rect = wintypes.RECT()
        render_hwnd = None if hwnd is None else find_render_window_in(hwnd)
        if render_hwnd is not None and ctypes.windll.user32.GetWindowRect(
            render_hwnd,
            ctypes.byref(rect),
        ):
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            stable_checks = stable_checks + 1 if width > height else 0
            if stable_checks >= 2:
                print(
                    f"{serial}: landscape window ready "
                    f"({width}x{height})"
                )
                return True
        else:
            stable_checks = 0
        time.sleep(1)
    return False


def mumu_command(manager: Path, instance: int, *args: str) -> list[str]:
    return [str(manager), *args[:1], "-v", str(instance), *args[1:]]


def launch_player(manager: Path, instance: int, *, dry_run: bool) -> bool:
    result = run_command(
        mumu_command(manager, instance, "api", "launch_player"),
        dry_run=dry_run,
        timeout=30,
    )
    if result.returncode == 0:
        return True

    sys.stderr.write(result.stderr)
    return False


def connect_adb(
    adb_path: str,
    serial: str,
    timeout_seconds: float,
    *,
    dry_run: bool,
) -> bool:
    if dry_run:
        run_command([adb_path, "connect", serial], dry_run=True)
        return True

    deadline = time.monotonic() + timeout_seconds
    next_recycle = time.monotonic()
    needs_connect = True
    while time.monotonic() < deadline:
        if needs_connect:
            run_command([adb_path, "connect", serial], timeout=15)
            needs_connect = False
        state = run_command(
            [adb_path, "-s", serial, "get-state"],
            timeout=15,
        )
        if state.returncode == 0 and state.stdout.strip() == "device":
            return True

        now = time.monotonic()
        if now >= next_recycle:
            run_command([adb_path, "disconnect", serial], timeout=15)
            needs_connect = True
            next_recycle = now + 10
        time.sleep(2)

    return False


def wait_for_android_ready(
    adb_path: str,
    serial: str,
    timeout_seconds: float,
    *,
    dry_run: bool,
) -> bool:
    if dry_run:
        return True

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = run_command(
            [adb_path, "-s", serial, "shell", "pm", "path", "android"],
            dry_run=False,
            timeout=15,
        )
        if (
            result.returncode == 0
            and result.stdout.strip().startswith("package:")
        ):
            return True
        time.sleep(2)
    return False


def package_is_installed(adb_path: str, serial: str, package: str, *, dry_run: bool) -> bool:
    result = run_command(
        [adb_path, "-s", serial, "shell", "pm", "path", package],
        dry_run=dry_run,
        timeout=15,
    )
    if dry_run:
        return True
    return result.returncode == 0 and result.stdout.strip().startswith("package:")


def resolve_launcher_activity(adb_path: str, serial: str, package: str, *, dry_run: bool) -> str | None:
    result = run_command(
        [
            adb_path,
            "-s",
            serial,
            "shell",
            "cmd",
            "package",
            "resolve-activity",
            "--brief",
            "-c",
            "android.intent.category.LAUNCHER",
            package,
        ],
        dry_run=dry_run,
        timeout=15,
    )
    if dry_run:
        return f"{package}/.LauncherActivity"
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return None

    for line in reversed(result.stdout.splitlines()):
        line = line.strip()
        if "/" in line and not line.startswith("No activity"):
            return line
    return None


def launch_app_with_adb(adb_path: str, serial: str, package: str, *, dry_run: bool) -> bool:
    activity = resolve_launcher_activity(adb_path, serial, package, dry_run=dry_run)
    if activity is None:
        print(f"Could not resolve launcher activity for {package} on {serial}.")
        return False

    result = run_command(
        [
            adb_path,
            "-s",
            serial,
            "shell",
            "am",
            "start",
            "-n",
            activity,
            "-a",
            "android.intent.action.MAIN",
            "-c",
            "android.intent.category.LAUNCHER",
        ],
        dry_run=dry_run,
        timeout=30,
    )
    if result.stdout.strip():
        print(f"{serial}: {result.stdout.strip()}")
    if result.returncode == 0:
        print(f"{serial}: launched {package}")
        return True

    sys.stderr.write(result.stderr)
    return False


def tap_template_on_device(
    adb_path: str,
    serial: str,
    capture: WindowCapture | None,
    device_size: tuple[int, int],
    template: Path,
    timeout_seconds: float,
    *,
    dry_run: bool,
) -> bool:
    if dry_run:
        print(f"{serial}: wait for and tap {template}")
        return True
    if capture is None:
        print(f"{serial}: WGC capture is unavailable.")
        return False

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        match = find_template_multiscale(capture.grab(), template, threshold=0.85)
        if match is not None:
            tap_x, tap_y = scale_vision_point(
                match.center_x,
                match.center_y,
                device_size,
            )
            tap = run_command(
                [
                    adb_path,
                    "-s",
                    serial,
                    "shell",
                    "input",
                    "tap",
                    str(tap_x),
                    str(tap_y),
                ],
                timeout=15,
            )
            if tap.returncode == 0:
                print(
                    f"{serial}: tapped {template.name} "
                    f"({match.score:.3f})"
                )
                time.sleep(1.5)
                return True
        time.sleep(1)

    print(f"{serial}: timed out waiting for {template}.")
    return False


def run_nickname_step(
    adb_path: str,
    serial: str,
    capture: WindowCapture | None,
    device_size: tuple[int, int],
    timeout_seconds: float,
    *,
    dry_run: bool,
) -> bool:
    nickname_template = FRIEND_FARM_ASSETS / "enter_your_nickname.png"
    confirm_template = FRIEND_FARM_ASSETS / "confirm_no_bg.png"
    nickname = f"farm{secrets.token_hex(4)}"

    if not tap_template_on_device(
        adb_path,
        serial,
        capture,
        device_size,
        nickname_template,
        timeout_seconds,
        dry_run=dry_run,
    ):
        return False

    text_result = run_command(
        [adb_path, "-s", serial, "shell", "input", "text", nickname],
        dry_run=dry_run,
        timeout=15,
    )
    if text_result.returncode != 0:
        sys.stderr.write(text_result.stderr)
        return False

    enter_result = run_command(
        [adb_path, "-s", serial, "shell", "input", "keyevent", "66"],
        dry_run=dry_run,
        timeout=15,
    )
    if enter_result.returncode != 0:
        sys.stderr.write(enter_result.stderr)
        return False

    print(f"{serial}: entered nickname {nickname}")
    return tap_transparent_template_on_device(
        adb_path,
        serial,
        capture,
        device_size,
        confirm_template,
        timeout_seconds,
        dry_run=dry_run,
    )


def find_transparent_template_multiscale(
    screenshot,
    template_path: Path,
    threshold: float = 0.9,
    center_region: tuple[float, float, float, float] | None = None,
) -> TemplateMatch | None:
    import cv2
    import numpy as np

    if isinstance(screenshot, bytes):
        screen = cv2.imdecode(
            np.frombuffer(screenshot, dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
    else:
        screen = screenshot
    if screen is None:
        return None

    key = str(template_path)
    template = _transparent_template_cache.get(key)
    if template is None:
        template = cv2.imread(key, cv2.IMREAD_UNCHANGED)
        if template is None or template.shape[2] != 4:
            raise ValueError(
                f"Transparent template must be an RGBA image: {template_path}"
            )
        _transparent_template_cache[key] = template

    color = template[:, :, :3]
    alpha = template[:, :, 3]
    screen_height, screen_width = screen.shape[:2]
    best: TemplateMatch | None = None

    scale_percents = sorted(
        range(50, 201, 10),
        key=lambda value: abs(value - 100),
    )
    for scale_percent in scale_percents:
        scale = scale_percent / 100
        width = round(color.shape[1] * scale)
        height = round(color.shape[0] * scale)
        if (
            width < 4
            or height < 4
            or width > screen_width
            or height > screen_height
        ):
            continue

        resized_color = cv2.resize(
            color,
            (width, height),
            interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
        )
        resized_mask = cv2.resize(
            alpha,
            (width, height),
            interpolation=cv2.INTER_NEAREST,
        )
        result = cv2.matchTemplate(
            screen,
            resized_color,
            cv2.TM_CCORR_NORMED,
            mask=resized_mask,
        )
        result = np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)
        offset_x = 0
        offset_y = 0
        if center_region is not None:
            region_x1, region_y1, region_x2, region_y2 = center_region
            min_x = max(0, math.ceil(region_x1 * screen_width - width / 2))
            max_x = min(
                result.shape[1] - 1,
                math.floor(region_x2 * screen_width - width / 2),
            )
            min_y = max(0, math.ceil(region_y1 * screen_height - height / 2))
            max_y = min(
                result.shape[0] - 1,
                math.floor(region_y2 * screen_height - height / 2),
            )
            if min_x > max_x or min_y > max_y:
                continue
            result = result[min_y : max_y + 1, min_x : max_x + 1]
            offset_x = min_x
            offset_y = min_y

        _, score, _, location = cv2.minMaxLoc(result)
        location = (location[0] + offset_x, location[1] + offset_y)
        if score >= threshold and (best is None or score > best.score):
            best = TemplateMatch(
                x=int(location[0]),
                y=int(location[1]),
                width=width,
                height=height,
                score=float(score),
            )
            if score >= 0.97:
                return best

    return best


def tap_transparent_template_on_device(
    adb_path: str,
    serial: str,
    capture: WindowCapture | None,
    device_size: tuple[int, int],
    template: Path,
    timeout_seconds: float,
    *,
    dry_run: bool,
) -> bool:
    if dry_run:
        print(f"{serial}: wait for and tap {template} at any scale")
        return True
    if capture is None:
        print(f"{serial}: WGC capture is unavailable.")
        return False

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        match = find_transparent_template_multiscale(
            capture.grab(),
            template,
            threshold=0.9,
        )
        if match is not None:
            tap_x, tap_y = scale_vision_point(
                match.center_x,
                match.center_y,
                device_size,
            )
            tap = run_command(
                [
                    adb_path,
                    "-s",
                    serial,
                    "shell",
                    "input",
                    "tap",
                    str(tap_x),
                    str(tap_y),
                ],
                timeout=15,
            )
            if tap.returncode == 0:
                print(
                    f"{serial}: tapped {template.name} "
                    f"({match.score:.3f})"
                )
                time.sleep(1.5)
                return True
        time.sleep(1)

    print(f"{serial}: timed out waiting for {template}.")
    return False


def close_all_modals(
    adb_path: str,
    serial: str,
    capture: WindowCapture | None,
    device_size: tuple[int, int],
    timeout_seconds: float,
    *,
    dry_run: bool,
) -> bool:
    templates = [
        FRIEND_FARM_ASSETS / "x_no_bg.png",
        FRIEND_FARM_ASSETS / "confirm_no_bg.png",
    ]
    if dry_run:
        print(f"{serial}: close all x.png or confirm.png modals")
        return True
    if capture is None:
        print(f"{serial}: WGC capture is unavailable.")
        return False

    started = time.monotonic()
    progress_deadline = started + timeout_seconds
    scan_until = started + min(8.0, timeout_seconds)
    clear_since: float | None = None
    modal_visible = False

    while time.monotonic() < progress_deadline:
        matches = []
        screenshot = capture.grab()
        for template in templates:
            match = find_transparent_template_multiscale(
                screenshot,
                template,
                threshold=0.975,
            )
            if (
                match is not None
                and template.name == "x_no_bg.png"
                and (match.width < 24 or match.height < 24)
            ):
                continue
            if match is not None:
                matches.append((match.score, template, match))

        if matches:
            modal_visible = True
            clear_since = None
            _score, template, match = max(matches, key=lambda item: item[0])
            tap_x, tap_y = scale_vision_point(
                match.center_x,
                match.center_y,
                device_size,
            )
            tap = run_command(
                [
                    adb_path,
                    "-s",
                    serial,
                    "shell",
                    "input",
                    "tap",
                    str(tap_x),
                    str(tap_y),
                ],
                timeout=15,
            )
            if tap.returncode != 0:
                sys.stderr.write(tap.stderr)
                return False
            print(f"{serial}: closed modal with {template.name}")
            progress_deadline = time.monotonic() + timeout_seconds
            time.sleep(0.4)
            continue

        modal_visible = False
        now = time.monotonic()
        if clear_since is None:
            clear_since = now
        if now >= scan_until and now - clear_since >= 3.0:
            print(f"{serial}: no more modals")
            return True
        time.sleep(0.2)

    if not modal_visible:
        print(f"{serial}: no more modals")
        return True
    print(f"{serial}: timed out while closing modals.")
    return False


def launch_chrome_url(
    adb_path: str,
    serial: str,
    url: str,
    *,
    dry_run: bool,
) -> bool:
    result = run_command(
        [
            adb_path,
            "-s",
            serial,
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            url,
            "-p",
            "com.android.chrome",
        ],
        dry_run=dry_run,
        timeout=30,
    )
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode == 0 and "Error:" not in output:
        print(f"{serial}: opened {url} in Chrome")
        return True
    sys.stderr.write(output)
    return False


def load_friend_farm_trace(
    levels_dir: Path = FRIEND_FARM_RECORDINGS_DIR,
) -> dict:
    variants = load_levels(levels_dir).get(1, [])
    if not variants:
        raise ValueError(f"No level 1 recording in {levels_dir}")
    return variants[-1]


def replay_friend_farm_trace(
    device: AvdDevice,
    menu_capture: WindowCapture,
    replay_capture: WindowCapture,
    recorded: dict,
    trigger_timeout: float,
    max_seconds: float = 1200.0,
) -> bool:
    with device.input_shell() as shell:
        trigger_deadline = time.perf_counter() + trigger_timeout
        while time.perf_counter() < trigger_deadline:
            if find_transparent_template_multiscale(
                menu_capture.grab(),
                FRIEND_FARM_EARN_XP_TEMPLATE,
                threshold=0.9,
            ):
                started = time.perf_counter()
                print(
                    f"Friend-farm timed replay of {len(recorded['taps'])} taps "
                    f"from {recorded['path'].name}."
                )
                break
            time.sleep(0.01)
        else:
            print("Timed out waiting for earn_xp.png; replay not started.")
            return False

        taps = recorded["taps"]
        tap_index = 0
        deadline = started + max_seconds
        next_result_check = started
        while time.perf_counter() < deadline:
            now = time.perf_counter()
            if now >= next_result_check:
                if find_template(
                    replay_capture.grab(),
                    RESULT_OK_BUTTON_TEMPLATE,
                    threshold=0.85,
                ):
                    print("Result screen detected; timed replay finished.")
                    return True
                next_result_check = now + 0.1

            while tap_index < len(taps) and now - started >= taps[tap_index]["t"]:
                tap = taps[tap_index]
                shell.swipe(
                    tap["x"],
                    tap["y"],
                    tap["x"],
                    tap["y"],
                    max(1, round(tap["duration"] * 1000)),
                    background=True,
                    label="friend_farm_trace",
                )
                tap_index += 1
            time.sleep(0.005)

    print("Timed replay timed out without reaching the result screen.")
    return False


def run_friend_farm_levels(
    adb_path: str,
    serial: str,
    capture: WindowCapture | None,
    device_size: tuple[int, int],
    timeout_seconds: float,
    *,
    dry_run: bool,
) -> bool:
    if dry_run:
        if not tap_template_on_device(
            adb_path,
            serial,
            capture,
            device_size,
            FRIEND_FARM_PLAY_3_TEMPLATE,
            timeout_seconds,
            dry_run=True,
        ):
            return False
        print(f"{serial}: run level replay with {FRIEND_FARM_RECORDINGS_DIR}")
        return True
    if capture is None:
        print(f"{serial}: WGC capture is unavailable.")
        return False

    replay_capture: WindowCapture | None = None
    try:
        recorded = load_friend_farm_trace()
        hwnd = mumu_window_for_serial(serial)
        if hwnd is None:
            raise RuntimeError("could not find its MuMu window")
        replay_capture = WindowCapture(
            window_hwnd=hwnd,
            device_size=DEFAULT_DEVICE_SIZE,
        )
        replay_device = AvdDevice(
            serial=serial,
            adb_path=adb_path,
            device_size=DEFAULT_DEVICE_SIZE,
            input_size=device_size,
        )
    except Exception as exc:
        if replay_capture is not None:
            replay_capture.close()
        print(f"{serial}: could not prepare timed replay: {exc}")
        return False

    try:
        if not tap_template_on_device(
            adb_path,
            serial,
            capture,
            device_size,
            FRIEND_FARM_PLAY_3_TEMPLATE,
            timeout_seconds,
            dry_run=False,
        ):
            return False
        return replay_friend_farm_trace(
            replay_device,
            capture,
            replay_capture,
            recorded,
            timeout_seconds,
        )
    except Exception as exc:
        print(f"{serial}: timed replay failed: {exc}")
        return False
    finally:
        replay_capture.close()


def run_friend_farm_sequence(
    adb_path: str,
    serial: str,
    capture: WindowCapture | None,
    device_size: tuple[int, int],
    timeout_seconds: float,
    *,
    dry_run: bool,
) -> bool:
    for template in FRIEND_FARM_INITIAL_SEQUENCE:
        if not tap_template_on_device(
            adb_path,
            serial,
            capture,
            device_size,
            template,
            timeout_seconds,
            dry_run=dry_run,
        ):
            return False

    if not run_nickname_step(
        adb_path,
        serial,
        capture,
        device_size,
        timeout_seconds,
        dry_run=dry_run,
    ):
        return False
    if not close_all_modals(
        adb_path,
        serial,
        capture,
        device_size,
        timeout_seconds,
        dry_run=dry_run,
    ):
        return False
    if not launch_chrome_url(
        adb_path,
        serial,
        FRIEND_FARM_URL,
        dry_run=dry_run,
    ):
        return False
    if not close_all_modals(
        adb_path,
        serial,
        capture,
        device_size,
        timeout_seconds,
        dry_run=dry_run,
    ):
        return False
    for template in FRIEND_FARM_WORKSHOP_SEQUENCE:
        if not tap_template_on_device(
            adb_path,
            serial,
            capture,
            device_size,
            template,
            timeout_seconds,
            dry_run=dry_run,
        ):
            return False
    return run_friend_farm_levels(
        adb_path,
        serial,
        capture,
        device_size,
        timeout_seconds,
        dry_run=dry_run,
    )


def launch_one_mumu_instance(
    manager: Path,
    adb_path: str,
    instance: int,
    package: str,
    boot_timeout: float,
    *,
    dry_run: bool,
) -> bool:
    serial = instance_adb_serial(manager, instance)
    if serial is None:
        print(f"Could not determine MuMu ADB port for instance {instance}.")
        return False

    print(f"MuMu instance {instance} ({serial})")
    if not launch_player(manager, instance, dry_run=dry_run):
        return False
    if not connect_adb(adb_path, serial, boot_timeout, dry_run=dry_run):
        print(
            f"Timed out waiting for the ADB endpoint for instance {instance} "
            f"at {serial}."
        )
        return False
    if not wait_for_android_ready(
        adb_path,
        serial,
        boot_timeout,
        dry_run=dry_run,
    ):
        print(
            f"Timed out waiting for Android package manager on "
            f"instance {instance}."
        )
        return False
    if not package_is_installed(adb_path, serial, package, dry_run=dry_run):
        print(f"{package} is not installed on {serial}.")
        return False
    if not launch_app_with_adb(adb_path, serial, package, dry_run=dry_run):
        return False
    if not wait_for_landscape_window(
        serial,
        boot_timeout,
        dry_run=dry_run,
    ):
        print(
            f"Timed out waiting for Cookie Run to switch instance "
            f"{instance} to landscape."
        )
        return False
    return True


def arrange_mumu_windows(
    manager: Path,
    grid: tuple[int, int] | None = None,
    *,
    dry_run: bool,
) -> bool:
    if dry_run:
        layout = "automatic" if grid is None else f"{grid[0]}x{grid[1]}"
        print(f"Arrange MuMu player windows in a {layout} grid")
        return True
    if os.name != "nt":
        print("Window arrangement is only supported on Windows.")
        return False

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    root = str(mumu_root(manager).resolve()).casefold()
    manager_path = str(manager.resolve()).casefold()
    windows: list[tuple[int, str]] = []

    process_query_limited_information = 0x1000

    def process_path(pid: int) -> str | None:
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return None
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                return None
            return buffer.value
        finally:
            kernel32.CloseHandle(handle)

    enum_callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    @enum_callback_type
    def collect_window(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):
            return True

        title_length = user32.GetWindowTextLengthW(hwnd)
        if title_length == 0:
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        executable = process_path(pid.value)
        if executable is None:
            return True

        executable_key = str(Path(executable).resolve()).casefold()
        if (
            executable_key == manager_path
            or not executable_key.startswith(root + os.sep)
        ):
            return True

        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        if rect.right - rect.left < 300 or rect.bottom - rect.top < 300:
            return True

        title = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        windows.append((hwnd, title.value))
        return True

    user32.EnumWindows(collect_window, 0)
    windows.sort(key=lambda item: item[1].casefold())
    if not windows:
        print("No visible MuMu player windows were found to arrange.")
        return False

    work_area = wintypes.RECT()
    if not user32.SystemParametersInfoW(
        0x0030, 0, ctypes.byref(work_area), 0
    ):
        print("Could not determine the Windows desktop work area.")
        return False

    if grid is None:
        columns = math.ceil(math.sqrt(len(windows)))
        rows = math.ceil(len(windows) / columns)
    else:
        columns, rows = grid
        if columns * rows < len(windows):
            print(
                f"Grid {columns}x{rows} has {columns * rows} cells but "
                f"{len(windows)} MuMu windows were found."
            )
            return False
    width = work_area.right - work_area.left
    height = work_area.bottom - work_area.top

    success = True
    for position, (hwnd, _title) in enumerate(windows):
        column = position % columns
        row = position // columns
        left = work_area.left + width * column // columns
        right = work_area.left + width * (column + 1) // columns
        top = work_area.top + height * row // rows
        bottom = work_area.top + height * (row + 1) // rows
        user32.ShowWindow(hwnd, 9)
        if not user32.MoveWindow(
            hwnd, left, top, right - left, bottom - top, True
        ):
            success = False

    print(
        f"Arranged {len(windows)} MuMu windows in a "
        f"{columns}x{rows} grid."
    )
    return success


def list_adb_devices(adb_path: str, *, dry_run: bool) -> list[str]:
    result = run_command([adb_path, "devices"], dry_run=dry_run, timeout=15)
    if dry_run:
        return []
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return []

    devices: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        columns = line.split()
        if len(columns) >= 2 and columns[1] == "device":
            devices.append(columns[0])
    return devices


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start MuMu Player instances and launch Cookie Run on each one.",
    )
    parser.add_argument(
        "--package",
        default=DEFAULT_PACKAGE,
        help=f"Android package to launch. Defaults to {DEFAULT_PACKAGE}.",
    )
    parser.add_argument(
        "--manager",
        help="Path to MuMuManager.exe. Also honors MUMU_MANAGER_PATH.",
    )
    parser.add_argument(
        "--instances",
        type=parse_instance_list,
        help="MuMu instance indexes to launch, e.g. 0,1,2 or 0-5. Defaults to probing indexes.",
    )
    parser.add_argument(
        "--max-instances",
        type=int,
        help="Deprecated; ignored. Instances are read from MuMu's vms directory.",
    )
    parser.add_argument(
        "--boot-timeout",
        type=float,
        default=120.0,
        help="Seconds to wait for each launched MuMu instance to finish Android boot.",
    )
    parser.add_argument(
        "--no-start-players",
        action="store_true",
        help="Do not start MuMu instances; only launch the app through currently connected ADB devices.",
    )
    parser.add_argument(
        "--adb",
        help="ADB path for --no-start-players mode. Also honors ADB_PATH.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing them.",
    )
    parser.add_argument(
        "--no-arrange",
        action="store_true",
        help="Do not arrange launched MuMu windows into a desktop grid.",
    )
    parser.add_argument(
        "--grid",
        type=parse_grid,
        metavar="COLUMNSxROWS",
        help="Window grid dimensions, e.g. 3x1. Defaults to an automatic grid.",
    )
    parser.add_argument(
        "--friend-farm",
        action="store_true",
        help="After launch, tap the friend-farm login/play/pause/quit sequence.",
    )
    parser.add_argument(
        "--tap-timeout",
        type=float,
        default=60.0,
        help="Seconds to wait for each friend-farm image. Defaults to 60.",
    )
    args = parser.parse_args()
    if args.no_arrange and args.grid is not None:
        parser.error("--grid cannot be used with --no-arrange")
    if args.tap_timeout <= 0:
        parser.error("--tap-timeout must be greater than zero")
    return args


def launch_via_mumu_manager(args: argparse.Namespace, manager: Path) -> int:
    adb_path = find_mumu_adb(manager, args.adb)
    if adb_path is None:
        print("ADB was not found. Set ADB_PATH or pass --adb.")
        return 1

    instances = args.instances
    if instances is None:
        instances = configured_instances(manager)

    if not instances:
        print("No MuMu instances found under the install's vms directory.")
        return 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(instances)) as executor:
        launch_results = list(executor.map(
            lambda instance: launch_one_mumu_instance(
                manager,
                adb_path,
                instance,
                args.package,
                args.boot_timeout,
                dry_run=args.dry_run,
            ),
            instances,
        ))

    if not all(launch_results):
        print(
            "At least one MuMu instance did not reach Cookie Run landscape "
            "readiness; skipping grid arrangement and automation."
        )
        return 1

    arrange_succeeded = (
        True
        if args.no_arrange
        else arrange_mumu_windows(manager, args.grid, dry_run=args.dry_run)
    )

    automation_succeeded = True
    if args.friend_farm:
        ready_instances = [
            instance
            for instance, launched in zip(instances, launch_results)
            if launched
        ]
        serial_to_size: dict[str, tuple[int, int]] = {}
        for instance in ready_instances:
            serial = instance_adb_serial(manager, instance)
            device_size = instance_device_size(manager, instance)
            if serial is None or device_size is None:
                print(
                    f"MuMu instance {instance}: could not determine its "
                    "ADB serial or configured resolution."
                )
                automation_succeeded = False
                continue
            serial_to_size[serial] = device_size
            print(
                f"MuMu instance {instance} ({serial}) resolution: "
                f"{device_size[0]}x{device_size[1]}"
            )
        serials = list(serial_to_size)
        if serials:
            captures: dict[str, WindowCapture | None] = {}
            try:
                for serial in serials:
                    if args.dry_run:
                        captures[serial] = None
                        continue
                    hwnd = mumu_window_for_serial(serial)
                    if hwnd is None:
                        print(f"{serial}: could not find its MuMu window.")
                        automation_succeeded = False
                        continue
                    try:
                        captures[serial] = WindowCapture(
                            window_hwnd=hwnd,
                            device_size=VISION_REFERENCE_SIZE,
                        )
                        print(f"{serial}: WGC capture started for HWND {hwnd}")
                    except Exception as exc:
                        print(f"{serial}: could not start WGC capture: {exc}")
                        automation_succeeded = False

                captured_serials = [
                    serial for serial in serials if serial in captures
                ]
                if captured_serials:
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=len(captured_serials)
                    ) as executor:
                        automation_results = executor.map(
                            lambda serial: run_friend_farm_sequence(
                                adb_path,
                                serial,
                                captures[serial],
                                serial_to_size[serial],
                                args.tap_timeout,
                                dry_run=args.dry_run,
                            ),
                            captured_serials,
                        )
                        automation_succeeded = (
                            all(automation_results)
                            and automation_succeeded
                        )
            finally:
                for capture in captures.values():
                    if capture is not None:
                        capture.close()

    return (
        0
        if all(launch_results) and arrange_succeeded and automation_succeeded
        else 1
    )


def launch_via_adb(args: argparse.Namespace) -> int:
    adb_path = args.adb or os.environ.get("ADB_PATH") or shutil.which("adb")
    if adb_path is None:
        print("ADB was not found. Set ADB_PATH or pass --adb.")
        return 1

    devices = list_adb_devices(adb_path, dry_run=args.dry_run)
    if not devices and not args.dry_run:
        print("No connected ADB devices found.")
        return 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(devices)) as executor:
        results = executor.map(
            lambda serial: (
                print(f"ADB device {serial}") is None
                and launch_app_with_adb(adb_path, serial, args.package, dry_run=args.dry_run)
            ),
            devices,
        )

    return 1 if not all(results) else 0


def main() -> None:
    args = parse_args()

    if args.no_start_players:
        raise SystemExit(launch_via_adb(args))

    manager = find_mumu_manager(args.manager)
    if manager is None:
        print(
            "MuMuManager.exe was not found. Pass --manager, set MUMU_MANAGER_PATH, "
            "or use --no-start-players with ADB_PATH for already-running instances."
        )
        raise SystemExit(1)

    raise SystemExit(launch_via_mumu_manager(args, manager))


if __name__ == "__main__":
    main()
