"""Best-effort desktop/audio feedback: notify-send and paplay beep.

Everything here fails silently if the tools are missing or error out.
"""

import subprocess
import sys

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
        if sys.platform == "win32":
            return  # ponytail: no-op on Windows, add toast via winrt if requested
        if len(body) > 120:
            body = body[:117] + "..."
        if sys.platform == "darwin":
            # osascript's `display notification` string is an AppleScript
            # literal — escape backslashes and double quotes.
            def _esc(s):
                return s.replace("\\", "\\\\").replace('"', '\\"')
            self._run(
                ["osascript", "-e",
                 f'display notification "{_esc(body)}" with title "{_esc(title)}"']
            )
            return
        self._run(
            ["notify-send", "--app-name=omnihear", f"--urgency={urgency}",
             "--expire-time=3000", title, body]
        )

    def beep(self):
        if not self.beep_enabled:
            return
        if sys.platform == "win32":
            try:
                import winsound
                winsound.MessageBeep()
            except Exception:
                pass
            return
        import os
        if sys.platform == "darwin":
            ping = "/System/Library/Sounds/Ping.aiff"
            if os.path.exists(ping):
                self._run(["afplay", ping])
            else:
                self._run(["osascript", "-e", "beep"])
            return
        import shutil
        player = None
        # aplay is ALSA-only and can't decode Ogg Vorbis (_BEEP_SOUNDS are
        # .oga) -- it "succeeds" while playing the file as raw PCM noise.
        for p in ["pw-play", "paplay"]:
            if shutil.which(p):
                player = p
                break
        if not player:
            return
        for sound in _BEEP_SOUNDS:
            if os.path.exists(sound):
                self._run([player, sound])
                return
