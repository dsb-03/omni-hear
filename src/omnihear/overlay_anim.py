"""Shared animation model for the recording overlay.

Both renderers draw from this: the Tk overlay in app.py (Linux X11/XWayland,
Windows) and the AppKit panel in macos_overlay.py. It is pure stdlib math
with no GUI imports, so the platforms can't drift apart and it can be
exercised headless (`python -m omnihear.overlay_anim`).

Listening: a red dot with an expanding halo next to a mirrored waveform
driven by the live microphone level. The newest level sits in the centre
and ripples outward, so the bars visibly follow your voice. If no signal
at all arrives in the first 1.5 s (muted or wrong mic), it turns grey.

Transcribing: the dot becomes an amber spinner and the bars ease into a
smooth travelling wave with a highlight sweeping across. It reads as
"working", not "hearing".
"""

from __future__ import annotations

import math
import time
from collections import deque
from typing import NamedTuple

# Geometry (pixels in Tk, points on macOS). The pill's rounded ends are
# centred on the dot (left) and just past the last bar (right).
PILL_W, PILL_H = 126, 38
DOT_CX, DOT_R = 19.0, 4.5
SPINNER_R = 6.0
N_BARS = 13
BAR_W, BAR_GAP = 3.0, 3.0
BAR_MIN, BAR_MAX = 3.0, 24.0
BARS_X0 = 36.0            # left edge of the first bar
FRAME_MS = 33             # ~30 fps while visible

# Colours as 0..1 RGB.
BG = (0.067, 0.075, 0.094)      # #111318
EDGE = (0.20, 0.22, 0.27)
REC = (1.0, 0.294, 0.243)       # #ff4b3e
BUSY = (1.0, 0.69, 0.125)       # #ffb020
BAR = (0.93, 0.94, 0.96)
MUTED = (0.42, 0.45, 0.51)

NO_SIGNAL_RMS = 1e-4            # ~-80 dBFS: digital silence (muted source)
NO_SIGNAL_SECONDS = 1.5


class Dot(NamedTuple):
    color: tuple
    spinner: float | None   # clockwise degrees while transcribing, else None
    halo_r: float
    halo_alpha: float


class Frame(NamedTuple):
    bars: list              # bar heights in px, BAR_MIN..BAR_MAX
    colors: list            # per-bar RGB
    dot: Dot
    no_signal: bool


def mix(a: tuple, b: tuple, t: float) -> tuple:
    """Blend RGB a toward b by t (0 = a, 1 = b)."""
    t = min(1.0, max(0.0, t))
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def to_hex(rgb: tuple) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def bar_x(i: int) -> float:
    """Horizontal centre of bar i."""
    return BARS_X0 + i * (BAR_W + BAR_GAP) + BAR_W / 2


def level_from_rms(rms: float) -> float:
    """Map block RMS (float audio, 0..1) to a 0..1 display level on a dB
    scale: -50 dBFS (quiet room) -> 0, -18 dBFS (close, loud speech) -> 1.
    Normal speech into a laptop mic (-30..-22 dBFS) lands around 0.6-0.9."""
    if rms <= 1e-7:
        return 0.0
    db = 20.0 * math.log10(rms)
    return min(1.0, max(0.0, (db + 50.0) / 32.0))


class OverlayAnimation:
    """Call set_level() from the audio thread, set_mode() and frame() from
    the GUI thread. Shared fields are plain floats/bools, so cross-thread
    writes are atomic under the GIL."""

    def __init__(self):
        self.mode = "hidden"              # "listening" | "transcribing" | "hidden"
        self._rms = 0.0
        self._heard = False               # any real signal since listening began
        self._env = 0.0
        half = N_BARS // 2 + 1
        self._hist = deque([0.0] * half, maxlen=half)
        self._heights = [0.0] * N_BARS    # eased, 0..1
        self._mode_since = time.monotonic()

    def set_level(self, rms: float) -> None:
        self._rms = rms
        if rms > NO_SIGNAL_RMS:
            self._heard = True

    def set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        if mode == "listening":
            self._rms = 0.0
            self._heard = False
            self._env = 0.0
            self._hist.extend([0.0] * self._hist.maxlen)
        self.mode = mode
        self._mode_since = time.monotonic()

    def frame(self, now: float | None = None) -> Frame:
        now = time.monotonic() if now is None else now
        t = now - self._mode_since
        centre = N_BARS // 2
        targets = [0.0] * N_BARS
        no_signal = False

        if self.mode == "transcribing":
            # A highlight sweeps left to right over a gentle travelling wave.
            sweep = (t * 0.9) % 1.6 - 0.3
            colors = []
            for i in range(N_BARS):
                x = i / (N_BARS - 1)
                wave = 0.5 + 0.5 * math.sin(t * 5.0 - i * 0.62)
                glow = math.exp(-((x - sweep) / 0.16) ** 2)
                targets[i] = 0.14 + 0.22 * wave + 0.44 * glow
                colors.append(mix(BUSY, BG, 0.55 * (1.0 - glow)))
            dot = Dot(BUSY, (t * 400.0) % 360.0, 0.0, 0.0)
            ease = 0.25   # slower: bars morph from the voice shape into the wave
        else:
            # Fast attack, slow release, then ripple outward from the centre.
            level = level_from_rms(self._rms)
            if level > self._env:
                self._env = level
            else:
                self._env = self._env * 0.86 + level * 0.14
            self._hist.appendleft(self._env)
            no_signal = (not self._heard) and t > NO_SIGNAL_SECONDS
            for i in range(N_BARS):
                d = abs(i - centre)
                # Taller in the middle, plus per-bar movement so a steady
                # tone still looks alive rather than like a level meter.
                v = self._hist[d] * (1.0 - 0.085 * d)
                v *= 0.74 + 0.26 * math.sin(now * 11.0 + i * 1.9)
                idle = 0.06 + 0.05 * (0.5 + 0.5 * math.sin(now * 3.2 - d * 0.75))
                targets[i] = max(idle, v)
            colors = [MUTED if no_signal else BAR] * N_BARS
            phase = (t % 1.3) / 1.3
            dot = Dot(MUTED if no_signal else REC, None,
                      DOT_R + 1.0 + phase * 6.5, 0.45 * (1.0 - phase))
            ease = 0.5

        for i in range(N_BARS):
            self._heights[i] += (targets[i] - self._heights[i]) * ease
        bars = [BAR_MIN + h * (BAR_MAX - BAR_MIN) for h in self._heights]
        return Frame(bars, colors, dot, no_signal)


if __name__ == "__main__":
    a = OverlayAnimation()
    a.set_mode("listening")
    t0 = time.monotonic()
    quiet = a.frame(t0 + 0.1)
    assert all(BAR_MIN <= h < BAR_MIN + 4 for h in quiet.bars), "idle bars stay low"
    for k in range(10):
        a.set_level(0.08)                       # ~-22 dBFS speech
        loud = a.frame(t0 + 0.2 + k * 0.033)
    assert loud.bars[N_BARS // 2] > 11, "centre bar follows the voice"
    assert loud.bars[N_BARS // 2] > loud.bars[0], "level ripples outward from the centre"
    assert not loud.no_signal

    b = OverlayAnimation()
    b.set_mode("listening")
    muted = b.frame(time.monotonic() + NO_SIGNAL_SECONDS + 0.1)
    assert muted.no_signal and muted.colors[0] == MUTED, "never heard anything -> grey"

    a.set_mode("transcribing")
    busy = a.frame()
    assert busy.dot.spinner is not None and busy.dot.color == BUSY
    assert level_from_rms(0.0) == 0.0 and level_from_rms(1.0) == 1.0
    assert to_hex((1.0, 0.294, 0.243)) == "#ff4b3e"
    print("overlay_anim self-check OK")
