"""Stdlib virtual keyboard via /dev/uinput \u2014 Wayland text injection with
no daemon and no pip/apt dependency.

GNOME (Mutter) and KDE (KWin) don't implement the virtual-keyboard
protocol wtype needs, and ydotool needs a root-ish daemon plus its own
setup. Writing key events to /dev/uinput works on every compositor (the
kernel hands them to libinput like a real keyboard). The .deb ships a
udev rule tagging /dev/uinput `uaccess`, so the logged-in desktop user can
open it — the same rule Steam ships for controllers.

Limits (documented in README / ROADMAP):
- Keys go through the active XKB layout; the table is US QWERTY, so
  non-US layouts get wrong characters for some keys.
- Non-ASCII text is entered through IBus's Ctrl+Shift+U unicode entry
  (GNOME's default input method); elsewhere those characters are skipped.
"""

from __future__ import annotations

import fcntl
import os
import struct
import threading
import time
import unicodedata

from .evdev_hotkey import KEY_LEFTSHIFT, US_KEYMAP, VIRTUAL_DEVICE_NAMES

DEVICE_PATH = "/dev/uinput"
DEVICE_NAME = VIRTUAL_DEVICE_NAMES[0]

# linux/uinput.h ioctls: _IOW('U', nr, size) = 1<<30 | size<<16 | 'U'<<8 | nr
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_DEV_SETUP = 0x405C5503      # _IOW('U', 3, struct uinput_setup) — 92 bytes
UI_SET_EVBIT = 0x40045564      # _IOW('U', 100, int)
UI_SET_KEYBIT = 0x40045565     # _IOW('U', 101, int)
_SETUP_FMT = "HHHH80sI"        # input_id{bustype,vendor,product,version}, name, ff_max
BUS_USB = 0x03

_EVENT_FMT = "llHHi"
EV_SYN, EV_KEY = 0x00, 0x01
SYN_REPORT = 0

KEY_LEFTCTRL = 29
KEY_BACKSPACE = 14
KEY_U = 22
_HEX_CODES = {c: US_KEYMAP[c][0] for c in "0123456789abcdef"}

# Typographic characters Whisper sometimes emits, mapped to ASCII so they
# go through the keymap instead of the slower unicode-entry path. One
# char -> one char, so voice "undo" (which backspaces len(text)) stays exact.
_ASCII_FOLD = {
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-",
    "\u00a0": " ", "\u202f": " ", "\u2009": " ",
}

# Seconds between events. Mutter/KWin drop keys sent back-to-back with no
# gap; ydotool uses ~12 ms per key, this is a bit quicker.
_KEY_DELAY = 0.004
# After UI_DEV_CREATE the compositor needs a moment to pick up the new
# device; events sent before that are silently lost.
_SETTLE_SECONDS = 0.35


def available() -> bool:
    """True if /dev/uinput exists and this process may write to it."""
    return os.path.exists(DEVICE_PATH) and os.access(DEVICE_PATH, os.W_OK)


def fold(text: str) -> str:
    """Normalize to NFC and replace typographic punctuation with ASCII."""
    text = unicodedata.normalize("NFC", text)
    return "".join(_ASCII_FOLD.get(ch, ch) for ch in text)


class VirtualKeyboard:
    """One lazily created uinput device, reused for the process lifetime."""

    def __init__(self, unicode_entry: bool = True):
        self._fd: int | None = None
        self._lock = threading.Lock()
        self.unicode_entry = unicode_entry
        self.skipped = 0  # chars that could not be typed (non-ASCII, no IBus)

    # -- device lifecycle -------------------------------------------
    def _ensure(self) -> int:
        if self._fd is not None:
            return self._fd
        fd = os.open(DEVICE_PATH, os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
            codes = {code for code, _ in US_KEYMAP.values()}
            codes |= {KEY_LEFTSHIFT, KEY_LEFTCTRL, KEY_BACKSPACE, KEY_U}
            for code in sorted(codes):
                fcntl.ioctl(fd, UI_SET_KEYBIT, code)
            setup = struct.pack(_SETUP_FMT, BUS_USB, 0x1209, 0x0A11, 1,
                                DEVICE_NAME.encode(), 0)
            fcntl.ioctl(fd, UI_DEV_SETUP, setup)
            fcntl.ioctl(fd, UI_DEV_CREATE)
        except OSError:
            os.close(fd)
            raise
        self._fd = fd
        time.sleep(_SETTLE_SECONDS)
        return fd

    def close(self) -> None:
        with self._lock:
            if self._fd is None:
                return
            try:
                fcntl.ioctl(self._fd, UI_DEV_DESTROY)
            except OSError:
                pass
            os.close(self._fd)
            self._fd = None

    # -- low-level events --------------------------------------------
    def _emit(self, fd: int, code: int, value: int) -> None:
        os.write(fd, struct.pack(_EVENT_FMT, 0, 0, EV_KEY, code, value))
        os.write(fd, struct.pack(_EVENT_FMT, 0, 0, EV_SYN, SYN_REPORT, 0))
        time.sleep(_KEY_DELAY)

    def _tap(self, fd: int, code: int, *mods: int) -> None:
        for m in mods:
            self._emit(fd, m, 1)
        self._emit(fd, code, 1)
        self._emit(fd, code, 0)
        for m in reversed(mods):
            self._emit(fd, m, 0)

    def _unicode(self, fd: int, ch: str) -> bool:
        """IBus unicode entry: Ctrl+Shift+U, hex code point, Space."""
        if not self.unicode_entry:
            return False
        self._tap(fd, KEY_U, KEY_LEFTCTRL, KEY_LEFTSHIFT)
        for digit in format(ord(ch), "x"):
            self._tap(fd, _HEX_CODES[digit])
        self._tap(fd, US_KEYMAP[" "][0])
        return True

    # -- public API ------------------------------------------------------
    def type(self, text: str) -> None:
        with self._lock:
            fd = self._ensure()
            for ch in fold(text):
                key = US_KEYMAP.get(ch)
                if key is not None:
                    code, shift = key
                    if shift:
                        self._tap(fd, code, KEY_LEFTSHIFT)
                    else:
                        self._tap(fd, code)
                elif ch.isprintable() and self._unicode(fd, ch):
                    pass
                else:
                    self.skipped += 1

    def backspace(self, n: int) -> None:
        if n <= 0:
            return
        with self._lock:
            fd = self._ensure()
            for _ in range(n):
                self._tap(fd, KEY_BACKSPACE)


_default: VirtualKeyboard | None = None
_default_lock = threading.Lock()


def default_keyboard() -> VirtualKeyboard:
    global _default
    with _default_lock:
        if _default is None:
            from . import linux_session
            _default = VirtualKeyboard(
                unicode_entry=linux_session.has_ibus_unicode_entry())
        return _default
