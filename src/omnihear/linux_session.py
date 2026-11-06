"""Linux session detection + Wayland text injection.

Hotkeys on Wayland live in evdev_hotkey.py. Typing prefers omnihear's own
stdlib /dev/uinput keyboard (uinput_keyboard.py — works on GNOME, KDE and
wlroots, no daemon), then shells out to ydotool (any compositor, needs
ydotoold) or wtype (wlroots/Hyprland only), matching how X11 already
shells out to xdotool — no new pip deps.
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


def desktop() -> str:
    """Lower-cased XDG_CURRENT_DESKTOP, e.g. 'ubuntu:gnome', 'kde'."""
    return (os.environ.get("XDG_CURRENT_DESKTOP") or "").strip().lower()


def is_gnome() -> bool:
    d = desktop()
    return "gnome" in d or "unity" in d


def wtype_supported() -> bool:
    """wtype needs zwp_virtual_keyboard_v1, which GNOME (Mutter) and KDE
    (KWin) don't offer to regular clients — it errors out there."""
    d = desktop()
    return not (is_gnome() or "kde" in d or "plasma" in d)


def has_ibus_unicode_entry() -> bool:
    """Ctrl+Shift+U unicode entry is available (IBus, GNOME's default)."""
    if is_gnome():
        return True
    return any((os.environ.get(v) or "").lower() == "ibus"
               for v in ("GTK_IM_MODULE", "QT_IM_MODULE", "XMODIFIERS"))


def uinput_available() -> bool:
    from . import uinput_keyboard
    return uinput_keyboard.available()


def wayland_type_available() -> list[str]:
    """Working Wayland typers for this desktop, preferred order."""
    found = []
    if uinput_available():
        found.append("uinput")
    if shutil.which("ydotool"):
        found.append("ydotool")
    if shutil.which("wtype") and wtype_supported():
        found.append("wtype")
    return found


def resolve_type_method(configured: str) -> str:
    """Map config type_method to the backend that will actually run.

    'auto' picks a working backend for the session. On Wayland, bare
    'pynput' is remapped because pynput cannot inject into Wayland-native
    clients (it talks to X11 / XWayland only). 'paste' resolves like
    'auto': that backend sends its paste shortcut (and types when the
    clipboard is unavailable).
    """
    method = (configured or "auto").strip().lower()
    if sys.platform in ("win32", "darwin"):
        return "pynput"
    if method == "paste":
        method = "auto"
    if method == "auto" or (is_wayland() and method in ("pynput", "xdotool")):
        if is_wayland():
            avail = wayland_type_available()
            # Prefer a working typer; fall back to 'uinput' so
            # missing_wayland_deps() can print the /dev/uinput setup hint.
            return avail[0] if avail else "uinput"
        return "pynput"
    return method


def type_text(method: str, text: str) -> None:
    if method == "uinput":
        from . import uinput_keyboard
        uinput_keyboard.default_keyboard().type(text)
    elif method == "xdotool":
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
    if method == "uinput":
        from . import uinput_keyboard
        uinput_keyboard.default_keyboard().backspace(n)
    elif method == "xdotool":
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


def paste_chord(method: str) -> bool:
    """Press Shift+Insert, the paste key for type_method = "paste": GTK, Qt,
    Chromium and Firefox paste CLIPBOARD on it, terminals PRIMARY
    (clipboard.set_text sets both). True if it was sent."""
    if method == "uinput":
        from . import uinput_keyboard
        try:
            uinput_keyboard.default_keyboard().paste_chord()
        except OSError:
            return False
        return True
    if method == "xdotool":
        argv = ["xdotool", "key", "--clearmodifiers", "shift+Insert"]
    elif method == "ydotool":
        # KEY_LEFTSHIFT = 42, KEY_INSERT = 110; :1 press, :0 release.
        argv = ["ydotool", "key", "42:1", "110:1", "110:0", "42:0"]
    elif method == "wtype":
        # wtype uploads a fresh keymap each run; XWayland apps can drop a
        # key press sent before they've applied it, so pause first.
        argv = ["wtype", "-M", "shift", "-s", "50", "-k", "Insert",
                "-m", "shift"]
    else:
        raise ValueError(f"unknown type method for Linux inject: {method}")
    try:
        return subprocess.run(argv, check=False, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def copy_chord(method: str) -> bool:
    """Press Ctrl+Insert, which copies the selection to CLIPBOARD in GTK,
    Qt, Chromium, Firefox and VTE terminals alike (Ctrl+C would interrupt
    a terminal). Used by Command Mode. True if it was sent."""
    if method == "uinput":
        from . import uinput_keyboard
        try:
            uinput_keyboard.default_keyboard().copy_chord()
        except OSError:
            return False
        return True
    if method == "xdotool":
        argv = ["xdotool", "key", "--clearmodifiers", "ctrl+Insert"]
    elif method == "ydotool":
        # KEY_LEFTCTRL = 29, KEY_INSERT = 110; :1 press, :0 release.
        argv = ["ydotool", "key", "29:1", "110:1", "110:0", "29:0"]
    elif method == "wtype":
        argv = ["wtype", "-M", "ctrl", "-s", "50", "-k", "Insert",
                "-m", "ctrl"]
    else:
        raise ValueError(f"unknown type method for Linux inject: {method}")
    try:
        return subprocess.run(argv, check=False, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def in_input_group_pending() -> bool:
    """User is listed in the `input` group but this process predates it
    (group changes only apply after logging out and back in)."""
    try:
        import grp
        import pwd
        user = pwd.getpwuid(os.getuid()).pw_name
        gid = grp.getgrnam("input").gr_gid
        listed = user in grp.getgrnam("input").gr_mem
    except (KeyError, ImportError, OSError):
        return False
    return listed and gid not in os.getgroups()


def _ydotool_socket_present() -> bool:
    candidates = [os.environ.get("YDOTOOL_SOCKET") or ""]
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        candidates.append(os.path.join(runtime, ".ydotool_socket"))
    candidates.append("/tmp/.ydotool_socket")
    return any(c and os.path.exists(c) for c in candidates)


def missing_wayland_deps(type_method: str) -> list[str]:
    """Human-readable setup hints when Wayland prerequisites are missing."""
    hints = []
    if not is_wayland():
        return hints
    from . import evdev_hotkey
    if not evdev_hotkey.keyboard_devices():
        if in_input_group_pending():
            hints.append(
                "you were added to the `input` group but this login predates "
                "it — log out and back in so hotkeys can read your keyboard")
        else:
            hints.append(
                "hotkeys need read access to /dev/input/event* — "
                "run `sudo usermod -aG input $USER` then log out and back in")
    resolved = resolve_type_method(type_method)
    if resolved == "uinput" and not uinput_available():
        hints.append(
            "text injection needs write access to /dev/uinput — the omnihear "
            ".deb installs a udev rule for this; if you run from source: "
            "`sudo cp udev/70-omnihear-uinput.rules /usr/lib/udev/rules.d/ && "
            "sudo modprobe uinput && sudo udevadm trigger --sysname-match=uinput`"
            " (or install ydotool)")
    elif resolved in ("ydotool", "wtype") and not shutil.which(resolved):
        hints.append(
            f"text injection needs `{resolved}` — `sudo apt install {resolved}`"
            " (or set type_method = \"auto\" to use omnihear's built-in "
            "uinput typer)")
    if resolved == "wtype" and not wtype_supported():
        hints.append(
            "wtype does not work on GNOME/KDE (no virtual-keyboard protocol) — "
            "set type_method = \"auto\" or \"uinput\"")
    if (resolved == "ydotool" and shutil.which("ydotool")
            and not _ydotool_socket_present()):
        hints.append(
            "ydotool needs its daemon running "
            "(`systemctl --user enable --now ydotool` or `ydotoold &`) — "
            "or use type_method = \"uinput\", which needs no daemon")
    return hints
