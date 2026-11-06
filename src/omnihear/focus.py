"""Which app has keyboard focus -- for per-app styles and Insights' top apps.

Stdlib only, best-effort, never raises; returns a lowercase app name or
None when it can't tell:
- Windows: foreground window's process image name via ctypes ("slack").
- macOS: NSWorkspace frontmost application (pyobjc, already bundled).
- Linux X11: `xdotool getactivewindow getwindowclassname` ("firefox").
- Wayland: no portable API (GNOME has none at all), so None and the default
  style applies. XWayland's "active window" is wrong whenever a native
  Wayland window has focus, so xdotool is deliberately not used there.
"""

import os
import shutil
import subprocess
import sys


def supported() -> bool:
    if sys.platform in ("win32", "darwin"):
        return True
    from . import linux_session
    return (not linux_session.is_wayland() and bool(os.environ.get("DISPLAY"))
            and shutil.which("xdotool") is not None)


def _clean(name) -> str | None:
    name = (name or "").strip().lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name[:100] or None


def _windows() -> str | None:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return _clean(os.path.basename(buf.value))
    finally:
        kernel32.CloseHandle(handle)


def _macos() -> str | None:
    from AppKit import NSWorkspace
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return _clean(app.localizedName()) if app is not None else None


def _x11() -> str | None:
    out = subprocess.run(["xdotool", "getactivewindow", "getwindowclassname"],
                         capture_output=True, text=True, timeout=1)
    return _clean(out.stdout) if out.returncode == 0 else None


def active_app() -> str | None:
    try:
        if sys.platform == "win32":
            return _windows()
        if sys.platform == "darwin":
            return _macos()
        if supported():
            return _x11()
    except Exception:
        pass
    return None


if __name__ == "__main__":
    print(f"supported={supported()} active_app={active_app()!r}")
