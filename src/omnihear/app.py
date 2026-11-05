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


class RecordingOverlay:
    """Floating pill bottom-centre of the screen (Tk: Linux X11/XWayland and
    Windows). Listening: red dot + waveform that follows the live mic level;
    the dot becomes a rounded stop square while hands-free recording is
    locked. Transcribing: amber spinner + flowing wave. Drawing comes from
    the shared model in overlay_anim.py, which the macOS overlay uses too.

    show()/show_transcribing()/hide() are called from any thread and queued
    to the Tk thread; set_level() is called from the audio callback and
    set_locked() from any thread (both just set model attributes).
    """

    _ALPHA = 0.94

    def __init__(self):
        from .overlay_anim import OverlayAnimation
        self.anim = OverlayAnimation()
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

        # Bottom-centre, just above the taskbar/dock: near where you look
        # while typing.
        w, h = oa.PILL_W, oa.PILL_H
        try:
            x = (root.winfo_screenwidth() - w) // 2
            y = root.winfo_screenheight() - h - 90
            root.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            root.geometry(f"{w}x{h}+900+900")

        bg = oa.to_hex(oa.BG)
        window_bg = bg
        outline = ""
        if sys.platform == "win32":
            # A colour key makes everything outside the pill transparent, so
            # Windows gets real rounded ends. Plain Tk on X11 has no window
            # shaping; there the pill fills a small dark rectangle.
            key = "#010203"
            try:
                root.attributes("-transparentcolor", key)
                window_bg = key
                outline = oa.to_hex(oa.EDGE)
            except tk.TclError:
                pass
        root.configure(bg=window_bg)

        canvas = tk.Canvas(root, width=w, height=h, bg=window_bg,
                           highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_polygon(_pill_points(0.5, 0.5, w - 0.5, h - 0.5, h / 2),
                              smooth=True, fill=bg, outline=outline)

        cx, cy = oa.DOT_CX, h / 2
        sr = oa.SPINNER_R
        halo = canvas.create_oval(0, 0, 0, 0, fill=bg, outline="")
        dot = canvas.create_oval(cx - oa.DOT_R, cy - oa.DOT_R,
                                 cx + oa.DOT_R, cy + oa.DOT_R,
                                 fill=oa.to_hex(oa.REC), outline="")
        s = oa.STOP_HALF
        stop_sq = canvas.create_polygon(
            _pill_points(cx - s, cy - s, cx + s, cy + s, oa.STOP_CORNER),
            smooth=True, fill=oa.to_hex(oa.REC), outline="", state="hidden")
        track = canvas.create_oval(cx - sr, cy - sr, cx + sr, cy + sr, width=2,
                                   outline=oa.to_hex(oa.mix(oa.BUSY, oa.BG, 0.75)),
                                   state="hidden")
        spinner = canvas.create_arc(cx - sr, cy - sr, cx + sr, cy + sr,
                                    start=90, extent=110, style="arc", width=2,
                                    outline=oa.to_hex(oa.BUSY), state="hidden")
        bars = [canvas.create_line(oa.bar_x(i), cy, oa.bar_x(i), cy,
                                   width=oa.BAR_W, capstyle="round",
                                   fill=oa.to_hex(oa.BAR))
                for i in range(oa.N_BARS)]

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
                    fill=oa.to_hex(oa.mix(d.color, oa.BG, 1.0 - d.halo_alpha)))
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
                # Round caps add BAR_W/2 at each end of the line.
                half = max(0.25, (bh - oa.BAR_W) / 2)
                x = oa.bar_x(i)
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
                target = 0.0 if st["closing"] else self._ALPHA
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
    def __init__(self, cfg: dict, db=None, feedback=None, brain=None):
        self.cfg = cfg
        self.db = db
        self.feedback = feedback
        self.brain = brain
        self._hotwords_supported = True  # cleared if faster-whisper is too old

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
                self._overlay = MacOverlay()
            else:
                self._overlay = RecordingOverlay()
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
        """Send the paste key through the key backend: Shift+Insert on Linux
        (see linux_session.paste_chord), Ctrl+V on Windows, Cmd+V on macOS.
        True if it was sent."""
        method = self._type_method
        if method in linux_session_methods():
            from . import linux_session
            return linux_session.paste_chord(method)
        try:
            from pynput.keyboard import Key, KeyCode
            if sys.platform == "darwin":
                mod, key = Key.cmd, KeyCode.from_char("v")
            elif sys.platform == "win32":
                # VK_V by code, so non-Latin layouts still send Ctrl+V.
                mod, key = Key.ctrl, KeyCode.from_vk(0x56)
            else:
                mod, key = Key.shift, Key.insert
            kb = self._kb()
            with kb.pressed(mod):
                kb.press(key)
                kb.release(key)
        except Exception as e:
            self._log(f"paste key failed: {e}")
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
    def _clean_audio(audio):
        """Trim near-silent edges and normalize peak amplitude. vad_filter
        (faster-whisper) handles silence *segmentation* during decoding but
        not input *level* -- a quiet mic can still skew the no_speech_prob/
        avg_logprob confidence thresholds, which normalization fixes."""
        import numpy as np
        threshold = 0.01  # ponytail: fixed energy gate, revisit if quiet speech gets clipped
        loud = np.where(np.abs(audio) > threshold)[0]
        if loud.size:
            audio = audio[loud[0]:loud[-1] + 1]
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
        self._last_rms = rms
        set_level = self._overlay_level
        if set_level is not None:
            try:
                set_level(rms)
            except Exception:
                pass

    def _start_recording(self, mode="dictate"):
        """Open the mic and start capturing; True if recording. Called with
        _hk_lock held (see the hotkey state machine below)."""
        if self._recording:
            return True
        self._recording = True
        self._recording_mode = mode
        self._rec_gen += 1
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
        if not chunks:
            self._log("No audio captured.")
            self._overlay_after_recording()
            return
        audio = np.concatenate(chunks, axis=0).flatten()

        duration = len(audio) / self.cfg["sample_rate"]
        if duration < self.cfg["min_duration"]:
            self._log("Too short, ignoring.")
            self._overlay_after_recording()
            return

        audio = self._clean_audio(audio)
        self._log(f"Queued {duration:.2f}s of audio for transcription...")
        # Recording -> transcribing; the worker clears it when done.
        self._overlay_transcribing()
        self._transcribing += 1
        self._work_q.put(("transcribe", audio, duration, mode))

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
        # The one worker runs every job in order: ("transcribe", audio,
        # duration, mode) from _stop_recording and ("paste_last", pressed_at)
        # from the paste-last hotkey.
        while True:
            job = self._work_q.get()
            try:
                if job[0] == "paste_last":
                    self._paste_last_job(job[1])
                else:
                    _, audio, duration, mode = job
                    self._transcribe_one(audio, duration, mode)
            except Exception as e:
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

    def _transcribe_one(self, audio, duration, mode="dictate"):
        model = self._get_model()
        t0 = time.monotonic()
        cpu0 = time.process_time()
        language = self.cfg["language"]
        if language in ("", "auto"):
            language = None  # let faster-whisper auto-detect
        kwargs = dict(
            language=language,
            beam_size=self.cfg["beam_size"],
            vad_filter=self.cfg["vad_filter"],
            no_speech_threshold=self.cfg["no_speech_threshold"],
            log_prob_threshold=self.cfg["log_prob_threshold"],
            compression_ratio_threshold=self.cfg["compression_ratio_threshold"],
            condition_on_previous_text=self.cfg["condition_on_previous_text"],
        )
        prompt_parts = []
        if self._brain_active() and self.cfg.get("brain_hotwords"):
            if self._hotwords_supported:
                kwargs["hotwords"] = self.brain.hotwords()
            bp = self.brain.initial_prompt()
            if bp:
                prompt_parts.append(bp)
        if self.cfg.get("rag_context"):
            prompt_parts.extend(self._rag_context_texts(
                self._last_text, self.cfg.get("rag_context_limit", 3)))
        if prompt_parts:
            kwargs["initial_prompt"] = " ".join(prompt_parts)[:400]
        try:
            segments, info = model.transcribe(audio, **kwargs)
        except TypeError:
            # older faster-whisper without hotwords support
            self._hotwords_supported = False
            kwargs.pop("hotwords", None)
            segments, info = model.transcribe(audio, **kwargs)
        segments = list(segments)
        text = "".join(seg.text for seg in segments).strip()

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

            resolved_cmd = None
            if (self.cfg.get("terminal_commands") and text
                    and sys.platform not in ("win32", "darwin")):
                from . import linux_session, terminal_commands
                # xdotool window/cwd probes — X11 only.
                if not linux_session.is_wayland():
                    resolved_cmd = terminal_commands.translate(text)

            if resolved_cmd:
                text = resolved_cmd  # bypass brain/punctuation -- it's a command, not prose
            else:
                if text and self.cfg.get("cleanup", "off") != "off":
                    # fillers/stutters/self-corrections; "" if only "um"
                    from . import cleanup
                    text = cleanup.clean(text, self.cfg["cleanup"],
                                         getattr(info, "language", None))
                if text and self._brain_active() and self.cfg.get("brain_autocorrect"):
                    try:
                        text = self.brain.apply(text)
                    except Exception as e:
                        self._log(f"brain apply failed: {e}")
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

        typed_text = text
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

        self._insert(typed_text + " ")
        self._last_typed_len = len(typed_text) + 1
        if self.feedback:
            self.feedback.notify("omnihear", typed_text, urgency="normal")
        if self.db:
            try:
                self.db.insert(text, duration, elapsed_ms, self.cfg["model"],
                               cpu_percent=cpu_percent, memory_mb=memory_mb,
                               avg_logprob=avg_logprob, no_speech_prob=no_speech_prob,
                               compression_ratio=compression_ratio)
            except Exception as e:
                print(f"History write failed: {e}")
        self._last_text = text
        try:
            from . import cloud
            cloud.track_activation()
        except Exception:
            pass

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
