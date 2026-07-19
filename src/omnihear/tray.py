"""Windows system tray icon: Open Dashboard / Quit.

Windows-only (imported from __main__.py behind a sys.platform check).
pystray/PIL are lazy imports so this module adds no hard dependency on
Linux, matching the heavy-import convention used in app.py.
"""

import os
import subprocess
import sys
import threading
import webbrowser


def _open_dashboard_window(url):
    """Open the dashboard in a chromeless Edge app window; browser fallback."""
    for base in ("%ProgramFiles(x86)%", "%ProgramFiles%"):
        edge = os.path.expandvars(base + r"\Microsoft\Edge\Application\msedge.exe")
        if os.path.exists(edge):
            subprocess.Popen([edge, f"--app={url}"])
            return
    webbrowser.open(url)


def _icon_image():
    from PIL import Image, ImageDraw
    # Bundled .ico when frozen (PyInstaller --add-data), else draw one.
    ico = os.path.join(getattr(sys, "_MEIPASS", ""), "omnihear.ico")
    if os.path.exists(ico):
        return Image.open(ico)
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
    if hasattr(icon, "run_detached"):
        icon.run_detached()
    else:
        threading.Thread(target=icon.run, daemon=True).start()
