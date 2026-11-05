"""Clipboard text for type_method = "paste" (beta). Stdlib only.

app.py's paste path saves the clipboard, puts the dictation there, sends
the paste shortcut through the key backend, then restores the old text.
This module is only the clipboard part, and it is best-effort everywhere:
failures return None/False, they never raise.

- Linux shells out to the usual tools, like the rest of omnihear: xclip or
  xsel on X11, wl-copy/wl-paste (wl-clipboard) on Wayland. GNOME is the
  exception: Mutter has no (wlr/ext) data-control protocol, so wl-copy and
  wl-paste fall back to a focus-stealing popup surface there, while X11
  selections set through XWayland are bridged to Wayland apps; so on GNOME
  xclip/xsel win when DISPLAY is set. PRIMARY is set along with CLIPBOARD:
  the Linux paste key is Shift+Insert, which pastes CLIPBOARD in GTK, Qt,
  Chromium and Firefox but PRIMARY in VTE terminals (GNOME Terminal,
  Ptyxis), xterm, Konsole, kitty, foot and Alacritty.
  The setters fork a background process that serves the selection, so
  they run with stdout/stderr on DEVNULL: a captured pipe would make
  subprocess.run wait for that child.
- macOS: pbcopy/pbpaste under a UTF-8 locale (an app started from Finder
  has none, and they garble non-ASCII without one).
- Windows: the Win32 clipboard (CF_UNICODETEXT) through ctypes.

Only text is handled: get_text() returns None for an empty (with some
tools), non-text or unreachable clipboard; there is nothing to restore then.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

CLIPBOARD, PRIMARY = "clipboard", "primary"

# Seconds a clipboard tool (and the app owning the selection, which has to
# answer a read) gets before it counts as unavailable.
_TIMEOUT = 2.0

# Linux tool -> description for backend() / --doctor.
_LINUX_TOOLS = {"xclip": "xclip", "xsel": "xsel",
                "wl-clipboard": "wl-copy/wl-paste"}


# -- Linux ---------------------------------------------------------------

def _pick_linux_tool(session: str, gnome: bool, display: bool,
                     have) -> str | None:
    """The clipboard tool to use on Linux, or None.

    session: linux_session.session_type(); gnome: linux_session.is_gnome();
    display: DISPLAY is set (X11, or XWayland under a Wayland session);
    have(cmd): cmd is installed.
    """
    x11 = [t for t in ("xclip", "xsel") if display and have(t)]
    wl = (["wl-clipboard"] if session == "wayland"
          and have("wl-copy") and have("wl-paste") else [])
    if session != "wayland":
        order = x11
    elif gnome:
        order = x11 + wl
    else:
        order = wl + x11
    return order[0] if order else None


def _linux_tool() -> str | None:
    from . import linux_session
    return _pick_linux_tool(linux_session.session_type(),
                            linux_session.is_gnome(),
                            bool(os.environ.get("DISPLAY")),
                            lambda cmd: shutil.which(cmd) is not None)


def _set_argv(tool: str, selection: str) -> list[str]:
    if tool == "xclip":
        return ["xclip", "-selection", selection, "-in"]
    if tool == "xsel":
        return ["xsel", f"--{selection}", "--input"]
    # An explicit type: wl-copy would otherwise sniff the content, and
    # dictation that looks like HTML would be offered as text/html only.
    argv = ["wl-copy", "--type", "text/plain;charset=utf-8"]
    return argv + ["--primary"] if selection == PRIMARY else argv


def _get_argv(tool: str, selection: str) -> list[str]:
    if tool == "xclip":
        return ["xclip", "-selection", selection, "-out",
                "-target", "UTF8_STRING"]
    if tool == "xsel":
        return ["xsel", f"--{selection}", "--output"]
    # "text" makes wl-paste pick whichever text type is offered (and fail on
    # images); --no-newline stops it appending "\n".
    argv = ["wl-paste", "--no-newline", "--type", "text"]
    return argv + ["--primary"] if selection == PRIMARY else argv


def _as_text(data: bytes) -> str | None:
    # An xclip that holds an image answers a text request with the raw
    # image bytes; real text is valid UTF-8 without NULs.
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return None if "\0" in text else text


def _read(argv: list[str], env: dict | None = None) -> str | None:
    try:
        r = subprocess.run(argv, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=_TIMEOUT, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return _as_text(r.stdout) if r.returncode == 0 else None


def _write(argv: list[str], text: str, env: dict | None = None) -> bool:
    try:
        r = subprocess.run(argv, input=text.encode("utf-8"),
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           timeout=_TIMEOUT, env=env)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return False
    return r.returncode == 0


# -- macOS ---------------------------------------------------------------

def _mac_env() -> dict:
    env = dict(os.environ)
    env["LANG"] = env["LC_ALL"] = "en_US.UTF-8"
    return env


# -- Windows -------------------------------------------------------------

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
_win = None


def _win_api():
    """(ctypes, user32, kernel32) with explicit prototypes: handles are
    pointer-sized c_void_p, so nothing is truncated on 64-bit. Private
    WinDLL instances, so these prototypes can't clash with other ctypes
    users of windll.user32 (pynput, pystray)."""
    global _win
    if _win is None:
        import ctypes
        from ctypes import wintypes as w
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        for fn, restype, argtypes in (
            (user32.OpenClipboard, w.BOOL, [w.HWND]),
            (user32.CloseClipboard, w.BOOL, []),
            (user32.EmptyClipboard, w.BOOL, []),
            (user32.IsClipboardFormatAvailable, w.BOOL, [w.UINT]),
            (user32.GetClipboardData, w.HANDLE, [w.UINT]),
            (user32.SetClipboardData, w.HANDLE, [w.UINT, w.HANDLE]),
            (user32.RegisterClipboardFormatW, w.UINT, [w.LPCWSTR]),
            (user32.CreateWindowExW, w.HWND,
             [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int,
              ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU,
              w.HINSTANCE, w.LPVOID]),
            (user32.DestroyWindow, w.BOOL, [w.HWND]),
            (kernel32.GlobalAlloc, w.HGLOBAL, [w.UINT, ctypes.c_size_t]),
            (kernel32.GlobalFree, w.HGLOBAL, [w.HGLOBAL]),
            (kernel32.GlobalLock, w.LPVOID, [w.HGLOBAL]),
            (kernel32.GlobalUnlock, w.BOOL, [w.HGLOBAL]),
            (kernel32.GlobalSize, ctypes.c_size_t, [w.HGLOBAL]),
        ):
            fn.restype, fn.argtypes = restype, argtypes
        _win = (ctypes, user32, kernel32)
    return _win


def _win_encode(text: str) -> bytes:
    """CF_UNICODETEXT payload: CRLF line ends, UTF-16LE, NUL-terminated."""
    text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    return text.encode("utf-16-le", "surrogatepass") + b"\0\0"


def _win_decode(raw: bytes) -> str:
    """Inverse of _win_encode. The memory block can be longer than the
    string (allocations round up), so stop at the first NUL."""
    text = raw[:len(raw) & ~1].decode("utf-16-le", "surrogatepass")
    return text.split("\0", 1)[0].replace("\r\n", "\n")


def _win_open(user32, hwnd) -> bool:
    # Other programs (clipboard history, the app that just pasted) hold
    # the clipboard open for brief moments.
    for _ in range(20):
        if user32.OpenClipboard(hwnd):
            return True
        time.sleep(0.01)
    return False


def _win_alloc(ctypes, kernel32, data: bytes):
    """A GMEM_MOVEABLE block (what SetClipboardData requires) holding data,
    or None."""
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h:
        return None
    p = kernel32.GlobalLock(h)
    if not p:
        kernel32.GlobalFree(h)
        return None
    ctypes.memmove(p, data, len(data))
    kernel32.GlobalUnlock(h)
    return h


def _win_keep_local(ctypes, user32, kernel32) -> None:
    """Keep omnihear's short-lived clipboard text out of Win+V history and
    cloud clipboard sync (DWORD 0 in these registered formats)."""
    zero = (0).to_bytes(4, "little")
    for name in ("CanIncludeInClipboardHistory", "CanUploadToCloudClipboard"):
        fmt = user32.RegisterClipboardFormatW(name)
        h = _win_alloc(ctypes, kernel32, zero) if fmt else None
        if h is not None and not user32.SetClipboardData(fmt, h):
            kernel32.GlobalFree(h)


def _win_set(text: str) -> bool:
    ctypes, user32, kernel32 = _win_api()
    data = _win_encode(text)
    # Own the clipboard through a hidden window: after OpenClipboard(NULL),
    # EmptyClipboard leaves the clipboard without an owner and
    # SetClipboardData is documented to fail.
    hwnd = user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0,
                                  None, None, None, None)
    try:
        if not _win_open(user32, hwnd):
            return False
        try:
            if not user32.EmptyClipboard():
                return False
            h = _win_alloc(ctypes, kernel32, data)
            if h is None:
                return False
            if not user32.SetClipboardData(CF_UNICODETEXT, h):
                kernel32.GlobalFree(h)  # only the system's once set
                return False
            try:
                _win_keep_local(ctypes, user32, kernel32)
            except Exception:
                pass
            return True
        finally:
            user32.CloseClipboard()
    finally:
        if hwnd:
            user32.DestroyWindow(hwnd)


def _win_get() -> str | None:
    ctypes, user32, kernel32 = _win_api()
    if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return None
    if not _win_open(user32, None):
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)  # owned by the clipboard
        p = kernel32.GlobalLock(h) if h else None
        if not p:
            return None
        try:
            size = kernel32.GlobalSize(h)
            raw = ctypes.string_at(p, size) if size else None
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()
    return None if raw is None else _win_decode(raw)


# -- public API ----------------------------------------------------------

def backend() -> str | None:
    """What paste uses for the clipboard (for --doctor), or None."""
    if sys.platform == "win32":
        return "Win32 clipboard"
    if sys.platform == "darwin":
        found = shutil.which("pbcopy") and shutil.which("pbpaste")
        return "pbcopy/pbpaste" if found else None
    tool = _linux_tool()
    if tool is None:
        return None
    from . import linux_session
    if tool != "wl-clipboard" and linux_session.is_wayland():
        return f"{tool} (via XWayland)"
    return _LINUX_TOOLS[tool]


def get_text(primary: bool = False) -> str | None:
    """The clipboard's text, or with primary=True the Linux PRIMARY
    selection (None elsewhere). None when empty (with some tools), not
    text, or unreachable."""
    try:
        if sys.platform == "win32":
            return None if primary else _win_get()
        if sys.platform == "darwin":
            return None if primary else _read(["pbpaste"], env=_mac_env())
        tool = _linux_tool()
        if tool is None:
            return None
        return _read(_get_argv(tool, PRIMARY if primary else CLIPBOARD))
    except Exception:
        return None


def set_text(text: str, primary: bool = True) -> bool:
    """Put text on the clipboard and, on Linux unless primary=False, on the
    PRIMARY selection too (best-effort). True if the clipboard was set."""
    try:
        if sys.platform == "win32":
            return _win_set(text)
        if sys.platform == "darwin":
            return _write(["pbcopy"], text, env=_mac_env())
        tool = _linux_tool()
        if tool is None or not _write(_set_argv(tool, CLIPBOARD), text):
            return False
        if primary:
            _write(_set_argv(tool, PRIMARY), text)
        return True
    except Exception:
        return False


def set_primary(text: str) -> bool:
    """Linux: set only the PRIMARY selection. False elsewhere."""
    if sys.platform in ("win32", "darwin"):
        return False
    try:
        tool = _linux_tool()
        return tool is not None and _write(_set_argv(tool, PRIMARY), text)
    except Exception:
        return False


if __name__ == "__main__":
    def have(*cmds):
        return lambda c: c in cmds

    everything = have("xclip", "xsel", "wl-copy", "wl-paste")
    pick = _pick_linux_tool
    # X11: xclip, then xsel; wl-clipboard can't work without a compositor.
    assert pick("x11", False, True, everything) == "xclip"
    assert pick("x11", True, True, have("xsel", "wl-copy", "wl-paste")) == "xsel"
    assert pick("x11", False, True, have("wl-copy", "wl-paste")) is None
    assert pick("x11", False, False, everything) is None
    # GNOME Wayland: the X11 tools through XWayland when DISPLAY is set...
    assert pick("wayland", True, True, everything) == "xclip"
    assert pick("wayland", True, True, have("xsel", "wl-copy", "wl-paste")) == "xsel"
    # ... else wl-clipboard (works, but steals focus briefly).
    assert pick("wayland", True, False, everything) == "wl-clipboard"
    assert pick("wayland", True, True, have("wl-copy", "wl-paste")) == "wl-clipboard"
    # KDE / wlroots: wl-clipboard (data-control), then the X11 tools.
    assert pick("wayland", False, True, everything) == "wl-clipboard"
    assert pick("wayland", False, True, have("xsel")) == "xsel"
    assert pick("wayland", False, False, have("xclip")) is None
    assert pick("wayland", False, True, have("wl-copy")) is None  # needs both
    assert pick("unknown", False, False, everything) is None

    assert _set_argv("xclip", PRIMARY) == ["xclip", "-selection", "primary", "-in"]
    assert _set_argv("xsel", CLIPBOARD) == ["xsel", "--clipboard", "--input"]
    assert _set_argv("wl-clipboard", PRIMARY)[-1] == "--primary"
    assert "--primary" not in _set_argv("wl-clipboard", CLIPBOARD)
    assert _get_argv("xclip", CLIPBOARD)[-2:] == ["-target", "UTF8_STRING"]
    assert _get_argv("xsel", PRIMARY) == ["xsel", "--primary", "--output"]
    assert _get_argv("wl-clipboard", CLIPBOARD) == [
        "wl-paste", "--no-newline", "--type", "text"]

    assert _as_text(b"") == ""
    assert _as_text("héllo ✓\n".encode()) == "héllo ✓\n"
    assert _as_text(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR") is None
    assert _as_text(b"a\0b") is None

    for s in ("", "plain", "a\nb\n\nc", "a\r\nb", "é ✓ \U0001F600"):
        assert _win_decode(_win_encode(s)) == s.replace("\r\n", "\n"), s
    assert _win_encode("a\nb") == "a\r\nb\0".encode("utf-16-le")
    assert _win_encode("a\r\nb") == _win_encode("a\nb")
    assert _win_decode("hi\0junk".encode("utf-16-le") + b"\x01") == "hi"
    assert _win_decode(b"") == ""
    print("clipboard self-check OK")
