"""Native macOS recording/transcribing indicator (AppKit floating panel).

macOS can't use the Tkinter overlay (Cocoa GUI must run on the main thread,
which the pystray menu-bar icon owns). Instead this draws a small borderless
NSPanel — a red pulsing dot while recording, an amber dot while transcribing —
bottom-center of the screen, click-through and non-activating so it never
steals keyboard focus from the field being typed into.

State changes arrive from the recorder/worker threads and are marshalled onto
the main thread (which the pystray NSApplication run loop services) via
performSelectorOnMainThread_. pyobjc is already a dependency on macOS.

Public interface mirrors the Tk RecordingOverlay (show/hide) and adds
show_transcribing(), so app.py can drive both overlays through the same hooks.
"""

import objc
from Foundation import NSObject, NSMakeRect, NSMakePoint, NSTimer
from AppKit import (
    NSPanel, NSColor, NSTextField, NSView, NSScreen, NSFont,
    NSBackingStoreBuffered, NSScreenSaverWindowLevel,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
)

# Not all of these mask constants are exported by every pyobjc version.
NSWindowStyleMaskBorderless = 0
NSWindowStyleMaskNonactivatingPanel = 1 << 7

_W, _H = 172.0, 46.0


def _cg(r, g, b, a=1.0):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a).CGColor()


class _OverlayController(NSObject):
    """Owns the panel; all UI methods below run on the main thread only."""

    def init(self):
        self = objc.super(_OverlayController, self).init()
        if self is None:
            return None
        self._panel = None
        self._dot = None
        self._label = None
        self._timer = None
        self._pulse_bright = True
        return self

    # -- construction (main thread) ----------------------------------
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

        content = panel.contentView()
        content.setWantsLayer_(True)
        content.layer().setBackgroundColor_(_cg(0.10, 0.10, 0.11, 0.95))
        content.layer().setCornerRadius_(12.0)
        content.layer().setMasksToBounds_(True)

        dot = NSView.alloc().initWithFrame_(NSMakeRect(20, _H / 2 - 6, 12, 12))
        dot.setWantsLayer_(True)
        dot.layer().setCornerRadius_(6.0)
        dot.layer().setBackgroundColor_(_cg(0.91, 0.30, 0.24))
        content.addSubview_(dot)

        label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(44, (_H - 22) / 2.0, _W - 54, 22))
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setTextColor_(NSColor.whiteColor())
        label.setFont_(NSFont.systemFontOfSize_(14.0))
        label.setStringValue_("Recording")
        content.addSubview_(label)

        self._panel = panel
        self._dot = dot
        self._label = label

    def _reposition(self):
        screen = NSScreen.mainScreen()
        if screen is None or self._panel is None:
            return
        vf = screen.visibleFrame()
        x = vf.origin.x + (vf.size.width - _W) / 2.0
        y = vf.origin.y + 90.0
        self._panel.setFrameOrigin_(NSMakePoint(x, y))

    # -- selector targets (main thread, no-arg selectors) ------------
    def showRecording(self):
        if self._panel is None:
            self._build()
        self._label.setStringValue_("Recording")
        self._dot.layer().setBackgroundColor_(_cg(0.91, 0.30, 0.24))
        self._reposition()
        self._panel.orderFrontRegardless()   # show without becoming key
        self._start_pulse()

    def showTranscribing(self):
        if self._panel is None:
            self._build()
        self._stop_pulse()
        self._label.setStringValue_("Transcribing…")
        self._dot.layer().setOpacity_(1.0)
        self._dot.layer().setBackgroundColor_(_cg(0.95, 0.65, 0.15))
        self._reposition()
        self._panel.orderFrontRegardless()

    def hideOverlay(self):
        self._stop_pulse()
        if self._panel is not None:
            self._panel.orderOut_(None)

    # -- pulse animation (main thread) -------------------------------
    def _start_pulse(self):
        self._stop_pulse()
        self._pulse_bright = True
        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.55, self, "pulse:", None, True)

    def _stop_pulse(self):
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None
        if self._dot is not None:
            self._dot.layer().setOpacity_(1.0)

    def pulse_(self, timer):
        if self._dot is None:
            return
        self._pulse_bright = not self._pulse_bright
        self._dot.layer().setOpacity_(1.0 if self._pulse_bright else 0.3)


class MacOverlay:
    """Thread-safe façade: methods can be called from any thread; each hops
    to the main thread where the AppKit panel lives."""

    def __init__(self):
        self._ctrl = _OverlayController.alloc().init()

    def _dispatch(self, selector):
        self._ctrl.performSelectorOnMainThread_withObject_waitUntilDone_(
            selector, None, False)

    def show(self):               # recording
        self._dispatch("showRecording")

    def show_transcribing(self):
        self._dispatch("showTranscribing")

    def hide(self):
        self._dispatch("hideOverlay")
