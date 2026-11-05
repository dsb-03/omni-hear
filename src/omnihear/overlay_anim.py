"""Shared animation model for the recording overlay.

Both renderers draw from this: the Tk overlay in app.py (Linux X11/XWayland,
Windows) and the AppKit panel in macos_overlay.py. It is pure stdlib math
with no GUI imports, so the platforms can't drift apart and it can be
exercised headless (`python -m omnihear.overlay_anim`).

Listening: a red dot with an expanding halo next to a mirrored waveform
driven by the live microphone level. The newest level sits in the centre
and ripples outward, so the bars visibly follow your voice. If no signal
at all arrives in the first 1.5 s (muted or wrong mic), it turns grey.

Locked (hands-free, recording continues without holding the key): the
listening dot becomes a small rounded "stop" square, halo still pulsing,
so it reads as "tap to stop".

Transcribing: the dot becomes an amber spinner and the bars ease into a
smooth travelling wave with a highlight sweeping across. It reads as
"working", not "hearing".

Size, colours, shapes and screen position are user-configurable (the
overlay_* config keys). `Style` turns those into concrete geometry in
pixels (points on macOS) and `place()` picks the window position, so both
renderers lay the pill out identically. The module constants below are the
look at scale 1 and stay the defaults.
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
# Locked: rounded stop square (half side, corner radius). A bit larger than
# the dot so it still reads as a square on Tk's aliased 1x canvas.
STOP_HALF, STOP_CORNER = 5.0, 2.0
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

# Window placement presets (overlay_position) and shapes. config.py mirrors
# these for validation and the dashboard.
POSITIONS = ("bottom_center", "bottom_left", "bottom_right",
             "top_center", "top_left", "top_right", "center")
SHAPES = ("pill", "rounded", "square")          # container
BAR_SHAPES = ("rounded", "square")              # individual waveform bars
# Distance from the screen edge for each preset, before the user's offset.
# Bottom sits just above a typical taskbar/dock: near where you look while
# typing.
MARGIN_BOTTOM, MARGIN_TOP, MARGIN_SIDE = 90, 48, 24

NO_SIGNAL_RMS = 1e-4            # ~-80 dBFS: digital silence (muted source)
NO_SIGNAL_SECONDS = 1.5


class Dot(NamedTuple):
    color: tuple
    spinner: float | None   # clockwise degrees while transcribing, else None
    halo_r: float
    halo_alpha: float
    stop: bool = False      # locked: draw a rounded stop square, not a dot


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


def parse_hex(value, default: tuple) -> tuple:
    """'#rrggbb' -> 0..1 RGB, or default if it isn't a valid colour."""
    v = str(value or "").strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    try:
        if len(v) != 6:
            raise ValueError
        return tuple(int(v[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return default


def _clamp(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    if v != v:          # NaN
        return default
    return min(hi, max(lo, v))


class Style:
    """Concrete overlay look from the overlay_* config keys (missing or bad
    values fall back to the defaults). All geometry is already multiplied by
    `scale`, in pixels (Tk) / points (macOS), with y running down from the
    pill's top edge.

    Layout at scale 1: the dot sits in the left end, bars start 17 px after
    it, and the pill is just tall enough for the tallest bar.
    """

    def __init__(self, cfg: dict | None = None):
        c = cfg or {}
        s = self.scale = _clamp(c.get("overlay_scale", 1.0), 0.5, 4.0, 1.0)
        self.n_bars = int(_clamp(c.get("overlay_bar_count", N_BARS), 3, 41, N_BARS))
        bw = _clamp(c.get("overlay_bar_width", BAR_W), 1.0, 16.0, BAR_W)
        gap = _clamp(c.get("overlay_bar_gap", BAR_GAP), 0.0, 16.0, BAR_GAP)
        bmax = _clamp(c.get("overlay_bar_height", BAR_MAX), 8.0, 96.0, BAR_MAX)
        shape = c.get("overlay_shape", "pill")
        self.shape = shape if shape in SHAPES else "pill"
        self.round_bars = c.get("overlay_bar_shape", "rounded") != "square"
        self.opacity = _clamp(c.get("overlay_opacity", 0.94), 0.2, 1.0, 0.94)
        self.bg = parse_hex(c.get("overlay_bg_color"), BG)
        self.bar = parse_hex(c.get("overlay_bar_color"), BAR)
        self.rec = parse_hex(c.get("overlay_dot_color"), REC)
        self.busy, self.muted = BUSY, MUTED
        # A subtle outline a little lighter than the background (Windows).
        self.edge = mix(self.bg, (1.0, 1.0, 1.0), 0.14)

        h = max(float(PILL_H), bmax + 14.0)
        left = h / 2 if self.shape == "pill" else DOT_CX
        bars_x0 = left + (BARS_X0 - DOT_CX)
        right = max(15.0, h / 2 - 4.0) if self.shape == "pill" else 15.0
        w = bars_x0 + self.n_bars * (bw + gap) - gap + right
        radius = {"pill": h / 2, "rounded": min(10.0, h / 2), "square": 0.0}[self.shape]

        self.width = max(1, round(w * s))
        self.height = max(1, round(h * s))
        self.radius = radius * s
        self.dot_cx = left * s
        self.cy = self.height / 2
        self.dot_r = DOT_R * s
        self.stop_half, self.stop_corner = STOP_HALF * s, STOP_CORNER * s
        self.spinner_r = SPINNER_R * s
        self.line_w = 2.0 * s                   # spinner stroke
        self.halo_grow = 6.5 * s
        self.bar_w, self.bar_gap = bw * s, gap * s
        self.bars_x0 = bars_x0 * s
        self.bar_max = bmax * s
        # Rounded bars bottom out as a circle; square ones as a short stub.
        self.bar_min = min(self.bar_w if self.round_bars else 2.0 * s,
                           self.bar_max / 2)

    def bar_x(self, i: int) -> float:
        """Horizontal centre of bar i."""
        return self.bars_x0 + i * (self.bar_w + self.bar_gap) + self.bar_w / 2


def place(style: Style, cfg: dict | None, screen_w: float, screen_h: float):
    """Top-left (x, y) of the overlay on a screen_w x screen_h area, y down,
    from overlay_position plus the overlay_offset_x/_y nudge (positive y =
    down). Clamped so the pill always stays fully on screen."""
    c = cfg or {}
    pos = c.get("overlay_position", "bottom_center")
    if pos not in POSITIONS:
        pos = "bottom_center"
    w, h = style.width, style.height
    if pos.endswith("_left"):
        x = MARGIN_SIDE
    elif pos.endswith("_right"):
        x = screen_w - w - MARGIN_SIDE
    else:
        x = (screen_w - w) / 2
    if pos.startswith("top"):
        y = MARGIN_TOP
    elif pos.startswith("bottom"):
        y = screen_h - h - MARGIN_BOTTOM
    else:
        y = (screen_h - h) / 2
    x += _clamp(c.get("overlay_offset_x", 0), -10000, 10000, 0)
    y += _clamp(c.get("overlay_offset_y", 0), -10000, 10000, 0)
    x = min(max(0, x), max(0, screen_w - w))
    y = min(max(0, y), max(0, screen_h - h))
    return int(x), int(y)


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
    the GUI thread; `locked` may be set from any thread. Shared fields are
    plain floats/bools, so cross-thread writes are atomic under the GIL."""

    def __init__(self, style: Style | None = None):
        self.style = st = style or Style()
        self.mode = "hidden"              # "listening" | "transcribing" | "hidden"
        self.locked = False               # hands-free lock: dot -> stop square
        self._rms = 0.0
        self._heard = False               # any real signal since listening began
        self._env = 0.0
        half = st.n_bars // 2 + 1
        self._hist = deque([0.0] * half, maxlen=half)
        self._heights = [0.0] * st.n_bars    # eased, 0..1
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
        st = self.style
        n = st.n_bars
        centre = n // 2
        # Spread the wave/falloff over however many bars there are, so a
        # different bar count keeps the same overall shape.
        k = (N_BARS - 1) / max(1, n - 1)
        targets = [0.0] * n
        no_signal = False

        if self.mode == "transcribing":
            # A highlight sweeps left to right over a gentle travelling wave.
            sweep = (t * 0.9) % 1.6 - 0.3
            colors = []
            for i in range(n):
                x = i / (n - 1)
                wave = 0.5 + 0.5 * math.sin(t * 5.0 - i * k * 0.62)
                glow = math.exp(-((x - sweep) / 0.16) ** 2)
                targets[i] = 0.14 + 0.22 * wave + 0.44 * glow
                colors.append(mix(st.busy, st.bg, 0.55 * (1.0 - glow)))
            dot = Dot(st.busy, (t * 400.0) % 360.0, 0.0, 0.0)
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
            for i in range(n):
                d = abs(i - centre)
                # Taller in the middle, plus per-bar movement so a steady
                # tone still looks alive rather than like a level meter.
                v = self._hist[d] * max(0.0, 1.0 - 0.085 * d * k)
                v *= 0.74 + 0.26 * math.sin(now * 11.0 + i * 1.9)
                idle = 0.06 + 0.05 * (0.5 + 0.5 * math.sin(now * 3.2 - d * k * 0.75))
                targets[i] = max(idle, v)
            colors = [st.muted if no_signal else st.bar] * n
            phase = (t % 1.3) / 1.3
            # The halo grows from just outside the dot, or the stop square's
            # rounded corners when locked.
            extent = ((st.stop_half - st.stop_corner) * math.sqrt(2)
                      + st.stop_corner if self.locked else st.dot_r)
            dot = Dot(st.muted if no_signal else st.rec, None,
                      extent + st.scale + phase * st.halo_grow,
                      0.45 * (1.0 - phase), self.locked)
            ease = 0.5

        for i in range(n):
            self._heights[i] += (targets[i] - self._heights[i]) * ease
        bars = [st.bar_min + h * (st.bar_max - st.bar_min) for h in self._heights]
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

    assert not loud.dot.stop, "unlocked listening draws the round dot"
    a.locked = True                             # hands-free lock
    lk1 = a.frame(t0 + 0.6)
    lk2 = a.frame(t0 + 1.1)
    assert lk1.dot.stop and lk1.dot.spinner is None and lk1.dot.color == REC, \
        "locked: red stop square"
    assert lk1.dot.halo_alpha > 0 and lk1.dot.halo_r != lk2.dot.halo_r, \
        "locked: halo keeps pulsing"
    smallest = a.frame(a._mode_since + 2.61).dot      # start of a pulse
    assert smallest.halo_r > STOP_HALF * math.sqrt(2), "halo starts outside the square"
    b.locked = True
    grey = b.frame(time.monotonic() + NO_SIGNAL_SECONDS + 0.2).dot
    assert grey.stop and grey.color == MUTED, "locked + no signal -> grey square"

    a.set_mode("transcribing")
    busy = a.frame()
    assert busy.dot.spinner is not None and busy.dot.color == BUSY
    assert not busy.dot.stop, "only the listening dot turns into a stop square"
    assert level_from_rms(0.0) == 0.0 and level_from_rms(1.0) == 1.0
    assert to_hex((1.0, 0.294, 0.243)) == "#ff4b3e"

    # Customised style: bigger, more bars, square container and bars.
    cfg = {"overlay_scale": 2.0, "overlay_bar_count": 21, "overlay_shape": "square",
           "overlay_bar_shape": "square", "overlay_bar_color": "#00ff00",
           "overlay_bg_color": "zzz", "overlay_bar_height": 40}
    big = Style(cfg)
    assert big.n_bars == 21 and big.radius == 0 and not big.round_bars
    assert big.bar == (0.0, 1.0, 0.0) and big.bg == BG, "bad colour -> default"
    assert big.height == round((40 + 14) * 2) and big.bar_max == 80
    assert big.bar_x(20) + big.bar_w / 2 < big.width, "last bar inside the pill"
    c = OverlayAnimation(big)
    c.set_mode("listening")
    fr = c.frame()
    assert len(fr.bars) == 21 and all(big.bar_min <= h <= big.bar_max for h in fr.bars)
    c.set_mode("transcribing")
    assert len(c.frame().bars) == 21

    d = Style()
    assert (d.width, d.height) == (PILL_W, PILL_H) and d.bar_x(0) == bar_x(0), \
        "scale 1 defaults keep the original geometry"
    assert Style({"overlay_scale": "nope", "overlay_bar_count": 99}).n_bars == 41
    assert place(d, {}, 1920, 1080) == ((1920 - PILL_W) // 2, 1080 - PILL_H - MARGIN_BOTTOM)
    assert place(d, {"overlay_position": "top_right"}, 1920, 1080) == \
        (1920 - PILL_W - MARGIN_SIDE, MARGIN_TOP)
    assert place(d, {"overlay_position": "top_left", "overlay_offset_x": -500}, 1920, 1080)[0] == 0, \
        "offsets can't push it off screen"
    assert parse_hex("#FFF", BG) == (1.0, 1.0, 1.0) and parse_hex(None, BG) == BG
    print("overlay_anim self-check OK")
