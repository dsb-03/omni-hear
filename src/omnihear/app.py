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
    Windows). Listening: red dot + waveform that follows the live mic level.
    Transcribing: amber spinner + flowing wave. Drawing comes from the shared
    model in overlay_anim.py, which the macOS overlay uses too.

    show()/show_transcribing()/hide() are called from any thread and queued
    to the Tk thread; set_level() is called from the audio callback.
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
                canvas.itemconfigure(dot, state="normal", fill=oa.to_hex(d.color))
                canvas.itemconfigure(track, state="hidden")
                canvas.itemconfigure(spinner, state="hidden")
            else:
                canvas.itemconfigure(halo, state="hidden")
                canvas.itemconfigure(dot, state="hidden")
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
        if self.thread.is_alive():
            self.queue.put("hide")

    def set_level(self, rms: float):
        """Live mic level (block RMS) from the audio callback thread."""
        self.anim.set_level(rms)


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
    def _insert(self, text):
        """Put text at the cursor. Single entry point for every insertion
        (dictation, Q&A answers, paste-last), so insertion strategy
        (typing vs. clipboard paste) lives in one place."""
        self._type_text(text)
        self._last_inserted = text

    def _type_text(self, text):
        method = self._type_method
        if method in linux_session_methods():
            from . import linux_session
            linux_session.type_text(method, text)
            return
        self._kb_controller.type(text)

    def _backspace(self, n):
        """Erase the last n characters typed via _type_text."""
        if n <= 0:
            return
        method = self._type_method
        if method in linux_session_methods():
            from . import linux_session
            linux_session.backspace(method, n)
            return
        from pynput.keyboard import Key
        for _ in range(n):
            self._kb_controller.press(Key.backspace)
            self._kb_controller.release(Key.backspace)

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
        import sounddevice as sd
        if self._recording:
            return
        self._recording = True
        self._recording_mode = mode
        if self._overlay:
            self._overlay.show()
        if self.feedback:
            self.feedback.beep()
        stream = sd.InputStream(
            samplerate=self.cfg["sample_rate"],
            channels=1,
            dtype="float32",
            device=self.cfg["input_device"] or None,
            callback=self._audio_callback,
        )
        stream.start()
        self._stream = stream
        self._log("Recording...")

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

    def _stop_recording(self):
        import numpy as np
        if not self._recording:
            return
        self._recording = False
        mode = self._recording_mode
        stream = self._stream
        stream.stop()
        stream.close()

        chunks = []
        while not self._audio_q.empty():
            chunks.append(self._audio_q.get())
        if not chunks:
            self._log("No audio captured.")
            self._overlay_idle()
            return
        audio = np.concatenate(chunks, axis=0).flatten()

        duration = len(audio) / self.cfg["sample_rate"]
        if duration < self.cfg["min_duration"]:
            self._log("Too short, ignoring.")
            self._overlay_idle()
            return

        audio = self._clean_audio(audio)
        self._log(f"Queued {duration:.2f}s of audio for transcription...")
        # Recording -> transcribing; the worker clears it when done.
        self._overlay_transcribing()
        self._work_q.put((audio, duration, mode))

    # -- transcription worker -----------------------------------------
    def _worker_loop(self):
        while True:
            audio, duration, mode = self._work_q.get()
            try:
                self._transcribe_one(audio, duration, mode)
            except Exception as e:
                print(f"Transcription error: {e}")
                if self.feedback:
                    self.feedback.notify("omnihear error", str(e),
                                         urgency="normal")
            finally:
                # Clear the transcribing indicator once the queue drains.
                if self._work_q.empty():
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
            segments, _ = model.transcribe(audio, **kwargs)
        except TypeError:
            # older faster-whisper without hotwords support
            self._hotwords_supported = False
            kwargs.pop("hotwords", None)
            segments, _ = model.transcribe(audio, **kwargs)
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

        configured_type = self.cfg.get("type_method") or "auto"
        self._type_method = linux_session.resolve_type_method(configured_type)
        if (sys.platform not in ("win32", "darwin")
                and self._type_method != configured_type):
            print(f"omnihear: using type_method={self._type_method} "
                  f"(config had {configured_type!r}, "
                  f"session={linux_session.session_type()})")

        if linux_session.is_wayland():
            for hint in linux_session.missing_wayland_deps(
                    self.cfg.get("type_method") or "auto"):
                print(f"omnihear: Wayland setup: {hint}")
            if self.cfg.get("terminal_commands"):
                print("omnihear: terminal_commands needs X11/xdotool — "
                      "disabled on Wayland")

        ask_hotkey = self.cfg.get("ask_hotkey") or ""
        threading.Thread(target=self._worker_loop, daemon=True).start()
        threading.Thread(target=self._idle_unload_loop, daemon=True).start()

        print(f"Hold '{config_mod.hotkey_display(self.cfg['hotkey'])}' to "
              "record, release to transcribe & type. Ctrl+C to quit.")
        if ask_hotkey:
            print(f"Hold '{config_mod.hotkey_display(ask_hotkey)}' to ask a "
                  "question (voice Q&A, beta).")
        print("Model loads lazily on first press; first transcription "
              "after load takes a few extra seconds.")

        if linux_session.is_wayland():
            self._run_evdev(ask_hotkey)
        else:
            self._run_pynput(ask_hotkey)

    def _run_pynput(self, ask_hotkey: str):
        from pynput import keyboard

        combo = parse_hotkey(self.cfg["hotkey"])
        if self._type_method == "pynput":
            self._kb_controller = keyboard.Controller()

        ask_combo = None
        if ask_hotkey:
            try:
                ask_combo = parse_hotkey(ask_hotkey)
            except ValueError as e:
                print(f"omnihear: invalid ask_hotkey ({e}), voice Q&A disabled")
            if ask_combo == combo:
                print("omnihear: ask_hotkey matches hotkey, voice Q&A disabled")
                ask_combo = None

        pressed = set()

        def on_press(key):
            if key not in combo and (ask_combo is None or key not in ask_combo):
                return
            pressed.add(key)
            if pressed == combo:
                self._start_recording("dictate")
            elif ask_combo is not None and pressed == ask_combo:
                self._start_recording("ask")

        def on_release(key):
            if key not in combo and (ask_combo is None or key not in ask_combo):
                return
            pressed.discard(key)
            self._stop_recording()

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        with self._listener as listener:
            listener.join()

    def _run_evdev(self, ask_hotkey: str):
        from . import evdev_hotkey

        try:
            combo = evdev_hotkey.parse_hotkey_codes(self.cfg["hotkey"])
        except ValueError as e:
            raise SystemExit(f"omnihear: invalid hotkey for Wayland: {e}") from e

        ask_combo = None
        if ask_hotkey:
            try:
                ask_combo = evdev_hotkey.parse_hotkey_codes(ask_hotkey)
            except ValueError as e:
                print(f"omnihear: invalid ask_hotkey ({e}), voice Q&A disabled")
            if ask_combo == combo:
                print("omnihear: ask_hotkey matches hotkey, voice Q&A disabled")
                ask_combo = None

        monitor = evdev_hotkey.HotkeyMonitor(
            combo,
            on_dictate_start=lambda: self._start_recording("dictate"),
            on_stop=self._stop_recording,
            ask_combo=ask_combo,
            on_ask_start=(lambda: self._start_recording("ask")) if ask_combo else None,
        )
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
