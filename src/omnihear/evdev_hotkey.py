"""Stdlib push-to-talk hotkeys via Linux evdev (/dev/input/event*).

Used on Wayland where pynput cannot receive global key events. Requires
the user to be able to open keyboard devices (typically: membership in
the `input` group). No pip dependency — reads the kernel input_event
struct directly.
"""

from __future__ import annotations

import os
import select
import struct
import threading
import time
from pathlib import Path

# linux/input.h: struct input_event { timeval(2*long); u16 type; u16 code; s32 value; }
_EVENT_FMT = "llHHi"
_EVENT_SIZE = struct.calcsize(_EVENT_FMT)
EV_KEY = 0x01
KEY_UP = 0
KEY_DOWN = 1
# value==2 (hold/repeat) ignored — press already recorded

# Canonical omnihear names -> linux KEY_* codes (input-event-codes.h).
_SPECIAL_CODES = {
    "ctrl_l": 29, "ctrl_r": 97,
    "alt_l": 56, "alt_r": 100,
    "shift_l": 42, "shift_r": 54,
    "cmd_l": 125, "cmd_r": 126,  # KEY_LEFTMETA / KEY_RIGHTMETA
    "caps_lock": 58, "space": 57,
    "pause": 119, "scroll_lock": 70,
    **{f"f{i}": 58 + i for i in range(1, 11)},  # F1=59 .. F10=68
    "f11": 87, "f12": 88,
}

# US QWERTY keymap: character -> (KEY_* code, needs shift). Shared with
# uinput_keyboard.py, which types through the same table.
KEY_LEFTSHIFT = 42
_UNSHIFTED = {
    **dict(zip("abcdefghijklmnopqrstuvwxyz",
               [30, 48, 46, 32, 18, 33, 34, 35, 23, 36, 37, 38, 50,
                49, 24, 25, 16, 19, 31, 20, 22, 47, 17, 45, 21, 44])),
    **dict(zip("1234567890", [2, 3, 4, 5, 6, 7, 8, 9, 10, 11])),
    "`": 41, "-": 12, "=": 13, "[": 26, "]": 27, "\\": 43,
    ";": 39, "'": 40, ",": 51, ".": 52, "/": 53,
    " ": 57, "\t": 15, "\n": 28,
}
_SHIFTED = {
    **{c.upper(): _UNSHIFTED[c] for c in "abcdefghijklmnopqrstuvwxyz"},
    "~": 41, "!": 2, "@": 3, "#": 4, "$": 5, "%": 6, "^": 7, "&": 8,
    "*": 9, "(": 10, ")": 11, "_": 12, "+": 13, "{": 26, "}": 27,
    "|": 43, ":": 39, '"': 40, "<": 51, ">": 52, "?": 53,
}
US_KEYMAP: dict[str, tuple[int, bool]] = {
    **{c: (code, False) for c, code in _UNSHIFTED.items()},
    **{c: (code, True) for c, code in _SHIFTED.items()},
}

# Single-character hotkeys: unshifted printable keys only ('+' is the
# combo separator, whitespace has a named key).
_CHAR_CODES = {c: code for c, code in _UNSHIFTED.items()
               if c not in " \t\n"}

# Virtual keyboards that inject text (ours and ydotool's). Their events
# must never be read back as hotkey presses: typing "Hello" through them
# presses Shift, which would trigger a shift_l hotkey.
VIRTUAL_DEVICE_NAMES = ("omnihear virtual keyboard", "ydotoold virtual device")

# How often to rescan for keyboards plugged in (or paired) after start.
_RESCAN_SECONDS = 3.0


def name_to_code(name: str) -> int:
    name = name.strip().lower()
    if name in _SPECIAL_CODES:
        return _SPECIAL_CODES[name]
    if len(name) == 1 and name in _CHAR_CODES:
        return _CHAR_CODES[name]
    raise ValueError(f"Unsupported Wayland hotkey part: {name!r}")


def parse_hotkey_codes(name: str) -> frozenset[int]:
    parts = [p for p in name.strip().lower().split("+") if p]
    if not parts:
        raise ValueError("Empty hotkey.")
    return frozenset(name_to_code(p) for p in parts)


def keyboard_devices() -> list[Path]:
    """Return readable /dev/input/eventN paths tagged as keyboards.

    Parses /proc/bus/input/devices (Handlers=... kbd ... eventN). Skips
    the virtual keyboards text injection uses (see VIRTUAL_DEVICE_NAMES).
    """
    found: list[Path] = []
    for path, _name in _keyboard_entries():
        if _readable(path):
            found.append(path)
    return found


def keyboard_device_count() -> int:
    """Physical keyboards present, readable or not (for setup hints)."""
    return len(_keyboard_entries())


def _keyboard_entries() -> list[tuple[Path, str]]:
    try:
        text = Path("/proc/bus/input/devices").read_text()
    except OSError:
        return []
    entries: list[tuple[Path, str]] = []
    for block in text.split("\n\n"):
        handlers = ""
        name = ""
        for line in block.splitlines():
            if line.startswith("H: Handlers="):
                handlers = line[len("H: Handlers="):]
            elif line.startswith("N: Name="):
                name = line[len("N: Name="):].strip().strip('"')
        if "kbd" not in handlers.split():
            continue
        if name.lower() in VIRTUAL_DEVICE_NAMES:
            continue
        for token in handlers.split():
            if token.startswith("event"):
                entries.append((Path("/dev/input") / token, name))
                break
    return entries


def _readable(path: Path) -> bool:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        os.close(fd)
        return True
    except OSError:
        return False


class HotkeyMonitor:
    """Listen for combo press/release on all readable keyboard devices."""

    def __init__(self, combo: frozenset[int],
                 on_dictate_start, on_stop,
                 ask_combo: frozenset[int] | None = None,
                 on_ask_start=None):
        self.combo = combo
        self.ask_combo = ask_combo
        self.on_dictate_start = on_dictate_start
        self.on_ask_start = on_ask_start
        self.on_stop = on_stop
        self._stop = threading.Event()
        self._thread = None
        self._watched = combo | (ask_combo or frozenset())

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="evdev-hotkey",
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def join(self):
        if self._thread is not None:
            self._thread.join()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        self.join()

    def _open_new(self, fds: dict[int, Path]) -> None:
        """Open keyboards not yet watched (startup + hotplug rescans)."""
        watched = set(fds.values())
        for p in keyboard_devices():
            if p in watched:
                continue
            try:
                fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = p
            except OSError:
                continue

    def _drop(self, fds: dict[int, Path], fd: int, pressed: set[int]) -> None:
        """Forget an unplugged device; release anything it was holding."""
        fds.pop(fd, None)
        try:
            os.close(fd)
        except OSError:
            pass
        if pressed:
            pressed.clear()
            self.on_stop()

    def _loop(self):
        fds: dict[int, Path] = {}
        pressed: set[int] = set()
        next_scan = 0.0
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if now >= next_scan:
                    self._open_new(fds)
                    next_scan = now + _RESCAN_SECONDS
                if not fds:
                    self._stop.wait(_RESCAN_SECONDS)
                    continue
                readable, _, _ = select.select(list(fds), [], [], 0.5)
                for fd in readable:
                    while True:
                        try:
                            raw = os.read(fd, _EVENT_SIZE)
                        except BlockingIOError:
                            break
                        except OSError:
                            # ENODEV: keyboard unplugged / BT disconnected.
                            self._drop(fds, fd, pressed)
                            break
                        if len(raw) < _EVENT_SIZE:
                            break
                        _, _, etype, code, value = struct.unpack(_EVENT_FMT, raw)
                        if etype != EV_KEY or code not in self._watched:
                            continue
                        if value == KEY_DOWN:
                            pressed.add(code)
                            if pressed == self.combo:
                                self.on_dictate_start()
                            elif (self.ask_combo is not None
                                  and pressed == self.ask_combo
                                  and self.on_ask_start is not None):
                                self.on_ask_start()
                        elif value == KEY_UP:
                            if code in pressed:
                                pressed.discard(code)
                                self.on_stop()
        finally:
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
