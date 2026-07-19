"""Windows system tray icon: Open Dashboard / Quit.

Windows-only (imported from __main__.py behind a sys.platform check).
pystray/PIL are lazy imports so this module adds no hard dependency on
Linux, matching the heavy-import convention used in app.py.
"""

import os
import threading
import webbrowser


def start_tray(port: int, stop_cb):
    import pystray
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((8, 8, 56, 56), fill=(59, 130, 246, 255))

    def _open_dashboard(icon, item):
        webbrowser.open(f"http://127.0.0.1:{port}")

    def _quit(icon, item):
        icon.stop()
        stop_cb()
        # ponytail: stop_cb (listener.stop()) can in rare cases hang if the
        # pynput thread is wedged; force-exit shortly after as a ceiling.
        threading.Timer(2.0, lambda: os._exit(0)).start()

    icon = pystray.Icon(
        "omnihear", img, "Omnihear",
        menu=pystray.Menu(
            pystray.MenuItem("Open Dashboard", _open_dashboard),
            pystray.MenuItem("Quit", _quit),
        ),
    )
    if hasattr(icon, "run_detached"):
        icon.run_detached()
    else:
        threading.Thread(target=icon.run, daemon=True).start()
