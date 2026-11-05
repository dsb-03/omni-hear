"""Native macOS recording/transcribing indicator (AppKit floating panel).

macOS can't use the Tkinter overlay (Cocoa GUI must run on the main thread,
which the pystray menu-bar icon owns). Instead this draws a borderless,
click-through, non-activating NSPanel bottom-centre of the screen, so it
never steals keyboard focus from the field being typed into.

It draws the same animation as the Tk overlay, from the shared model in
overlay_anim.py: while listening, a red dot with a pulsing halo next to a
waveform that follows the live mic level (a rounded stop square instead of
the dot while hands-free recording is locked); while transcribing, an amber
spinner and a flowing wave.

State changes arrive from the recorder/worker threads and are marshalled
onto the main thread (which the pystray NSApplication run loop services) via
performSelectorOnMainThread_. A ~30 fps NSTimer redraws only while the panel
is visible. set_level() is called from the audio thread and touches only the
pure-Python model, never AppKit. pyobjc is already a dependency on macOS.

Public interface mirrors the Tk RecordingOverlay: show(),
show_transcribing(), hide(), set_level(), set_locked().
"""

import objc
from Foundation import NSObject, NSMakeRect, NSMakePoint, NSTimer
from AppKit import (
    NSPanel, NSColor, NSView, NSScreen, NSBezierPath,
    NSBackingStoreBuffered, NSScreenSaverWindowLevel,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
)

from . import overlay_anim as oa

# Not all of these constants are exported by every pyobjc version.
NSWindowStyleMaskBorderless = 0
NSWindowStyleMaskNonactivatingPanel = 1 << 7
NSLineCapStyleRound = 1

_W, _H = float(oa.PILL_W), float(oa.PILL_H)


def _ns(rgb, alpha=1.0):
    r, g, b = rgb
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, alpha)


class OmnihearPillView(NSView):
    """Draws one overlay_anim.Frame: set .frame_state, then setNeedsDisplay_."""

    def initWithFrame_(self, rect):
        self = objc.super(OmnihearPillView, self).initWithFrame_(rect)
        if self is None:
            return None
        self.frame_state = None
        return self

    def drawRect_(self, rect):
        cy = _H / 2.0
        _ns(oa.BG, 0.94).setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(0, 0, _W, _H), cy, cy).fill()
        fr = self.frame_state
        if fr is None:
            return

        cx = oa.DOT_CX
        d = fr.dot
        if d.spinner is None:
            if d.halo_alpha > 0.01:
                r = d.halo_r
                _ns(d.color, d.halo_alpha).setFill()
                NSBezierPath.bezierPathWithOvalInRect_(
                    NSMakeRect(cx - r, cy - r, 2 * r, 2 * r)).fill()
            _ns(d.color).setFill()
            if d.stop:   # hands-free locked: rounded "stop" square
                s, c = oa.STOP_HALF, oa.STOP_CORNER
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    NSMakeRect(cx - s, cy - s, 2 * s, 2 * s), c, c).fill()
            else:
                r = oa.DOT_R
                NSBezierPath.bezierPathWithOvalInRect_(
                    NSMakeRect(cx - r, cy - r, 2 * r, 2 * r)).fill()
        else:
            sr = oa.SPINNER_R
            track = NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(cx - sr, cy - sr, 2 * sr, 2 * sr))
            track.setLineWidth_(2.0)
            _ns(d.color, 0.25).setStroke()
            track.stroke()
            # The model's angle runs clockwise; AppKit's run counter-clockwise.
            start = -d.spinner
            arc = NSBezierPath.bezierPath()
            arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                NSMakePoint(cx, cy), sr, start, start + 110.0, False)
            arc.setLineWidth_(2.0)
            arc.setLineCapStyle_(NSLineCapStyleRound)
            _ns(d.color).setStroke()
            arc.stroke()

        rad = oa.BAR_W / 2.0
        for i, (h, col) in enumerate(zip(fr.bars, fr.colors)):
            x = oa.BARS_X0 + i * (oa.BAR_W + oa.BAR_GAP)
            _ns(col).setFill()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, cy - h / 2.0, oa.BAR_W, h), rad, rad).fill()


class _OverlayController(NSObject):
    """Owns the panel; every method below runs on the main thread only."""

    def init(self):
        self = objc.super(_OverlayController, self).init()
        if self is None:
            return None
        self._panel = None
        self._view = None
        self._timer = None
        self._closing = False
        self._alpha = 0.0
        self.anim = oa.OverlayAnimation()
        return self

    # -- construction --------------------------------------------------
    @objc.python_method
    def _build(self):
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, _W, _H),
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered, False,
        )
        panel.setLevel_(NSScreenSaverWindowLevel)      # float above app windows
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)             # click-through
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        view = OmnihearPillView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, _H))
        panel.setContentView_(view)
        self._panel = panel
        self._view = view

    @objc.python_method
    def _reposition(self):
        screen = NSScreen.mainScreen()
        if screen is None or self._panel is None:
            return
        vf = screen.visibleFrame()
        x = vf.origin.x + (vf.size.width - _W) / 2.0
        y = vf.origin.y + 90.0
        self._panel.setFrameOrigin_(NSMakePoint(x, y))

    @objc.python_method
    def _show(self, mode):
        if self._panel is None:
            self._build()
        self.anim.set_mode(mode)
        self._closing = False
        if not self._panel.isVisible():
            self._alpha = 0.0
            self._panel.setAlphaValue_(0.0)
            self._reposition()
            self._panel.orderFrontRegardless()   # show without becoming key
        self._render()
        self._start_timer()

    # -- selector targets (no-arg selectors) -----------------------------
    def showRecording(self):
        self._show("listening")

    def showTranscribing(self):
        self._show("transcribing")

    def hideOverlay(self):
        if self._panel is None or not self._panel.isVisible():
            return
        self._closing = True
        self._start_timer()   # tick_ fades out, then orders the panel out

    # -- animation ---------------------------------------------------------
    @objc.python_method
    def _render(self):
        self._view.frame_state = self.anim.frame()
        self._view.setNeedsDisplay_(True)

    @objc.python_method
    def _start_timer(self):
        if self._timer is None:
            self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                oa.FRAME_MS / 1000.0, self, "tick:", None, True)

    @objc.python_method
    def _stop_timer(self):
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None

    def tick_(self, timer):
        if self._panel is None:
            self._stop_timer()
            return
        self._render()
        # ~150 ms fade in/out.
        target = 0.0 if self._closing else 1.0
        self._alpha += (target - self._alpha) * 0.45
        if abs(self._alpha - target) < 0.03:
            self._alpha = target
        self._panel.setAlphaValue_(self._alpha)
        if self._closing and self._alpha == 0.0:
            self._panel.orderOut_(None)
            self._stop_timer()
            self.anim.set_mode("hidden")


class MacOverlay:
    """Thread-safe façade: methods can be called from any thread; UI calls
    hop to the main thread where the AppKit panel lives."""

    def __init__(self):
        self._ctrl = _OverlayController.alloc().init()
        self._anim = self._ctrl.anim

    def _dispatch(self, selector):
        self._ctrl.performSelectorOnMainThread_withObject_waitUntilDone_(
            selector, None, False)

    def show(self):               # recording / listening
        self._dispatch("showRecording")

    def show_transcribing(self):
        self._dispatch("showTranscribing")

    def hide(self):
        self._anim.locked = False
        self._dispatch("hideOverlay")

    def set_level(self, rms):
        # Pure-Python model update (atomic float writes); safe off-main-thread.
        self._anim.set_level(rms)

    def set_locked(self, flag):
        """Hands-free lock: the listening dot becomes a stop square. A plain
        model attribute like set_level(); the next tick draws it."""
        self._anim.locked = bool(flag)
