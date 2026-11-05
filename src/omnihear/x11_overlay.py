"""Transparent recording overlay for Linux: a 32-bit ARGB X11 window drawn
with cairo, both through ctypes (stdlib only; libX11/libXext/libcairo ship
with every desktop).

Why not the Tk overlay: Tk paints every pixel opaque, and the X SHAPE
extension it falls back on is ignored by GNOME's compositor for XWayland
windows, so on Ubuntu's default Wayland session the pill showed up as a
rectangle. An ARGB window lets the compositor blend real transparent,
anti-aliased corners -- on XWayland and on composited X11 alike.

Used only when a compositor is running (otherwise ARGB corners are black);
ArgbOverlay() raises OverlayUnavailable and app.py falls back to Tk.

Draws the same overlay_anim.Frame as the Tk and AppKit renderers, with the
same Style geometry and place() position. The window is click-through
(empty input shape). Public interface mirrors RecordingOverlay: show(),
show_transcribing(), hide(), set_level(), set_locked().

All Xlib/cairo calls happen on the overlay's own thread and its own
display connection; other threads only touch the queue and the
pure-Python animation model.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import math
import queue
import threading
import time
from ctypes import (POINTER, Structure, byref, c_char_p, c_double, c_int,
                    c_long, c_uint, c_ulong, c_void_p, c_short, c_ushort)

from . import overlay_anim as oa


class OverlayUnavailable(Exception):
    pass


class _XVisualInfo(Structure):
    _fields_ = [("visual", c_void_p), ("visualid", c_ulong), ("screen", c_int),
                ("depth", c_int), ("c_class", c_int), ("red_mask", c_ulong),
                ("green_mask", c_ulong), ("blue_mask", c_ulong),
                ("colormap_size", c_int), ("bits_per_rgb", c_int)]


class _XSetWindowAttributes(Structure):
    _fields_ = [("background_pixmap", c_ulong), ("background_pixel", c_ulong),
                ("border_pixmap", c_ulong), ("border_pixel", c_ulong),
                ("bit_gravity", c_int), ("win_gravity", c_int),
                ("backing_store", c_int), ("backing_planes", c_ulong),
                ("backing_pixel", c_ulong), ("save_under", c_int),
                ("event_mask", c_long), ("do_not_propagate_mask", c_long),
                ("override_redirect", c_int), ("colormap", c_ulong),
                ("cursor", c_ulong)]


class _XRectangle(Structure):
    _fields_ = [("x", c_short), ("y", c_short),
                ("width", c_ushort), ("height", c_ushort)]


_TRUE_COLOR = 4
_CW_BACK_PIXEL, _CW_BORDER_PIXEL = 1 << 1, 1 << 3
_CW_OVERRIDE_REDIRECT, _CW_COLORMAP = 1 << 9, 1 << 13
_SHAPE_INPUT, _SHAPE_SET = 2, 0
_CAIRO_FORMAT_ARGB32 = 0
_OP_CLEAR, _OP_SOURCE, _OP_OVER = 0, 1, 2
_CAP_ROUND = 1

_libs = None
_ERROR_HANDLER = None   # keep the ctypes callback alive


def _load():
    """Load and prototype libX11, libXext and libcairo (once)."""
    global _libs
    if _libs is not None:
        return _libs

    def lib(name, fallback):
        return ctypes.CDLL(ctypes.util.find_library(name) or fallback)

    try:
        x = lib("X11", "libX11.so.6")
        xe = lib("Xext", "libXext.so.6")
        cr = lib("cairo", "libcairo.so.2")
    except OSError as e:
        raise OverlayUnavailable(f"missing library: {e}")

    def proto(f, res, *args):
        f.restype, f.argtypes = res, list(args)

    vp, d = c_void_p, c_double
    proto(x.XOpenDisplay, vp, c_char_p)
    proto(x.XCloseDisplay, c_int, vp)
    proto(x.XDefaultScreen, c_int, vp)
    proto(x.XRootWindow, c_ulong, vp, c_int)
    proto(x.XDisplayWidth, c_int, vp, c_int)
    proto(x.XDisplayHeight, c_int, vp, c_int)
    proto(x.XMatchVisualInfo, c_int, vp, c_int, c_int, c_int, POINTER(_XVisualInfo))
    proto(x.XCreateColormap, c_ulong, vp, c_ulong, vp, c_int)
    proto(x.XCreateWindow, c_ulong, vp, c_ulong, c_int, c_int, c_uint, c_uint,
          c_uint, c_int, c_uint, vp, c_ulong, POINTER(_XSetWindowAttributes))
    proto(x.XInternAtom, c_ulong, vp, c_char_p, c_int)
    proto(x.XGetSelectionOwner, c_ulong, vp, c_ulong)
    proto(x.XStoreName, c_int, vp, c_ulong, c_char_p)
    proto(x.XMapRaised, c_int, vp, c_ulong)
    proto(x.XUnmapWindow, c_int, vp, c_ulong)
    proto(x.XFlush, c_int, vp)
    proto(x.XPending, c_int, vp)
    proto(x.XNextEvent, c_int, vp, vp)
    xe.XShapeQueryExtension.restype = c_int
    xe.XShapeQueryExtension.argtypes = [vp, POINTER(c_int), POINTER(c_int)]
    proto(xe.XShapeCombineRectangles, None, vp, c_ulong, c_int, c_int, c_int,
          POINTER(_XRectangle), c_int, c_int, c_int)

    proto(cr.cairo_image_surface_create, vp, c_int, c_int, c_int)
    proto(cr.cairo_xlib_surface_create, vp, vp, c_ulong, vp, c_int, c_int)
    proto(cr.cairo_surface_destroy, None, vp)
    proto(cr.cairo_surface_flush, None, vp)
    proto(cr.cairo_create, vp, vp)
    proto(cr.cairo_destroy, None, vp)
    proto(cr.cairo_set_operator, None, vp, c_int)
    proto(cr.cairo_set_source_rgba, None, vp, d, d, d, d)
    proto(cr.cairo_set_source_surface, None, vp, vp, d, d)
    proto(cr.cairo_paint, None, vp)
    proto(cr.cairo_paint_with_alpha, None, vp, d)
    proto(cr.cairo_new_path, None, vp)
    proto(cr.cairo_new_sub_path, None, vp)
    proto(cr.cairo_close_path, None, vp)
    proto(cr.cairo_arc, None, vp, d, d, d, d, d)
    proto(cr.cairo_rectangle, None, vp, d, d, d, d)
    proto(cr.cairo_fill, None, vp)
    proto(cr.cairo_stroke, None, vp)
    proto(cr.cairo_set_line_width, None, vp, d)
    proto(cr.cairo_set_line_cap, None, vp, c_int)
    _libs = (x, xe, cr)
    return _libs


def _ignore_x_errors(x):
    """Xlib's default error handler exits the process. Only this overlay
    talks to libX11 in-process (pynput uses pure-Python python-xlib, and the
    Tk overlay isn't created alongside this one), so a no-op handler is safe."""
    global _ERROR_HANDLER
    if _ERROR_HANDLER is None:
        handler_t = ctypes.CFUNCTYPE(c_int, c_void_p, c_void_p)
        _ERROR_HANDLER = handler_t(lambda dpy, ev: 0)
        x.XSetErrorHandler.restype = c_void_p
        x.XSetErrorHandler.argtypes = [handler_t]
        x.XSetErrorHandler(_ERROR_HANDLER)


def _probe(x, xe):
    """Open the display and check for what the ARGB overlay needs. Returns
    (dpy, screen, XVisualInfo); raises OverlayUnavailable."""
    dpy = x.XOpenDisplay(None)
    if not dpy:
        raise OverlayUnavailable("no X display")
    try:
        scr = x.XDefaultScreen(dpy)
        vinfo = _XVisualInfo()
        if not x.XMatchVisualInfo(dpy, scr, 32, _TRUE_COLOR, byref(vinfo)):
            raise OverlayUnavailable("no 32-bit visual")
        cm = x.XInternAtom(dpy, f"_NET_WM_CM_S{scr}".encode(), False)
        if not x.XGetSelectionOwner(dpy, cm):
            raise OverlayUnavailable("no compositing manager")
        ev, er = c_int(), c_int()
        if not xe.XShapeQueryExtension(dpy, byref(ev), byref(er)):
            raise OverlayUnavailable("no SHAPE extension (click-through)")
    except Exception:
        x.XCloseDisplay(dpy)
        raise
    return dpy, scr, vinfo


def _rounded_rect(cr, c, x0, y0, w, h, r):
    """Add a rounded-rectangle path to cairo context c (cr = libcairo)."""
    r = max(0.0, min(r, w / 2, h / 2))
    cr.cairo_new_sub_path(c)
    cr.cairo_arc(c, x0 + w - r, y0 + r, r, -math.pi / 2, 0)
    cr.cairo_arc(c, x0 + w - r, y0 + h - r, r, 0, math.pi / 2)
    cr.cairo_arc(c, x0 + r, y0 + h - r, r, math.pi / 2, math.pi)
    cr.cairo_arc(c, x0 + r, y0 + r, r, math.pi, 1.5 * math.pi)
    cr.cairo_close_path(c)


class ArgbOverlay:
    def __init__(self, cfg: dict | None = None):
        x, xe, _cr = _load()
        dpy, _scr, _v = _probe(x, xe)    # raises OverlayUnavailable
        x.XCloseDisplay(dpy)
        self.cfg = dict(cfg or {})
        self.style = oa.Style(self.cfg)
        self.anim = oa.OverlayAnimation(self.style)
        self.queue = queue.Queue()
        self._ready = threading.Event()
        self._error = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self._ready.wait(5)
        if self._error is not None:
            raise OverlayUnavailable(self._error)

    # -- public, any thread -------------------------------------------------
    def show(self):
        if self.thread.is_alive():
            self.queue.put("show")

    def show_transcribing(self):
        if self.thread.is_alive():
            self.queue.put("transcribing")

    def hide(self):
        self.anim.locked = False
        if self.thread.is_alive():
            self.queue.put("hide")

    def set_level(self, rms: float):
        self.anim.set_level(rms)

    def set_locked(self, flag: bool):
        self.anim.locked = bool(flag)

    # -- overlay thread -----------------------------------------------------
    def _run(self):
        try:
            x, xe, cr = _load()
            dpy, scr, vinfo = _probe(x, xe)
            _ignore_x_errors(x)
            st = self.style
            w, h = st.width, st.height
            px, py = oa.place(st, self.cfg, x.XDisplayWidth(dpy, scr),
                              x.XDisplayHeight(dpy, scr))
            root = x.XRootWindow(dpy, scr)
            attrs = _XSetWindowAttributes()
            attrs.override_redirect = 1
            attrs.colormap = x.XCreateColormap(dpy, root, vinfo.visual, 0)
            attrs.background_pixel = 0
            attrs.border_pixel = 0
            win = x.XCreateWindow(
                dpy, root, px, py, w, h, 0, 32, 1, vinfo.visual,
                _CW_OVERRIDE_REDIRECT | _CW_COLORMAP | _CW_BACK_PIXEL | _CW_BORDER_PIXEL,
                byref(attrs))
            if not win:
                raise OverlayUnavailable("XCreateWindow failed")
            x.XStoreName(dpy, win, b"omnihear")
            # Empty input region: clicks go to whatever is underneath.
            xe.XShapeCombineRectangles(dpy, win, _SHAPE_INPUT, 0, 0, None, 0,
                                       _SHAPE_SET, 0)
            win_surf = cr.cairo_xlib_surface_create(dpy, win, vinfo.visual, w, h)
            # Two off-screen buffers: the frame, then the frame with the
            # fade/opacity applied, which is copied to the window in one go.
            back = cr.cairo_image_surface_create(_CAIRO_FORMAT_ARGB32, w, h)
            out = cr.cairo_image_surface_create(_CAIRO_FORMAT_ARGB32, w, h)
            if not win_surf or not back or not out:
                raise OverlayUnavailable("cairo surface creation failed")
            x.XFlush(dpy)
        except Exception as e:
            self._error = str(e) or type(e).__name__
            self._ready.set()
            return
        self._ready.set()

        visible, closing, alpha = False, False, 0.0
        event = ctypes.create_string_buffer(256)   # sizeof(XEvent) is 192
        while True:
            # Nothing is selected, but some events (e.g. from the
            # compositor) still arrive; read them so the queue can't grow.
            while x.XPending(dpy):
                x.XNextEvent(dpy, event)
            try:
                while True:
                    action = self.queue.get_nowait()
                    if action in ("show", "transcribing"):
                        self.anim.set_mode("listening" if action == "show"
                                           else "transcribing")
                        closing = False
                        if not visible:
                            visible, alpha = True, 0.0
                            x.XMapRaised(dpy, win)
                    elif action == "hide":
                        closing = True
            except queue.Empty:
                pass
            if visible:
                target = 0.0 if closing else 1.0
                alpha += (target - alpha) * 0.45
                if abs(alpha - target) < 0.03:
                    alpha = target
                if closing and alpha == 0.0:
                    x.XUnmapWindow(dpy, win)
                    visible = False
                    self.anim.set_mode("hidden")
                else:
                    self._draw(cr, back, self.anim.frame())
                    self._present(cr, win_surf, back, out, alpha * st.opacity)
                x.XFlush(dpy)
            time.sleep(oa.FRAME_MS / 1000.0 if visible else 0.05)

    def _present(self, cr, win_surf, back, out, alpha):
        """Show the frame in `back` at `alpha`. Everything is composed
        off-screen and then replaces the window's pixels in a single SOURCE
        copy: clearing the window and painting over it as two steps let the
        compositor sometimes show the cleared (invisible) window in between,
        which made the pill flicker while it animated."""
        c = cr.cairo_create(out)
        cr.cairo_set_operator(c, _OP_CLEAR)
        cr.cairo_paint(c)
        cr.cairo_set_operator(c, _OP_OVER)
        cr.cairo_set_source_surface(c, back, 0, 0)
        cr.cairo_paint_with_alpha(c, alpha)
        cr.cairo_destroy(c)
        cr.cairo_surface_flush(out)
        c = cr.cairo_create(win_surf)
        cr.cairo_set_operator(c, _OP_SOURCE)
        cr.cairo_set_source_surface(c, out, 0, 0)
        cr.cairo_paint(c)
        cr.cairo_destroy(c)
        cr.cairo_surface_flush(win_surf)

    def _draw(self, cr, surf, fr):
        """One overlay_anim.Frame into the ARGB back buffer (y down)."""
        st = self.style
        c = cr.cairo_create(surf)
        rgba = lambda col, a=1.0: cr.cairo_set_source_rgba(c, *col, a)
        cr.cairo_set_operator(c, _OP_CLEAR)
        cr.cairo_paint(c)
        cr.cairo_set_operator(c, _OP_OVER)

        _rounded_rect(cr, c, 0, 0, st.width, st.height, st.radius)
        rgba(st.bg)
        cr.cairo_fill(c)

        cx, cy, d = st.dot_cx, st.cy, fr.dot
        if d.spinner is None:
            if d.halo_alpha > 0.01:
                cr.cairo_new_path(c)
                cr.cairo_arc(c, cx, cy, d.halo_r, 0, 2 * math.pi)
                rgba(d.color, d.halo_alpha)
                cr.cairo_fill(c)
            rgba(d.color)
            if d.stop:
                s = st.stop_half
                _rounded_rect(cr, c, cx - s, cy - s, 2 * s, 2 * s, st.stop_corner)
            else:
                cr.cairo_new_path(c)
                cr.cairo_arc(c, cx, cy, st.dot_r, 0, 2 * math.pi)
            cr.cairo_fill(c)
        else:
            sr = st.spinner_r
            cr.cairo_set_line_width(c, st.line_w)
            cr.cairo_set_line_cap(c, _CAP_ROUND)
            cr.cairo_new_path(c)
            cr.cairo_arc(c, cx, cy, sr, 0, 2 * math.pi)
            rgba(d.color, 0.25)
            cr.cairo_stroke(c)
            # Model angle: clockwise degrees from 12 o'clock; cairo's y-down
            # arcs also run clockwise, from 3 o'clock.
            a0 = math.radians(d.spinner) - math.pi / 2
            cr.cairo_new_path(c)
            cr.cairo_arc(c, cx, cy, sr, a0, a0 + math.radians(110))
            rgba(d.color)
            cr.cairo_stroke(c)

        bw = st.bar_w
        rad = bw / 2 if st.round_bars else 0.0
        for i, (bh, col) in enumerate(zip(fr.bars, fr.colors)):
            _rounded_rect(cr, c, st.bar_x(i) - bw / 2, cy - bh / 2, bw, bh, rad)
            rgba(col)
            cr.cairo_fill(c)
        cr.cairo_destroy(c)
        cr.cairo_surface_flush(surf)
