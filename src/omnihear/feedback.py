"""Best-effort desktop/audio feedback: notify-send and paplay beep.

Everything here fails silently if the tools are missing or error out.
"""

import subprocess

_BEEP_SOUNDS = [
    "/usr/share/sounds/freedesktop/stereo/message.oga",
    "/usr/share/sounds/freedesktop/stereo/bell.oga",
]


class Feedback:
    def __init__(self, notify_enabled: bool = True, beep_enabled: bool = False):
        self.notify_enabled = notify_enabled
        self.beep_enabled = beep_enabled

    def _run(self, cmd):
        try:
            subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except (OSError, ValueError):
            pass

    def notify(self, title: str, body: str = "", urgency: str = "low"):
        if not self.notify_enabled:
            return
        if len(body) > 120:
            body = body[:117] + "..."
        self._run(
            ["notify-send", "--app-name=omnihear", f"--urgency={urgency}",
             "--expire-time=3000", title, body]
        )

    def beep(self):
        if not self.beep_enabled:
            return
        import shutil
        import os
        player = None
        for p in ["pw-play", "paplay", "aplay"]:
            if shutil.which(p):
                player = p
                break
        if not player:
            return
        for sound in _BEEP_SOUNDS:
            if os.path.exists(sound):
                self._run([player, sound])
                return
