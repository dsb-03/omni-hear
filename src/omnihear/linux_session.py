"""Linux session detection + Wayland text injection.

Hotkeys on Wayland live in evdev_hotkey.py. Typing shells out to
ydotool (any compositor, via uinput) or wtype (wlroots compositors),
matching how X11 already shells out to xdotool — no new pip deps.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def session_type() -> str:
    """Return 'wayland', 'x11', or 'unknown' for the current Linux session."""
    if sys.platform in ("win32", "darwin"):
        return "unknown"
    explicit = (os.environ.get("XDG_SESSION_TYPE") or "").strip().lower()
    if explicit in ("wayland", "x11"):
        return explicit
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def is_wayland() -> bool:
    return session_type() == "wayland"


def wayland_type_available() -> list[str]:
    """Installed Wayland typers, preferred order."""
    found = []
    for cmd in ("ydotool", "wtype"):
        if shutil.which(cmd):
            found.append(cmd)
    return found


def resolve_type_method(configured: str) -> str:
    """Map config type_method to the backend that will actually run.

    'auto' picks a working backend for the session. On Wayland, bare
    'pynput' is remapped because pynput cannot inject into Wayland-native
    clients (it talks to X11 / XWayland only).
    """
    method = (configured or "auto").strip().lower()
    if sys.platform in ("win32", "darwin"):
        return "pynput"
    if method == "auto" or (is_wayland() and method in ("pynput", "xdotool")):
        if is_wayland():
            avail = wayland_type_available()
            # Prefer an installed typer; fall back to the name 'ydotool' so
            # missing_wayland_deps() can print a clear apt install hint.
            return avail[0] if avail else "ydotool"
        return "pynput"
    return method


def type_text(method: str, text: str) -> None:
    if method == "xdotool":
        subprocess.run(["xdotool", "type", "--clearmodifiers", "--", text],
                       check=False)
    elif method == "ydotool":
        # ydotool reads the string as args; -- ends options for safety.
        subprocess.run(["ydotool", "type", "--", text], check=False)
    elif method == "wtype":
        subprocess.run(["wtype", "--", text], check=False)
    else:
        raise ValueError(f"unknown type method for Linux inject: {method}")


def backspace(method: str, n: int) -> None:
    if n <= 0:
        return
    if method == "xdotool":
        subprocess.run(["xdotool", "key", "--repeat", str(n), "BackSpace"],
                       check=False)
    elif method == "ydotool":
        # KEY_BACKSPACE = 14; :1 press, :0 release. --repeat is supported
        # by ydotool >= 1.0.
        subprocess.run(
            ["ydotool", "key", "--repeat", str(n), "--repeat-delay", "5",
             "14:1", "14:0"],
            check=False)
    elif method == "wtype":
        for _ in range(n):
            subprocess.run(["wtype", "-k", "backspace"], check=False)
    else:
        raise ValueError(f"unknown type method for Linux inject: {method}")


def missing_wayland_deps(type_method: str) -> list[str]:
    """Human-readable setup hints when Wayland prerequisites are missing."""
    hints = []
    if not is_wayland():
        return hints
    from . import evdev_hotkey
    if not evdev_hotkey.keyboard_devices():
        hints.append(
            "hotkeys need read access to /dev/input/event* — "
            "run `sudo usermod -aG input $USER` then log out and back in")
    resolved = resolve_type_method(type_method)
    if resolved in ("ydotool", "wtype") and not shutil.which(resolved):
        hints.append(
            f"text injection needs `{resolved}` "
            f"(or the other of ydotool/wtype) — "
            f"`sudo apt install ydotool` (any compositor) "
            f"or `sudo apt install wtype` (wlroots: sway/hyprland)")
        if resolved == "ydotool":
            hints.append(
                "ydotool also needs its daemon: "
                "`systemctl --user enable --now ydotoold` "
                "(or run `ydotoold` in the background)")
    return hints
