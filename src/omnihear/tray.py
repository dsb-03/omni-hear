"""System tray / menu-bar icon: Open Dashboard / Quit.

Used on Windows (imported from __main__.py behind a sys.platform check) and
macOS. pystray/PIL are lazy imports so this module adds no hard dependency on
Linux, matching the heavy-import convention used in app.py.

Threading note: on Windows the icon runs detached (or on a daemon thread) and
app.run() keeps the main thread. On macOS, AppKit requires the icon to own the
*main* thread, so start_tray() blocks there and __main__.py runs app.run() on a
background thread instead.
"""

import os
import subprocess
import sys
import threading
import webbrowser


def _open_dashboard_window(url):
    """Open the dashboard. Chromeless Edge app window on Windows; the default
    browser everywhere else."""
    if sys.platform == "win32":
        for base in ("%ProgramFiles(x86)%", "%ProgramFiles%"):
            edge = os.path.expandvars(base + r"\Microsoft\Edge\Application\msedge.exe")
            if os.path.exists(edge):
                subprocess.Popen([edge, f"--app={url}"])
                return
    webbrowser.open(url)


def _icon_image():
    from PIL import Image, ImageDraw
    # Bundled icon when frozen (PyInstaller --add-data): .ico on Windows,
    # .png on macOS. Fall back to a drawn blue dot.
    meipass = getattr(sys, "_MEIPASS", "")
    for name in ("omnihear.png", "omnihear.ico"):
        path = os.path.join(meipass, name)
        if meipass and os.path.exists(path):
            return Image.open(path)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((8, 8, 56, 56), fill=(59, 130, 246, 255))
    return img


def start_tray(port: int, stop_cb):
    import pystray

    def _open_dashboard(icon, item):
        _open_dashboard_window(f"http://127.0.0.1:{port}")

    def _quit(icon, item):
        icon.stop()
        stop_cb()
        # ponytail: stop_cb (listener.stop()) can in rare cases hang if the
        # pynput thread is wedged; force-exit shortly after as a ceiling.
        threading.Timer(2.0, lambda: os._exit(0)).start()

    icon = pystray.Icon(
        "omnihear", _icon_image(), "Omnihear",
        menu=pystray.Menu(
            pystray.MenuItem("Open Dashboard", _open_dashboard, default=True),
            pystray.MenuItem("Quit", _quit),
        ),
    )
    if sys.platform == "darwin":
        # AppKit demands the run loop own the main thread — block here.
        # __main__.py runs app.run() on a background thread on macOS.
        icon.run()
    elif hasattr(icon, "run_detached"):
        icon.run_detached()
    else:
        threading.Thread(target=icon.run, daemon=True).start()
