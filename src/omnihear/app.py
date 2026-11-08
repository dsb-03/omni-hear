"""Core push-to-talk record/transcribe/type logic.

Heavy dependencies (numpy, sounddevice, faster_whisper, pynput) are
imported here — inside functions where possible — so the rest of the
package (db, config, dashboard, feedback) stays importable without them.
"""

import gc
import queue
import sys
import threading
import time

# Accepted hotkey names live in config.py (single source of truth,
# shared with the dashboard); resolved lazily here since it needs pynput.
from . import config as config_mod
from .config import SPECIAL_KEY_NAMES


def linux_session_methods():
    """type_method values handled by linux_session (vs. pynput)."""
    return ("xdotool", "ydotool", "wtype", "uinput")


def resolve_key(name):
    """Resolve a single canonical key name to a pynput key object."""
    from pynput import keyboard
    name = name.strip().lower()
    if name in SPECIAL_KEY_NAMES:
        return getattr(keyboard.Key, name)
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    raise ValueError(
        f"Unrecognized hotkey part '{name}'. Use one of {SPECIAL_KEY_NAMES} "
        "or a single character."
    )


def parse_hotkey(name):
    """Parse a canonical hotkey string ('f9', 'ctrl_l+space') into a
    frozenset of pynput key objects. A single key is the degenerate
    one-element combo, so existing configs keep working."""
    parts = [p for p in name.strip().lower().split("+") if p]
    if not parts:
        raise ValueError("Empty hotkey.")
    return frozenset(resolve_key(p) for p in parts)


def _pill_points(x0, y0, x1, y1, r):
    """Polygon points for a rounded rectangle (draw with smooth=True)."""
    return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
            x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]


def _x11_shape_rounded(root, w, h, r):
    """Clip the overlay's X11 window to a w x h rounded rectangle (corner
    radius r) with the X SHAPE extension, via ctypes on libX11/libXext.
    Best-effort: returns False and leaves a plain rectangle when the
    libraries or extension are missing."""
    try:
        import ctypes
        import ctypes.util
        from ctypes import c_short, c_ushort, c_int, c_ulong, c_void_p, c_char_p

        x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        xext = ctypes.CDLL(ctypes.util.find_library("Xext") or "libXext.so.6")

        class XRectangle(ctypes.Structure):
            _fields_ = [("x", c_short), ("y", c_short),
                        ("width", c_ushort), ("height", c_ushort)]

        x11.XOpenDisplay.restype = c_void_p
        x11.XOpenDisplay.argtypes = [c_char_p]
        x11.XFlush.argtypes = [c_void_p]
        x11.XCloseDisplay.argtypes = [c_void_p]
        xext.XShapeQueryExtension.argtypes = [c_void_p, ctypes.POINTER(c_int),
                                              ctypes.POINTER(c_int)]
        xext.XShapeCombineRectangles.argtypes = [
            c_void_p, c_ulong, c_int, c_int, c_int,
            ctypes.POINTER(XRectangle), c_int, c_int, c_int]

        root.update_idletasks()             # make Tk create the X window
        win = int(root.wm_frame(), 16)      # the toplevel's outer window
        dpy = x11.XOpenDisplay(root.winfo_screen().encode())
        if not dpy:
            return False
        try:
            ev, er = c_int(), c_int()
            if not xext.XShapeQueryExtension(dpy, ctypes.byref(ev), ctypes.byref(er)):
                return False
            r = min(r, w / 2, h / 2)
            rows = []
            for y in range(h):
                # Inset of this row at the rounded corners (circle of radius r).
                dy = max(0.0, r - (y + 0.5), (y + 0.5) - (h - r))
                inset = round(r - (max(0.0, r * r - dy * dy)) ** 0.5) if dy else 0
                rows.append(XRectangle(inset, y, max(1, w - 2 * inset), 1))
            arr = (XRectangle * len(rows))(*rows)
            # ShapeBounding = 0, ShapeSet = 0, Unsorted = 0
            xext.XShapeCombineRectangles(dpy, win, 0, 0, 0, arr, len(rows), 0, 0)
            x11.XFlush(dpy)
        finally:
            x11.XCloseDisplay(dpy)
        return True
    except Exception:
        return False


def _linux_or_windows_overlay(cfg):
    """Linux: the transparent ARGB/cairo overlay (x11_overlay.py) when a
    compositor is running -- the only way to get real rounded corners on
    GNOME Wayland, whose compositor ignores X SHAPE on XWayland windows.
    Otherwise, and on Windows, the Tk overlay."""
    if sys.platform != "win32":
        try:
            from .x11_overlay import ArgbOverlay
            return ArgbOverlay(cfg)
        except Exception:
            pass
    return RecordingOverlay(cfg)


class RecordingOverlay:
    """Floating pill on screen (Tk: Linux X11/XWayland and Windows),
    bottom-centre by default. Listening: red dot + waveform that follows the
    live mic level; the dot becomes a rounded stop square while hands-free
    recording is locked. Transcribing: amber spinner + flowing wave. Drawing
    comes from the shared model in overlay_anim.py, which the macOS overlay
    uses too; size, colours, shapes and position come from the overlay_*
    config keys (overlay_anim.Style / place()).

    show()/show_transcribing()/hide() are called from any thread and queued
    to the Tk thread; set_level() is called from the audio callback and
    set_locked() from any thread (both just set model attributes).
    """

    def __init__(self, cfg: dict | None = None):
        from .overlay_anim import OverlayAnimation, Style
        self.cfg = dict(cfg or {})
        self.style = Style(self.cfg)
        self.anim = OverlayAnimation(self.style)
        self.root = None
        self.queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            import tkinter as tk
        except ImportError:
            return
        from . import overlay_anim as oa
        sty = self.style

        try:
            # Under Wayland this is an XWayland window; with no X display
            # at all (XWayland disabled) just run without the overlay.
            self.root = tk.Tk()
        except tk.TclError:
            self.root = None
            return
        root = self.root
        root.overrideredirect(True)
        root.attributes("-topmost", True)

        w, h = sty.width, sty.height
        try:
            mon = None
            if sys.platform == "win32":
                # Primary monitor's top-left is always (0, 0) in Windows'
                # multi-monitor coordinate space; SM_CXSCREEN/SM_CYSCREEN
                # (indices 0, 1) are its size, unlike winfo_screenwidth()/
                # _height(), which span every monitor combined.
                import ctypes
                user32 = ctypes.windll.user32
                mon = (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
            elif sys.platform != "darwin":
                from . import linux_session
                mon = linux_session.primary_monitor_geometry()
            if mon:
                mx, my, mw, mh = mon
            else:
                mx, my = 0, 0
                mw, mh = root.winfo_screenwidth(), root.winfo_screenheight()
            x, y = oa.place(sty, self.cfg, mw, mh)
            root.geometry(f"{w}x{h}+{x + mx}+{y + my}")
        except Exception:
            root.geometry(f"{w}x{h}+900+900")

        bg = oa.to_hex(sty.bg)
        window_bg = bg
        outline = ""
        if sys.platform == "win32":
            # A colour key makes everything outside the pill transparent, so
            # Windows gets real rounded ends.
            key = "#010203"
            try:
                root.attributes("-transparentcolor", key)
                window_bg = key
                outline = oa.to_hex(sty.edge)
            except tk.TclError:
                pass
        elif sty.radius > 0:
            # X11 has no colour key; clip the window itself to the shape.
            # Without the SHAPE extension the pill fills a small rectangle.
            _x11_shape_rounded(root, w, h, sty.radius)
        root.configure(bg=window_bg)

        canvas = tk.Canvas(root, width=w, height=h, bg=window_bg,
                           highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        if sty.radius > 0:
            canvas.create_polygon(
                _pill_points(0.5, 0.5, w - 0.5, h - 0.5, sty.radius),
                smooth=True, fill=bg, outline=outline)
        else:
            canvas.create_rectangle(0, 0, w - 1, h - 1, fill=bg, outline=outline)

        cx, cy = sty.dot_cx, sty.cy
        sr, dr = sty.spinner_r, sty.dot_r
        rec = oa.to_hex(sty.rec)
        halo = canvas.create_oval(0, 0, 0, 0, fill=bg, outline="")
        dot = canvas.create_oval(cx - dr, cy - dr, cx + dr, cy + dr,
                                 fill=rec, outline="")
        s = sty.stop_half
        stop_sq = canvas.create_polygon(
            _pill_points(cx - s, cy - s, cx + s, cy + s, sty.stop_corner),
            smooth=True, fill=rec, outline="", state="hidden")
        track = canvas.create_oval(cx - sr, cy - sr, cx + sr, cy + sr,
                                   width=sty.line_w,
                                   outline=oa.to_hex(oa.mix(sty.busy, sty.bg, 0.75)),
                                   state="hidden")
        spinner = canvas.create_arc(cx - sr, cy - sr, cx + sr, cy + sr,
                                    start=90, extent=110, style="arc",
                                    width=sty.line_w,
                                    outline=oa.to_hex(sty.busy), state="hidden")
        cap = "round" if sty.round_bars else "butt"
        # Round caps add bar_w/2 at each end of the line; butt caps add none.
        cap_add = sty.bar_w if sty.round_bars else 0.0
        bars = [canvas.create_line(sty.bar_x(i), cy, sty.bar_x(i), cy,
                                   width=sty.bar_w, capstyle=cap,
                                   fill=oa.to_hex(sty.bar))
                for i in range(sty.n_bars)]

        def set_alpha(a):
            try:
                root.attributes("-alpha", a)
                return True
            except tk.TclError:
                return False

        def draw(fr):
            d = fr.dot
            if d.spinner is None:
                r = d.halo_r
                canvas.coords(halo, cx - r, cy - r, cx + r, cy + r)
                canvas.itemconfigure(
                    halo, state="normal",
                    fill=oa.to_hex(oa.mix(d.color, sty.bg, 1.0 - d.halo_alpha)))
                # Locked (hands-free): stop square instead of the dot.
                shown, hidden = (stop_sq, dot) if d.stop else (dot, stop_sq)
                canvas.itemconfigure(shown, state="normal", fill=oa.to_hex(d.color))
                canvas.itemconfigure(hidden, state="hidden")
                canvas.itemconfigure(track, state="hidden")
                canvas.itemconfigure(spinner, state="hidden")
            else:
                canvas.itemconfigure(halo, state="hidden")
                canvas.itemconfigure(dot, state="hidden")
                canvas.itemconfigure(stop_sq, state="hidden")
                canvas.itemconfigure(track, state="normal")
                # Tk angles run counter-clockwise; the model's run clockwise.
                canvas.itemconfigure(spinner, state="normal", start=-d.spinner)
            for i, (item, bh, col) in enumerate(zip(bars, fr.bars, fr.colors)):
                half = max(0.25, (bh - cap_add) / 2)
                x = sty.bar_x(i)
                canvas.coords(item, x, cy - half, x, cy + half)
                canvas.itemconfigure(item, fill=oa.to_hex(col))

        root.withdraw()
        st = {"visible": False, "closing": False, "alpha": 0.0}

        def tick():
            try:
                while True:
                    action = self.queue.get_nowait()
                    if action in ("show", "transcribing"):
                        self.anim.set_mode("listening" if action == "show"
                                           else "transcribing")
                        st["closing"] = False
                        if not st["visible"]:
                            st["visible"] = True
                            st["alpha"] = 0.0
                            set_alpha(0.0)
                            root.deiconify()
                            root.lift()
                    elif action == "hide":
                        st["closing"] = True
            except queue.Empty:
                pass
            if st["visible"]:
                draw(self.anim.frame())
                # Quick fade in/out (~150 ms). Where -alpha is unsupported,
                # show and hide happen immediately.
                target = 0.0 if st["closing"] else sty.opacity
                st["alpha"] += (target - st["alpha"]) * 0.45
                if abs(st["alpha"] - target) < 0.03:
                    st["alpha"] = target
                faded = set_alpha(st["alpha"])
                if st["closing"] and (st["alpha"] == 0.0 or not faded):
                    root.withdraw()
                    st["visible"] = False
                    self.anim.set_mode("hidden")
            root.after(oa.FRAME_MS if st["visible"] else 50, tick)

        root.after(50, tick)
        root.mainloop()

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
        """Live mic level (block RMS) from the audio callback thread."""
        self.anim.set_level(rms)

    def set_locked(self, flag: bool):
        """Hands-free lock: draw the stop square instead of the dot."""
        self.anim.locked = bool(flag)


# Hands-free timing (seconds): a press shorter than TAP_SECONDS is a tap, and
# a second press within DOUBLE_TAP_SECONDS of a tap's release locks recording.
TAP_SECONDS = 0.3
DOUBLE_TAP_SECONDS = 0.35
# A hotkey press during, or this soon after, one of our own insertions may be
# our injected keystrokes matching it: pynput listeners (X11, Windows, macOS)
# see synthetic keys too. See App._insertion_echo / _could_self_trigger.
INSERT_ECHO_SECONDS = 0.3


class App:
    def __init__(self, cfg: dict, db=None, feedback=None, brain=None,
                 personal=None):
        self.cfg = cfg
        self.db = db
        self.feedback = feedback
        self.brain = brain
        self.personal = personal  # dictionary / snippets / app styles (personal.py)
        # transcribe() options this faster-whisper rejected (too old)
        self._unsupported_opts = set()
        # Chunked transcription: per-recording text of chunks already
        # transcribed (worker-only), and the audio thread's pause tracking.
        self._chunk_acc = {}
        self._chunk_frames = 0    # samples since the last cut
        self._quiet_frames = 0    # consecutive quiet samples
        self._speech_rms = 0.0    # decaying loud level, for relative pauses
        self._chunks_cut = 0      # chunks queued for the current recording

        self._model = None
        self._model_lock = threading.Lock()
        self._last_used = time.monotonic()

        self._audio_q = queue.Queue()
        self._work_q = queue.Queue()
        self._recording = False
        self._recording_mode = "dictate"
        self._stream = None
        self._last_typed_len = 0
        self._last_text = ""  # most recent transcript, seeds RAG context lookups
        self._last_inserted = ""  # last text put at the cursor (paste-last hotkey)
        self._last_rms = 0.0      # live mic level while recording (dashboard meter)
        self._locked = False      # hands-free: recording continues without holding
        # Hotkey state machine (_on_hotkey_press): listener threads and timers
        # call in, _hk_lock serializes them.
        self._hk_lock = threading.Lock()
        self._hk_state = "idle"   # while recording: "held" | "armed" | "locked"
        self._press_t = 0.0       # when the held press began (tap detection)
        self._rec_gen = 0         # bumped per recording, so stale timers no-op
        self._tap_timer = None    # hands-free double-tap window
        self._max_timer = None    # max_recording_seconds watchdog
        # Safety cap for every recording; out-of-range CLI/file values clamp.
        self._max_seconds = min(3600, max(10, int(
            cfg.get("max_recording_seconds", 300))))
        self._transcribing = 0    # transcription jobs queued or running
        self._inserting = False     # an insertion is in progress (worker)
        self._insert_window = None  # (start, end) of the most recent insertion
        self._verbose = bool(cfg.get("verbose"))
        self._overlay = None
        self._listener = None
        self._kb_controller = None
        # Resolved at run() so Wayland can remap pynput/auto -> ydotool/wtype.
        self._type_method = cfg.get("type_method") or "auto"
        # macOS can't use the Tk overlay (Cocoa GUI must own the main thread,
        # which the menu-bar tray takes) — use the native AppKit panel instead.
        # Both draw the same animation (overlay_anim.py).
        try:
            if sys.platform == "darwin":
                from .macos_overlay import MacOverlay
                self._overlay = MacOverlay(cfg)
            else:
                self._overlay = _linux_or_windows_overlay(cfg)
        except Exception as e:
            print(f"omnihear: warning: overlay could not start: {e}")
        # Feeds the live mic level to the overlay (None if it has no meter).
        self._overlay_level = getattr(self._overlay, "set_level", None)

    def _log(self, msg):
        """Per-transcription chatter; printed only with --verbose."""
        if self._verbose:
            print(msg)

    # -- status for the dashboard ------------------------------------
    def status(self) -> dict:
        from .overlay_anim import level_from_rms
        ask = self.cfg.get("ask_hotkey") or ""
        paste_last = self.cfg.get("paste_last_hotkey") or ""
        cmd = self.cfg.get("command_hotkey") or ""
        return {
            "model": self.cfg["model"],
            "hotkey": self.cfg["hotkey"],
            "hotkey_display": config_mod.hotkey_display(self.cfg["hotkey"]),
            "ask_hotkey_display": config_mod.hotkey_display(ask) if ask else "",
            "paste_last_hotkey_display": (config_mod.hotkey_display(paste_last)
                                          if paste_last else ""),
            "model_loaded": self._model is not None,
            "recording": self._recording,
            "recording_mode": self._recording_mode if self._recording else "",
            "locked": self._locked,
            "hands_free": bool(self.cfg.get("hands_free")),
            # 0..1 live mic level while recording (same scale as the overlay)
            "level": level_from_rms(self._last_rms) if self._recording else 0.0,
            "type_method": self._type_method,
            "paste": self._paste,
            "cleanup": self.cfg.get("cleanup", "off"),
            "command_hotkey_display": (config_mod.hotkey_display(cmd)
                                       if cmd else ""),
            "whisper_mode": bool(self.cfg.get("whisper_mode")),
            "chunked_transcription": bool(self.cfg.get("chunked_transcription")),
        }

    def _brain_active(self) -> bool:
        if self.brain is None:
            return False
        from . import cloud
        return cloud.beta_active()

    # -- model lifecycle ---------------------------------------------
    def _get_model(self):
        with self._model_lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                print(f"Loading Whisper model '{self.cfg['model']}' on "
                      f"{self.cfg['device']} ({self.cfg['compute_type']})...")
                if self.feedback:
                    self.feedback.notify("omnihear", "Loading Whisper model…")
                self._model = WhisperModel(
                    self.cfg["model"],
                    device=self.cfg["device"],
                    compute_type=self.cfg["compute_type"],
                )
                print("Model loaded.")
            self._last_used = time.monotonic()
            return self._model

    def _idle_unload_loop(self):
        timeout = self.cfg["idle_unload_minutes"] * 60
        while True:
            time.sleep(30)
            if timeout <= 0:
                continue
            with self._model_lock:
                if (self._model is not None
                        and time.monotonic() - self._last_used > timeout):
                    print("Idle timeout: unloading model to free RAM.")
                    self._model = None
                    gc.collect()

    # -- typing -------------------------------------------------------
    # type_method = "paste" (beta) is switched on by _setup_insertion();
    # until then, and for every other method, _insert() types.
    _paste = False
    _PASTE_SETTLE = 0.06   # s between setting the clipboard and the paste key
    _PASTE_RESTORE = 0.6   # s the app gets to read it before the old text returns

    def _setup_insertion(self):
        """Resolve type_method to the backend that actually runs (Wayland
        remaps pynput/auto). "paste" sends its paste key through whatever
        "auto" picks, which also types when the clipboard is unavailable."""
        from . import linux_session
        configured = self.cfg.get("type_method") or "auto"
        self._type_method = linux_session.resolve_type_method(configured)
        self._paste = configured == "paste"
        if self._paste:
            from . import clipboard
            self._clip_lock = threading.Lock()
            self._clip_gen = 0        # bumped per paste; stale restores skip
            self._clip_ours = None    # our text, while its restore is pending
            self._clip_saved = (None, None)  # user's (clipboard, PRIMARY) text
            self._clip_sent_at = 0.0  # monotonic time of the last paste key
            tool = clipboard.backend()
            key = {"darwin": "Cmd+V", "win32": "Ctrl+V"}.get(
                sys.platform, "Shift+Insert")
            if tool:
                print(f"omnihear: type_method=paste (beta): clipboard via "
                      f"{tool}, {key} via {self._type_method}")
            else:
                print("omnihear: type_method=paste (beta): no clipboard tool "
                      f"found, typing via {self._type_method} instead "
                      "(see omnihear --doctor)")
        elif (sys.platform not in ("win32", "darwin")
                and self._type_method != configured):
            print(f"omnihear: using type_method={self._type_method} "
                  f"(config had {configured!r}, "
                  f"session={linux_session.session_type()})")

    def _insert(self, text):
        """Put text at the cursor. Single entry point for every insertion
        (dictation, Q&A answers, paste-last), so insertion strategy
        (typing vs. clipboard paste) lives in one place."""
        self._inserting = True
        start = time.monotonic()
        try:
            if self._paste and text:
                self._paste_text(text)
            else:
                self._type_text(text)
        finally:
            self._insert_window = (start, time.monotonic())
            self._inserting = False
        self._last_inserted = text

    def _insertion_echo(self, t):
        """True if time t falls during, or just after, one of our own
        insertions -- i.e. a hotkey "press" then may be our injected keys."""
        if self._inserting:
            return True
        win = self._insert_window
        return win is not None and win[0] <= t <= win[1] + INSERT_ECHO_SECONDS

    def _could_self_trigger(self, name):
        """Could our own text insertion press this hotkey combo? pynput
        listeners (X11, Windows, macOS) also see keys we inject; the Wayland
        evdev reader skips our virtual keyboards, so it never can. Typing
        presses character keys and Shift; paste mode also sends Ctrl+V
        (Windows) or Cmd+V (macOS) (Linux's Shift+Insert is covered by
        Shift)."""
        if sys.platform not in ("win32", "darwin"):
            from . import linux_session
            if linux_session.is_wayland():
                return False
        parts = [p for p in name.strip().lower().split("+") if p]
        risky = {"shift_l", "shift_r"}
        if self._paste and sys.platform == "win32":
            risky |= {"ctrl_l", "ctrl_r"}
        if self._paste and sys.platform == "darwin":
            risky |= {"cmd_l", "cmd_r"}
        if self.cfg.get("command_hotkey"):
            # Command Mode sends the copy key: Cmd+C, Ctrl+C or Ctrl+Insert.
            risky |= ({"cmd_l", "cmd_r"} if sys.platform == "darwin"
                      else {"ctrl_l", "ctrl_r", "insert"})
        return bool(parts) and all(p in risky or len(p) == 1 for p in parts)

    def _guard_press(self, name, on_press):
        """Wrap a hotkey on_press so presses during our own insertions are
        ignored -- only for combos our insertion could actually press, so a
        normal hotkey (e.g. Right Ctrl) still works while text is typing."""
        if not name or not self._could_self_trigger(name):
            return on_press

        def guarded():
            if self._insertion_echo(time.monotonic()):
                self._log(f"Ignored {name} press during our own typing.")
                return
            on_press()
        return guarded

    def _paste_text(self, text):
        """Clipboard paste: save the user's clipboard text, put ours there,
        send the paste key, and put theirs back shortly after. Types instead
        when the clipboard can't be set; if the paste key can't be sent, the
        text stays on the clipboard for a manual paste."""
        from . import clipboard
        with self._clip_lock:
            if self._clip_ours is None:
                saved = (clipboard.get_text(), clipboard.get_text(primary=True))
            else:
                # Back-to-back pastes: the clipboard still holds our previous
                # text, and its pending restore still owes the user's own.
                saved = self._clip_saved
                # Apps read the clipboard asynchronously after the paste key;
                # keep the previous text there as long as a restore would.
                wait = self._clip_sent_at + self._PASTE_RESTORE - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
            if not clipboard.set_text(text):
                self._log("paste: clipboard unavailable, typing instead")
                self._type_text(text)
                return
            self._clip_gen += 1
            gen = self._clip_gen
            self._clip_saved, self._clip_ours = saved, text
            time.sleep(self._PASTE_SETTLE)  # let the new owner settle
            if not self._paste_chord():
                self._clip_saved, self._clip_ours = (None, None), None
                key = "Cmd+V" if sys.platform == "darwin" else "Ctrl+V"
                print("omnihear: could not send the paste key; the text is "
                      f"on the clipboard, press {key}")
                if self.feedback:
                    self.feedback.notify("omnihear",
                                         f"Copied — press {key} to paste",
                                         urgency="normal")
                return
            self._clip_sent_at = time.monotonic()
        timer = threading.Timer(self._PASTE_RESTORE, self._restore_clipboard,
                                args=(gen,))
        timer.daemon = True
        timer.start()

    def _restore_clipboard(self, gen):
        """Put the user's clipboard text back after a paste, unless a newer
        paste took over (its own restore comes later) or something else was
        copied or selected meanwhile. Non-text content can't be restored."""
        from . import clipboard
        with self._clip_lock:
            if gen != self._clip_gen or self._clip_ours is None:
                return
            (clip, prim), ours = self._clip_saved, self._clip_ours
            self._clip_saved, self._clip_ours = (None, None), None
            restored = False
            if clip is not None and clipboard.get_text() == ours:
                restored = clipboard.set_text(clip, primary=False)
            if prim is not None and clipboard.get_text(primary=True) == ours:
                restored = clipboard.set_primary(prim) or restored
            if restored:
                time.sleep(self._PASTE_SETTLE)  # before a next paste reads it

    def _paste_chord(self) -> bool:
        return self._chord("paste")

    def _chord(self, kind) -> bool:
        """Send the paste or copy key through the key backend. Paste:
        Shift+Insert on Linux (see linux_session.paste_chord), Ctrl+V on
        Windows, Cmd+V on macOS. Copy: Ctrl+Insert, Ctrl+C, Cmd+C. True if
        it was sent."""
        method = self._type_method
        if method in linux_session_methods():
            from . import linux_session
            send = (linux_session.paste_chord if kind == "paste"
                    else linux_session.copy_chord)
            return send(method)
        try:
            from pynput.keyboard import Key, KeyCode
            letter, vk = ("v", 0x56) if kind == "paste" else ("c", 0x43)
            if sys.platform == "darwin":
                mod, key = Key.cmd, KeyCode.from_char(letter)
            elif sys.platform == "win32":
                # VK code, so non-Latin layouts still send Ctrl+V / Ctrl+C.
                mod, key = Key.ctrl, KeyCode.from_vk(vk)
            else:
                mod = Key.shift if kind == "paste" else Key.ctrl
                key = Key.insert
            kb = self._kb()
            with kb.pressed(mod):
                kb.press(key)
                kb.release(key)
        except Exception as e:
            self._log(f"{kind} key failed: {e}")
            return False
        return True

    def _kb(self):
        """The pynput keyboard Controller (X11 auto, Windows, macOS), made
        on first use."""
        if self._kb_controller is None:
            from pynput import keyboard
            self._kb_controller = keyboard.Controller()
        return self._kb_controller

    def _type_text(self, text):
        method = self._type_method
        if method in linux_session_methods():
            from . import linux_session
            linux_session.type_text(method, text)
            return
        self._kb().type(text)

    def _backspace(self, n):
        """Erase the last n characters inserted (typed or pasted)."""
        if n <= 0:
            return
        method = self._type_method
        if method in linux_session_methods():
            from . import linux_session
            linux_session.backspace(method, n)
            return
        from pynput.keyboard import Key
        kb = self._kb()
        for _ in range(n):
            kb.press(Key.backspace)
            kb.release(Key.backspace)

    @staticmethod
    def _clean_audio(audio, whisper=False):
        """Trim near-silent edges and normalize peak amplitude. vad_filter
        (faster-whisper) handles silence *segmentation* during decoding but
        not input *level* -- a quiet mic can still skew the no_speech_prob/
        avg_logprob confidence thresholds, which normalization fixes.
        Whisper mode (quiet speech) uses a lower edge gate and normalizes
        loudness (RMS) instead of the peak, so one click can't keep a
        whisper quiet; the few samples that would clip are limited."""
        import numpy as np
        threshold = 0.002 if whisper else 0.01
        loud = np.where(np.abs(audio) > threshold)[0]
        if loud.size:
            audio = audio[loud[0]:loud[-1] + 1]
        if whisper and audio.size:
            rms = float(np.sqrt(np.mean(np.square(audio))))
            if rms > 1e-5:
                return np.clip(audio * min(0.1 / rms, 100.0), -0.99, 0.99)
            return audio
        peak = np.abs(audio).max() if audio.size else 0.0
        if peak > 1e-4:
            audio = audio * (0.9 / peak)
        return audio

    # -- recording ----------------------------------------------------
    def _audio_callback(self, indata, frames_count, time_info, status):
        if status:
            print(status)
        self._audio_q.put(indata.copy())
        # Block RMS drives the overlay's live waveform and the dashboard's
        # mic meter. Cheap (one pass over a few hundred samples) and never
        # allowed to break capture.
        try:
            import numpy as np
            rms = float(np.sqrt(np.mean(np.square(indata))))
        except Exception:
            return
        if self.cfg.get("chunked_transcription") and self._recording:
            self._track_pause(len(indata), rms)
        if self.cfg.get("whisper_mode"):
            rms *= 4  # ~+12 dB on the meters, so whispering still shows
        self._last_rms = rms
        set_level = self._overlay_level
        if set_level is not None:
            try:
                set_level(rms)
            except Exception:
                pass

    # Chunked transcription: cut at a pause of PAUSE_SECONDS once a chunk
    # holds chunk_seconds of audio. Runs on the audio thread, which must
    # never take _hk_lock (_stop_recording holds it while closing the
    # stream, and closing waits for this callback).
    PAUSE_SECONDS = 0.5

    def _track_pause(self, frames, rms):
        sr = self.cfg["sample_rate"]
        self._speech_rms = max(rms, self._speech_rms * 0.995)
        # Quiet relative to how loud this speaker is, with a floor for
        # digital silence -- works for whispering as well as normal speech.
        quiet = rms < max(2e-4, self._speech_rms * 0.15)
        self._quiet_frames = self._quiet_frames + frames if quiet else 0
        self._chunk_frames += frames
        if (self._chunk_frames >= self.cfg.get("chunk_seconds", 10) * sr
                and self._quiet_frames >= self.PAUSE_SECONDS * sr):
            self._cut_chunk()

    def _cut_chunk(self):
        """Audio thread: queue what's been recorded so far as a chunk."""
        import numpy as np
        chunks = self._drain_audio()
        self._chunk_frames = self._quiet_frames = 0
        if not chunks:
            return
        audio = np.concatenate(chunks, axis=0).flatten()
        duration = len(audio) / self.cfg["sample_rate"]
        audio = self._clean_audio(audio, bool(self.cfg.get("whisper_mode")))
        self._chunks_cut += 1
        self._work_q.put(("chunk", self._rec_gen, audio, duration))

    def _start_recording(self, mode="dictate"):
        """Open the mic and start capturing; True if recording. Called with
        _hk_lock held (see the hotkey state machine below)."""
        if self._recording:
            return True
        self._chunk_frames = self._quiet_frames = self._chunks_cut = 0
        self._speech_rms = 0.0
        self._recording = True
        self._recording_mode = mode
        self._rec_gen += 1
        self._warm_llm()
        if self._overlay:
            self._overlay.show()
        if self.feedback:
            self.feedback.beep()
        stream = None
        try:
            import sounddevice as sd
            stream = sd.InputStream(
                samplerate=self.cfg["sample_rate"],
                channels=1,
                dtype="float32",
                device=self.cfg["input_device"] or None,
                callback=self._audio_callback,
            )
            stream.start()
        except Exception as e:
            # No mic / device busy: say so and keep the hotkeys working
            # rather than letting the error kill the listener thread.
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            self._recording = False
            self._overlay_after_recording()
            print(f"omnihear: could not start recording: {e}")
            if self.feedback:
                self.feedback.notify("omnihear error",
                                     f"Could not start recording: {e}",
                                     urgency="normal")
            return False
        self._stream = stream
        # Safety cap, held or hands-free: stop and transcribe at the limit.
        self._max_timer = self._schedule(self._max_seconds,
                                         self._on_max_length, self._rec_gen)
        self._log("Recording...")
        return True

    def _overlay_transcribing(self):
        """Switch the indicator to its transcribing state (spinner + flowing
        wave), or just hide it on an overlay without one."""
        if not self._overlay:
            return
        fn = getattr(self._overlay, "show_transcribing", None)
        if fn:
            fn()
        else:
            self._overlay.hide()

    def _overlay_idle(self):
        if self._overlay:
            self._overlay.hide()

    def _overlay_after_recording(self):
        """A recording ended without queuing audio: back to the transcribing
        indicator if earlier audio is still being transcribed, else hide."""
        if self._transcribing:
            self._overlay_transcribing()
        else:
            self._overlay_idle()

    def _overlay_locked(self, flag):
        set_locked = getattr(self._overlay, "set_locked", None)
        if set_locked:
            set_locked(flag)

    def _end_recording(self):
        """Reset hands-free state and timers as a recording stops."""
        self._hk_state = "idle"
        self._locked = False
        self._overlay_locked(False)
        for timer in (self._tap_timer, self._max_timer):
            if timer is not None:
                timer.cancel()
        self._tap_timer = self._max_timer = None

    def _close_stream(self):
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            try:
                stream.stop()
            finally:
                stream.close()
        except Exception as e:   # e.g. the mic was unplugged mid-recording
            print(f"omnihear: warning: closing the audio stream failed: {e}")

    def _drain_audio(self):
        chunks = []
        while not self._audio_q.empty():
            chunks.append(self._audio_q.get())
        return chunks

    def _stop_recording(self):
        """Stop and queue the audio for transcription. Called with _hk_lock
        held."""
        import numpy as np
        if not self._recording:
            return
        self._recording = False
        self._end_recording()
        mode = self._recording_mode
        self._close_stream()

        chunks = self._drain_audio()
        audio, duration = None, 0.0
        if chunks:
            audio = np.concatenate(chunks, axis=0).flatten()
            duration = len(audio) / self.cfg["sample_rate"]
        if self._chunks_cut:
            # Earlier chunks are queued: always finish the recording, even
            # if the tail after the last pause is empty or too short.
            if duration < self.cfg["min_duration"]:
                audio, duration = None, 0.0
        elif audio is None:
            self._log("No audio captured.")
            self._overlay_after_recording()
            return
        elif duration < self.cfg["min_duration"]:
            self._log("Too short, ignoring.")
            self._overlay_after_recording()
            return

        if audio is not None:
            audio = self._clean_audio(audio, bool(self.cfg.get("whisper_mode")))
        self._log(f"Queued {duration:.2f}s of audio for transcription "
                  f"({self._chunks_cut} earlier chunk(s))...")
        # Recording -> transcribing; the worker clears it when done.
        self._overlay_transcribing()
        self._transcribing += 1
        self._work_q.put(("transcribe", audio, duration, mode, self._rec_gen))

    def _cancel_recording(self):
        """Discard the current recording without transcribing it (hands-free
        stray tap). Called with _hk_lock held."""
        if not self._recording:
            return
        self._recording = False
        self._end_recording()
        self._close_stream()
        self._drain_audio()
        self._overlay_after_recording()
        self._log("Single tap: recording discarded.")

    # -- hotkey state machine -------------------------------------------
    # The hotkey listener (pynput or evdev thread) and timers call in here;
    # _hk_lock serializes them. Hold-to-talk: press starts recording, release
    # stops and transcribes. Hands-free (cfg "hands_free") adds a lock:
    #   press shorter than TAP_SECONDS, released -> "armed": keep recording
    #     and wait DOUBLE_TAP_SECONDS for a second press
    #   second press while armed -> "locked": recording continues, key up
    #   no second press in time  -> a stray tap: discard the recording
    #   press while locked       -> stop and transcribe (its release is moot)
    # Every recording also gets a max_recording_seconds watchdog.
    def _schedule(self, delay, fn, *args):
        """Call fn(*args) after delay seconds on a daemon timer thread;
        cancel() the returned timer to drop the call."""
        timer = threading.Timer(delay, fn, args)
        timer.daemon = True
        timer.start()
        return timer

    def _on_hotkey_press(self, mode):
        now = time.monotonic()
        with self._hk_lock:
            if not self._recording:
                self._hold(mode, now)
            elif self._hk_state == "armed":
                if self._tap_timer is not None:
                    self._tap_timer.cancel()
                    self._tap_timer = None
                if mode == self._recording_mode:
                    self._hk_state = "locked"
                    self._locked = True
                    self._overlay_locked(True)
                    self._log("Hands-free: recording locked, tap to stop.")
                else:
                    # The other hotkey right after a stray tap: start over.
                    self._cancel_recording()
                    self._hold(mode, now)
            elif self._hk_state == "locked":
                self._stop_recording()
            # "held": key repeat or another hotkey while holding -- ignore,
            # and keep the original press time.

    def _hold(self, mode, now):
        if self._start_recording(mode):
            self._hk_state = "held"
            self._press_t = now

    def _on_hotkey_release(self, mode):
        now = time.monotonic()
        with self._hk_lock:
            if (not self._recording or self._hk_state != "held"
                    or mode != self._recording_mode):
                return
            if self.cfg.get("hands_free") and now - self._press_t < TAP_SECONDS:
                self._hk_state = "armed"
                self._tap_timer = self._schedule(
                    DOUBLE_TAP_SECONDS, self._on_tap_timeout, self._rec_gen)
            else:
                self._stop_recording()

    def _on_tap_timeout(self, gen):
        with self._hk_lock:
            if (gen == self._rec_gen and self._recording
                    and self._hk_state == "armed"):
                self._cancel_recording()

    def _on_max_length(self, gen):
        with self._hk_lock:
            if gen != self._rec_gen or not self._recording:
                return
            self._stop_recording()
        msg = (f"Recording reached the {self._max_seconds}s limit "
               "(max_recording_seconds); transcribing it.")
        print(f"omnihear: {msg}")
        if self.feedback:
            self.feedback.notify("omnihear", msg, urgency="normal")

    def _hotkey_bindings(self, combo, parse):
        """[(combo, on_press, on_release)] for the hotkey listener. combo is
        the parsed main hotkey; parse() turns the optional ask/paste-last
        hotkeys into the same key sets (pynput keys or evdev codes). One
        that is invalid or equal to a combo already bound is disabled."""
        bindings = [(combo,
                     self._guard_press(self.cfg.get("hotkey", ""),
                                       lambda: self._on_hotkey_press("dictate")),
                     lambda: self._on_hotkey_release("dictate"))]
        taken = {combo: "hotkey"}

        def extra(key, feature):
            name = self.cfg.get(key) or ""
            if not name:
                return None
            if key == "paste_last_hotkey" and config_mod.is_paste_shortcut(name):
                print(f"omnihear: {key} is your system paste shortcut "
                      f"({name}), {feature} disabled")
                return None
            try:
                parsed = parse(name)
            except ValueError as e:
                print(f"omnihear: invalid {key} ({e}), {feature} disabled")
                return None
            if parsed in taken:
                print(f"omnihear: {key} matches {taken[parsed]}, "
                      f"{feature} disabled")
                return None
            taken[parsed] = key
            return parsed

        ask = extra("ask_hotkey", "voice Q&A")
        if ask is not None:
            bindings.append((ask,
                             self._guard_press(self.cfg.get("ask_hotkey", ""),
                                               lambda: self._on_hotkey_press("ask")),
                             lambda: self._on_hotkey_release("ask")))
        cmd = extra("command_hotkey", "Command Mode")
        if cmd is not None:
            bindings.append((cmd,
                             self._guard_press(self.cfg.get("command_hotkey", ""),
                                               lambda: self._on_hotkey_press("command")),
                             lambda: self._on_hotkey_release("command")))
        paste = extra("paste_last_hotkey", "paste-last")
        if paste is not None:
            bindings.append((paste, self.paste_last, None))
        return bindings

    # -- paste last -------------------------------------------------------
    def paste_last(self):
        """Re-insert the last transcript at the cursor (paste-last hotkey;
        safe from any thread). Goes through the worker queue, so it lands
        after any transcriptions still pending."""
        self._work_q.put(("paste_last", time.monotonic()))

    def _paste_last_job(self, pressed_at):
        """Worker: put the last inserted text at the cursor again (never
        written to history)."""
        if self._insertion_echo(pressed_at):
            # Our own insertion pressed the hotkey (e.g. shift_l+v while
            # typing a "V", or this job's own paste): ignore it rather than
            # pasting again (or in a loop).
            return
        text = self._last_inserted
        if not text:
            if self.feedback:
                self.feedback.notify("omnihear", "Nothing to paste yet")
            return
        self._insert(text)
        self._last_typed_len = len(text)  # "undo" removes this insertion
        self._log("Pasted the last transcript again.")

    # -- transcription worker -----------------------------------------
    def _worker_loop(self):
        # The one worker runs every job in order: ("chunk", gen, audio,
        # duration) cut at pauses while recording (chunked_transcription),
        # ("transcribe", audio, duration, mode, gen) from _stop_recording
        # (audio is None when chunks already hold everything), and
        # ("paste_last", pressed_at) from the paste-last hotkey.
        while True:
            job = self._work_q.get()
            try:
                if job[0] == "paste_last":
                    self._paste_last_job(job[1])
                elif job[0] == "chunk":
                    self._chunk_job(*job[1:])
                else:
                    _, audio, duration, mode, gen = job
                    self._transcribe_one(audio, duration, mode, gen)
            except Exception as e:
                if job[0] == "transcribe":
                    self._chunk_acc.pop(job[4], None)
                what = "Paste-last" if job[0] == "paste_last" else "Transcription"
                print(f"{what} error: {e}")
                if self.feedback:
                    self.feedback.notify("omnihear error", str(e),
                                         urgency="normal")
            finally:
                if job[0] == "transcribe":
                    with self._hk_lock:
                        self._transcribing -= 1
                        # Clear the transcribing indicator once nothing is
                        # left to transcribe, unless a new recording is up.
                        if not self._transcribing and not self._recording:
                            self._overlay_idle()

    @staticmethod
    def _rss_mb():
        """Current process RSS in MB. /proc on Linux, getrusage on macOS,
        None where neither is available (e.g. Windows)."""
        if sys.platform == "darwin":
            try:
                import resource
                # ru_maxrss is bytes on macOS (KiB on Linux) — peak, not live,
                # but close enough for the dashboard's memory column.
                return round(
                    resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1)
            except (ImportError, ValueError):
                return None
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return round(int(line.split()[1]) / 1024, 1)
        except (OSError, ValueError, IndexError):
            pass
        return None

    def _rag_context_texts(self, query: str, limit: int) -> list[str]:
        """Best-effort keyword retrieval of relevant past transcriptions."""
        if not query or self.db is None:
            return []
        try:
            hits = self.db.search_relevant(query, limit=limit)
        except Exception as e:
            self._log(f"RAG context lookup failed: {e}")
            return []
        return [h["text"] for h in hits]

    def _vocab_hints(self) -> list[str]:
        """Words to bias Whisper towards: the personal dictionary (pinned
        first) and, with the beta Brain, its learned vocabulary."""
        words = []
        if self.personal is not None:
            try:
                words += self.personal.hint_words()
            except Exception as e:
                self._log(f"dictionary lookup failed: {e}")
        if self._brain_active() and self.cfg.get("brain_hotwords"):
            try:
                words += self.brain.top_words(50)
            except Exception as e:
                self._log(f"brain hints failed: {e}")
        seen, out = set(), []
        for w in words:
            if w.lower() not in seen:
                seen.add(w.lower())
                out.append(w)
        return out

    @staticmethod
    def _probe_app(box):
        from . import focus
        box.append(focus.active_app())

    # -- decoding -------------------------------------------------------
    def _decode(self, audio, language=None, extra_prompt=""):
        """Run Whisper on one piece of audio. Returns (text, segments, info).
        `language` overrides the configured one (a pinned chunk language);
        `extra_prompt` (the previous chunk's text) keeps chunks coherent."""
        model = self._get_model()
        auto = self.cfg["language"] in ("", "auto")
        if language is None and not auto:
            language = self.cfg["language"]
        whisper = bool(self.cfg.get("whisper_mode"))
        kwargs = dict(
            language=language,
            beam_size=self.cfg["beam_size"],
            vad_filter=self.cfg["vad_filter"],
            # Whisper mode: a segment is only dropped as silence when Whisper
            # is very sure, and quiet speech still passes the VAD.
            no_speech_threshold=(max(0.8, self.cfg["no_speech_threshold"])
                                 if whisper else self.cfg["no_speech_threshold"]),
            log_prob_threshold=(min(-1.5, self.cfg["log_prob_threshold"])
                                if whisper else self.cfg["log_prob_threshold"]),
            compression_ratio_threshold=self.cfg["compression_ratio_threshold"],
            condition_on_previous_text=self.cfg["condition_on_previous_text"],
        )
        if whisper and self.cfg["vad_filter"]:
            kwargs["vad_parameters"] = {"threshold": 0.3}
        if auto and language is None and self.cfg.get("code_switching"):
            # Per-segment language detection (faster-whisper >= 1.1).
            kwargs["multilingual"] = True
        prompt_parts = []
        vocab = self._vocab_hints()
        if vocab:
            kwargs["hotwords"] = " ".join(vocab[:50])
            prompt_parts.append(("Vocabulary: " + ", ".join(vocab[:20]) + ".")[:200])
        if extra_prompt:
            prompt_parts.append(extra_prompt[-200:])
        elif self.cfg.get("rag_context"):
            prompt_parts.extend(self._rag_context_texts(
                self._last_text, self.cfg.get("rag_context_limit", 3)))
        if prompt_parts:
            kwargs["initial_prompt"] = " ".join(prompt_parts)[:400]
        # Options an older faster-whisper doesn't know are dropped once and
        # remembered, newest first.
        for opt in self._unsupported_opts:
            kwargs.pop(opt, None)
        while True:
            try:
                segments, info = model.transcribe(audio, **kwargs)
                break
            except TypeError:
                opt = next((o for o in ("multilingual", "hotwords")
                            if o in kwargs), None)
                if opt is None:
                    raise
                self._unsupported_opts.add(opt)
                kwargs.pop(opt)
        segments = list(segments)
        return "".join(seg.text for seg in segments).strip(), segments, info

    def _chunk_job(self, gen, audio, duration):
        """Worker: transcribe a chunk cut at a pause while the user is still
        talking, and keep its text for the recording's final job."""
        t0 = time.monotonic()
        acc = self._chunk_acc.setdefault(gen, {
            "texts": [], "segments": [], "duration": 0.0, "elapsed": 0.0,
            "language": None})
        text, segments, info = self._decode(
            audio, language=acc["language"],
            extra_prompt=" ".join(acc["texts"]))
        if text:
            acc["texts"].append(text)
        acc["segments"] += segments
        acc["duration"] += duration
        acc["elapsed"] += time.monotonic() - t0
        # language = auto: pin what the first chunk detected for the rest of
        # this dictation (code_switching instead lets every chunk decide).
        if (acc["language"] is None and not self.cfg.get("code_switching")
                and self.cfg["language"] in ("", "auto")
                and getattr(info, "language_probability", 0) >= 0.6):
            acc["language"] = info.language
        self._log(f"chunk {len(acc['texts'])}: {duration:.1f}s -> {text!r}")

    def _transcribe_one(self, audio, duration, mode="dictate", gen=None):
        t0 = time.monotonic()
        cpu0 = time.process_time()
        # Which app will receive the text (per-app style, Insights). Probed
        # in parallel with transcription so it adds no latency.
        app_box = []
        app_probe = threading.Thread(target=self._probe_app, args=(app_box,),
                                     daemon=True)
        app_probe.start()
        acc = self._chunk_acc.pop(gen, None) if gen is not None else None
        texts, segments, language = [], [], None
        if acc:
            texts, segments, language = acc["texts"], acc["segments"], acc["language"]
            duration += acc["duration"]
            t0 -= acc["elapsed"]  # total transcription time for history
        info = None
        if audio is not None:
            tail, tail_segments, info = self._decode(
                audio, language=language, extra_prompt=" ".join(texts))
            if tail:
                texts = texts + [tail]
            segments = segments + tail_segments
        text = " ".join(texts).strip()
        lang = language or getattr(info, "language", None)

        app_probe.join(timeout=1.5)
        app_name = app_box[0] if app_box else None
        snippet = None  # expansion to insert instead of the spoken trigger
        if mode == "dictate":
            voice_cmds = self.cfg.get("voice_commands")
            if voice_cmds and text:
                from . import commands
                if commands.is_undo(text):
                    n, self._last_typed_len = self._last_typed_len, 0
                    if n:
                        self._backspace(n)
                        self._log(f"Undid last {n} chars")
                    return  # nothing typed, nothing logged to history

            if text and self.personal is not None:
                try:
                    snippet = self.personal.match_snippet(text)
                except Exception as e:
                    self._log(f"snippet lookup failed: {e}")

            resolved_cmd = None
            if (not snippet and self.cfg.get("terminal_commands") and text
                    and sys.platform not in ("win32", "darwin")):
                from . import linux_session, terminal_commands
                # xdotool window/cwd probes — X11 only.
                if not linux_session.is_wayland():
                    resolved_cmd = terminal_commands.translate(text)

            if snippet:
                pass  # history keeps the spoken trigger; the expansion is typed
            elif resolved_cmd:
                text = resolved_cmd  # bypass brain/punctuation -- it's a command, not prose
            else:
                level = self.cfg.get("cleanup", "off")
                if text and level != "off":
                    # fillers/stutters/self-corrections; "" if only "um"
                    from . import cleanup
                    text = cleanup.clean(text, level, lang)
                if text and level == "smart":
                    text = self._smart_cleanup(text, app_name)
                if text and self._brain_active() and self.cfg.get("brain_autocorrect"):
                    try:
                        text = self.brain.apply(text)
                    except Exception as e:
                        self._log(f"brain apply failed: {e}")
                if text and self.personal is not None:
                    # Dictionary spellings, then the focused app's style.
                    # Before spoken punctuation, so "period" said out loud
                    # survives a casual style.
                    try:
                        from .personal import apply_style
                        text = self.personal.apply_dictionary(text)
                        text = apply_style(
                            text, self.personal.style_for(app_name),
                            keep=self.personal.hint_words())
                    except Exception as e:
                        self._log(f"personalization failed: {e}")
                if voice_cmds and text:
                    from . import commands
                    text = commands.apply_punctuation(text)

        avg_logprob = no_speech_prob = compression_ratio = None
        if segments:
            n = len(segments)
            avg_logprob = sum(s.avg_logprob for s in segments) / n
            no_speech_prob = sum(s.no_speech_prob for s in segments) / n
            compression_ratio = sum(s.compression_ratio for s in segments) / n
            self._log(f"avg_logprob={avg_logprob:.3f} "
                      f"no_speech_prob={no_speech_prob:.3f} "
                      f"compression_ratio={compression_ratio:.3f}")
        wall = time.monotonic() - t0
        elapsed_ms = wall * 1000
        # Process CPU time spent during transcription as % of wall time
        # (can exceed 100 with multiple threads).
        cpu_percent = round((time.process_time() - cpu0) / wall * 100, 1) if wall > 0 else None
        memory_mb = self._rss_mb()
        self._last_used = time.monotonic()
        if not text:
            self._log("(empty transcription)")
            return
        self._log(f"-> {text}")

        typed_text = snippet or text
        suffix = " "
        if mode == "command":
            # `text` is the spoken instruction. With a selection, the
            # rewrite replaces it; with none, it behaves like voice Q&A.
            selection = self._grab_selection()
            if selection:
                rewritten = self._command_rewrite(text, selection)
                if rewritten is None:
                    typed_text = None  # leave the selection untouched
                else:
                    typed_text, suffix = rewritten, ""
            else:
                mode = "ask"
        if mode == "ask":
            # `text` here is the spoken question -- keep it as-is for history
            # and RAG (it's real dictation content), and type the generated
            # answer instead, falling back to the raw question if Ollama
            # isn't available.
            context = self._rag_context_texts(
                text, self.cfg.get("ask_context_limit", 5))
            try:
                from . import qna
                ans = qna.answer(text, context, self.cfg.get("ask_model", "llama3.2"))
            except Exception as e:
                ans = None
                self._log(f"qna failed: {e}")
            if ans:
                typed_text = ans
            else:
                self._log("qna unavailable, typing the raw question instead")

        if typed_text is not None:
            self._insert(typed_text + suffix)
            self._last_typed_len = len(typed_text) + len(suffix)
            if self.feedback:
                self.feedback.notify("omnihear", typed_text, urgency="normal")
        if self.db:
            try:
                self.db.insert(text, duration, elapsed_ms, self.cfg["model"],
                               cpu_percent=cpu_percent, memory_mb=memory_mb,
                               avg_logprob=avg_logprob, no_speech_prob=no_speech_prob,
                               compression_ratio=compression_ratio,
                               app=app_name)
            except Exception as e:
                print(f"History write failed: {e}")
        self._last_text = text
        try:
            from . import cloud
            cloud.track_activation()
        except Exception:
            pass

    # -- local AI editing (llm.py) ---------------------------------------
    def _llm_model(self):
        """Instruction-following model: Command Mode and voice Q&A."""
        from . import llm
        return self.cfg.get("ask_model") or llm.DEFAULT_ASSIST_MODEL

    def _cleanup_model(self):
        """Smart cleanup's model (a dictation-cleanup fine-tune by default)."""
        from . import llm
        return self.cfg.get("cleanup_model") or llm.DEFAULT_CLEANUP_MODEL

    def _models_to_warm(self):
        # Only what this recording will use, so a plain dictation doesn't
        # also keep the Command Mode model in RAM.
        if self._recording_mode == "dictate":
            return ([self._cleanup_model()]
                    if self.cfg.get("cleanup") == "smart" else [])
        return [self._llm_model()]  # "ask" / "command"

    def _warm_llm(self):
        """Pre-load the Ollama model(s) this recording may need, in the
        background, so the first edit isn't a cold start."""
        models = self._models_to_warm()
        if not models:
            return

        def warm():
            try:
                from . import llm
                for m in dict.fromkeys(models):
                    llm.warm(m)
            except Exception:
                pass
        threading.Thread(target=warm, daemon=True).start()

    def _smart_cleanup(self, text, app_name=None):
        """cleanup = "smart": an LLM polish within smart_cleanup_ms; the
        rule-cleaned text if it's short, slow, unavailable or implausible.
        Line breaks (the model formats dictated lists) are only accepted
        where the app's style is "document" -- elsewhere Enter may send."""
        from . import llm
        budget = self.cfg.get("smart_cleanup_ms", 1500) / 1000
        allow_newlines = False
        if self.personal is not None:
            try:
                allow_newlines = self.personal.style_for(app_name) == "document"
            except Exception:
                pass
        t0 = time.monotonic()
        try:
            out = llm.polish(text, self._cleanup_model(), budget, app=app_name,
                             allow_newlines=allow_newlines)
        except Exception as e:
            out = None
            self._log(f"smart cleanup failed: {e}")
        self._log(f"smart cleanup {'applied' if out else 'skipped'} "
                  f"({(time.monotonic() - t0) * 1000:.0f} ms)")
        return out or text

    def _command_rewrite(self, instruction, selection):
        from . import llm
        try:
            out = llm.rewrite(instruction, selection, self._llm_model())
        except Exception as e:
            out = None
            self._log(f"command rewrite failed: {e}")
        if out is None:
            msg = ("Command Mode needs Ollama running locally "
                   f"(model {self._llm_model()}); the selection was left "
                   "unchanged.")
            print(f"omnihear: {msg}")
            if self.feedback:
                self.feedback.notify("omnihear", msg, urgency="normal")
        return out

    _SELECTION_WAIT = 0.5  # s to wait for the app to answer the copy key

    def _grab_selection(self):
        """The focused app's selected text, or None. Puts a marker on the
        clipboard, sends the copy key (Ctrl+Insert on Linux, Ctrl+C on
        Windows, Cmd+C on macOS) and reads the clipboard back: if the marker
        is still there, nothing was selected. The user's clipboard text is
        put back afterwards."""
        from . import clipboard
        if clipboard.backend() is None:
            return None
        clip_lock = getattr(self, "_clip_lock", None)
        if clip_lock is not None:
            clip_lock.acquire()
        try:
            if getattr(self, "_clip_ours", None) is not None:
                # A paste's restore is pending: the clipboard holds our
                # dictation, the user's own text is in _clip_saved.
                saved = self._clip_saved[0]
                self._clip_saved, self._clip_ours = (None, None), None
            else:
                saved = clipboard.get_text()
            marker = f"⁣omnihear-selection-{time.monotonic_ns()}"
            if not clipboard.set_text(marker, primary=False):
                return None
            time.sleep(self._PASTE_SETTLE)
            self._inserting = True  # our own keys: keep hotkeys from firing
            start = time.monotonic()
            try:
                sent = self._chord("copy")
            finally:
                self._insert_window = (start, time.monotonic())
                self._inserting = False
            got = None
            deadline = time.monotonic() + self._SELECTION_WAIT
            while sent and time.monotonic() < deadline:
                time.sleep(0.03)
                cur = clipboard.get_text()
                if cur is not None and cur != marker:
                    got = cur
                    break
            clipboard.set_text(saved if saved is not None else "",
                               primary=False)
            return got if got and got.strip() else None
        finally:
            if clip_lock is not None:
                clip_lock.release()

    # -- main loop -----------------------------------------------------
    def run(self):
        from . import linux_session

        self._setup_insertion()

        if linux_session.is_wayland():
            for hint in linux_session.missing_wayland_deps(
                    self.cfg.get("type_method") or "auto"):
                print(f"omnihear: Wayland setup: {hint}")
            if self.cfg.get("terminal_commands"):
                print("omnihear: terminal_commands needs X11/xdotool — "
                      "disabled on Wayland")

        ask_hotkey = self.cfg.get("ask_hotkey") or ""
        paste_last = self.cfg.get("paste_last_hotkey") or ""
        threading.Thread(target=self._worker_loop, daemon=True).start()
        threading.Thread(target=self._idle_unload_loop, daemon=True).start()

        print(f"Hold '{config_mod.hotkey_display(self.cfg['hotkey'])}' to "
              "record, release to transcribe & type. Ctrl+C to quit.")
        if self.cfg.get("hands_free"):
            print("Hands-free (beta): double-tap it to keep recording without "
                  "holding, then tap once more to stop.")
        if ask_hotkey:
            print(f"Hold '{config_mod.hotkey_display(ask_hotkey)}' to ask a "
                  "question (voice Q&A, beta).")
        if paste_last:
            print(f"Press '{config_mod.hotkey_display(paste_last)}' to paste "
                  "the last transcript again.")
        if self._max_seconds != self.cfg.get("max_recording_seconds", 300):
            print("omnihear: max_recording_seconds must be 10-3600, using "
                  f"{self._max_seconds}")
        print("Model loads lazily on first press; first transcription "
              "after load takes a few extra seconds.")

        if linux_session.is_wayland():
            self._run_evdev()
        else:
            self._run_pynput()

    def _run_pynput(self):
        from pynput import keyboard
        from .evdev_hotkey import ComboMatcher

        combo = parse_hotkey(self.cfg["hotkey"])
        if self._type_method == "pynput":
            self._kb_controller = keyboard.Controller()

        matcher = ComboMatcher(self._hotkey_bindings(combo, parse_hotkey))

        def canonical(key):
            # Undo modifiers on character keys so a combo like
            # ctrl_l+shift_l+v matches: X11/macOS report 'V' while Shift is
            # held, Windows reports Ctrl+V as the control character '\x16'.
            # (evdev matches raw keycodes, so both backends now agree.)
            char = getattr(key, "char", None)
            if not char or len(char) != 1:
                return key
            if "\x01" <= char <= "\x1a":
                char = chr(ord(char) + 0x60)
            return keyboard.KeyCode.from_char(char.lower())

        def on_press(key):
            matcher.press(canonical(key))

        def on_release(key):
            matcher.release(canonical(key))

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        with self._listener as listener:
            listener.join()

    def _run_evdev(self):
        from . import evdev_hotkey

        try:
            combo = evdev_hotkey.parse_hotkey_codes(self.cfg["hotkey"])
        except ValueError as e:
            raise SystemExit(f"omnihear: invalid hotkey for Wayland: {e}") from e

        monitor = evdev_hotkey.HotkeyMonitor(
            self._hotkey_bindings(combo, evdev_hotkey.parse_hotkey_codes))
        self._listener = monitor
        with monitor:
            # Keep the main thread alive so Ctrl+C works; the monitor
            # thread owns the select() loop.
            try:
                while monitor._thread is not None and monitor._thread.is_alive():
                    monitor._thread.join(timeout=0.5)
            except KeyboardInterrupt:
                monitor.stop()

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
        # Drop pending hands-free/watchdog timers. No lock here: stop() must
        # never block (the tray's force-exit timer starts after it returns).
        for timer in (self._tap_timer, self._max_timer):
            if timer is not None:
                timer.cancel()


def list_devices():
    import sounddevice as sd
    print(sd.query_devices())
    sys.exit(0)


if __name__ == "__main__":
    import numpy as np

    sr = 16000
    t = np.linspace(0, 1, sr, dtype=np.float32)
    tone = 0.02 * np.sin(2 * np.pi * 440 * t)  # quiet 440Hz tone
    silence = np.zeros(sr // 2, dtype=np.float32)
    audio = np.concatenate([silence, tone, silence])

    cleaned = App._clean_audio(audio)
    assert len(cleaned) < len(audio), "should trim silent edges"
    assert 0.85 <= np.abs(cleaned).max() <= 0.95, "should normalize peak near 0.9"

    assert App._clean_audio(np.zeros(100, dtype=np.float32)).size == 100  # no-op on pure silence

    print("app self-check OK")
