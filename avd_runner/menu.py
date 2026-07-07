from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Protocol

from .captcha import solve_captcha
from .device import AvdDevice, wait
from .vision import find_template


class MenuContext(Protocol):
    device: AvdDevice
    capture: Any
    captcha_enabled: bool
    debug_view: Any | None
    debug_run_dir: Path | None
    debug_tap_count: int


def take_screenshot(ctx: MenuContext):
    """Menu-phase screenshot from the session WGC capture."""
    return ctx.capture.grab()


def debug_show(ctx: MenuContext, screen, boxes=()) -> None:
    """Draw the live debug window for a menu frame (no-op unless enabled)."""
    if ctx.debug_view is None:
        return
    ctx.debug_view.update(screen, boxes)


def match_box(match, label: str):
    """A green DebugView box list for a TemplateMatch, or empty if no match."""
    if match is None:
        return []
    return [(match.x, match.y, match.x + match.width, match.y + match.height, label, (0, 255, 0))]


def debug_save_tap(ctx: MenuContext, name: str, screen, x: int, y: int) -> None:
    """Save the frame a tap was decided on, with a red dot at the tap point."""
    if ctx.debug_run_dir is None:
        return
    import cv2

    frame = screen.copy()
    cv2.circle(frame, (x, y), 12, (0, 0, 255), -1)
    cv2.putText(frame, f"{x}, {y}", (x + 18, y + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    ctx.debug_tap_count += 1
    slug = name.lower().replace(" ", "_")
    ctx.debug_run_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(ctx.debug_run_dir / f"{ctx.debug_tap_count:02d}_{slug}.png"), frame)


def solve_captcha_if_present(
    ctx: MenuContext,
    screen,
    banner_template: str | Path,
) -> bool:
    """Solve the anti-bot captcha if the given screenshot shows it."""
    if not ctx.captcha_enabled:
        return False
    if find_template(screen, banner_template, threshold=0.9) is None:
        return False

    print("Anti-bot captcha detected; solving.")
    if not solve_captcha(
        ctx.device,
        ctx.capture,
        banner_template=banner_template,
        on_tap=(lambda name, frame, x, y: debug_save_tap(ctx, name, frame, x, y))
        if ctx.debug_run_dir is not None
        else None,
    ):
        print("Failed to solve captcha.")
        raise SystemExit(1)
    return True


def wait_template_gone(
    ctx: MenuContext,
    template_path: Path,
    threshold: float,
    banner_template: str | Path,
    timeout: float = 5.0,
    poll_seconds: float = 0.2,
) -> bool:
    """Poll until the template is no longer on screen. False on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if find_template(take_screenshot(ctx), template_path, threshold=threshold) is None:
            return True
        wait(poll_seconds)
    return False


def tap_template(
    ctx: MenuContext,
    name: str,
    template_path: Path,
    banner_template: str | Path,
    threshold: float = 0.85,
    attempts: int = 5,
    delay_seconds: float = 0.5,
    save_debug: bool = False,
    verify_gone: bool = False,
) -> bool:
    """Find and tap a template."""
    attempt = 0
    while attempt < attempts:
        screen = take_screenshot(ctx)
        match = find_template(screen, template_path, threshold=threshold)
        debug_show(ctx, screen, match_box(match, name))

        if match:
            wait(0.12)
            confirm = take_screenshot(ctx)
            if solve_captcha_if_present(ctx, confirm, banner_template):
                continue
            again = find_template(confirm, template_path, threshold=threshold)
            if (
                again is None
                or abs(again.center_x - match.center_x) > 3
                or abs(again.center_y - match.center_y) > 3
            ):
                attempt += 1
                print(f"{name} still animating on attempt {attempt}/{attempts}")
                wait(0.2)
                continue
            tx, ty = ctx.device.tap(match.center_x, match.center_y, label=name)
            debug_save_tap(ctx, name, confirm, tx, ty)
            if ctx.debug_view is not None:
                debug_show(ctx, confirm, match_box(match, name))
            print(
                f"Tapped {name} at {tx}, {ty} (target {match.center_x}, {match.center_y}) "
                f"score={match.score:.3f}"
            )
            if not verify_gone:
                return True
            if wait_template_gone(ctx, template_path, threshold, banner_template):
                return True
            attempt += 1
            print(f"{name} still on screen after tapping ({attempt}/{attempts}); retapping")
            continue

        if solve_captcha_if_present(ctx, screen, banner_template):
            continue

        attempt += 1
        print(f"{name} not found on attempt {attempt}/{attempts}")
        wait(delay_seconds)

    if save_debug:
        debug_path = Path("screenshots") / f"{template_path.stem}_not_found.png"
        import cv2

        debug_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(debug_path), take_screenshot(ctx))
        print(f"Saved {debug_path}")
    return False


def wait_for_template(
    ctx: MenuContext,
    name: str,
    template_path: Path,
    banner_template: str | Path,
    threshold: float = 0.85,
    attempts: int = 120,
    delay_seconds: float = 1.0,
) -> bool:
    attempt = 0
    while attempt < attempts:
        screen = take_screenshot(ctx)
        match = find_template(screen, template_path, threshold=threshold)
        debug_show(ctx, screen, match_box(match, name))
        if match:
            print(f"Found {name} score={match.score:.3f}")
            return True

        if solve_captcha_if_present(ctx, screen, banner_template):
            continue

        attempt += 1
        print(f"{name} not found on attempt {attempt}/{attempts}")
        wait(delay_seconds)

    return False


def wait_for_any_template(
    ctx: MenuContext,
    targets: list[tuple[str, Path]],
    banner_template: str | Path,
    threshold: float = 0.85,
    attempts: int = 120,
    delay_seconds: float = 0.5,
) -> str | None:
    """Poll until any of the (name, template) targets is on screen."""
    attempt = 0
    while attempt < attempts:
        screen = take_screenshot(ctx)
        for name, template_path in targets:
            match = find_template(screen, template_path, threshold=threshold)
            if match is not None:
                debug_show(ctx, screen, match_box(match, name))
                print(f"Found {name}")
                return name
        debug_show(ctx, screen)
        if solve_captcha_if_present(ctx, screen, banner_template):
            continue
        attempt += 1
        wait(delay_seconds)
    return None


def is_toggle_selected(
    ctx: MenuContext,
    name: str,
    selected_template: Path,
    unselected_template: Path,
    banner_template: str | Path,
    ready: float = 0.85,
    attempts: int = 25,
    delay_seconds: float = 0.2,
) -> bool:
    """Wait for a toggle to appear, then report if it is in the selected state."""
    for attempt in range(attempts):
        screen = take_screenshot(ctx)
        if solve_captcha_if_present(ctx, screen, banner_template):
            continue
        sel = find_template(screen, selected_template, threshold=-1.0)
        unsel = find_template(screen, unselected_template, threshold=-1.0)
        debug_show(ctx, screen, match_box(sel, name))
        sel_score = sel.score if sel else 0.0
        unsel_score = unsel.score if unsel else 0.0
        if max(sel_score, unsel_score) >= ready:
            print(f"{name}: selected={sel_score:.3f} unselected={unsel_score:.3f}")
            return sel_score > unsel_score
        wait(delay_seconds)
    print(f"{name}: toggle never appeared; treating as not selected")
    return False
