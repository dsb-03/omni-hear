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


class RecordingOverlay:
    def __init__(self):
        self.root = None
        self.queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            import tkinter as tk
        except ImportError:
            return

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        
        w, h = 100, 100
        try:
            screen_w = self.root.winfo_screenwidth()
            x = screen_w - w - 20
            y = 20
            self.root.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            self.root.geometry(f"{w}x{h}+1800+20")
            
        self.root.configure(bg="#1a1a19")
        try:
            self.root.attributes("-alpha", 0.95)
        except Exception:
            pass

        self.canvas = tk.Canvas(self.root, width=w, height=h, bg="#1a1a19", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        def create_rounded_rect(x1, y1, x2, y2, r, **kwargs):
            self.canvas.create_rectangle(x1+r, y1, x2-r, y2, width=0, **kwargs)
            self.canvas.create_rectangle(x1, y1+r, x2, y2-r, width=0, **kwargs)
            self.canvas.create_oval(x1, y1, x1+2*r, y1+2*r, width=0, **kwargs)
            self.canvas.create_oval(x2-2*r, y1, x2, y1+2*r, width=0, **kwargs)
            self.canvas.create_oval(x1, y2-2*r, x1+2*r, y2, width=0, **kwargs)
            self.canvas.create_oval(x2-2*r, y2-2*r, x2, y2, width=0, **kwargs)

        create_rounded_rect(18, 18, 82, 82, 10, fill="#2c3e50")
        self.pulse_ring = self.canvas.create_oval(14, 14, 86, 86, outline="#3498db", width=2)

        def bezier_points(p0, p1, p2, p3, steps=15):
            pts = []
            for i in range(steps + 1):
                t = i / steps
                x = (1-t)**3 * p0[0] + 3*(1-t)**2 * t * p1[0] + 3*(1-t) * t**2 * p2[0] + t**3 * p3[0]
                y = (1-t)**3 * p0[1] + 3*(1-t)**2 * t * p1[1] + 3*(1-t) * t**2 * p2[1] + t**3 * p3[1]
                pts.append((x, y))
            return pts

        pts = []
        pts.extend(bezier_points((30, 50), (34, 42), (38, 42), (42, 50)))
        pts.extend(bezier_points((42, 50), (46, 58), (50, 58), (54, 50))[1:])
        pts.extend(bezier_points((54, 50), (58, 38), (62, 38), (66, 50))[1:])
        
        flat_pts = []
        for p in pts:
            flat_pts.extend(p)

        self.canvas.create_line(flat_pts, fill="#26c6da", width=5, capstyle="round", joinstyle="round")

        r = 2.4
        self.canvas.create_oval(30-r, 50-r, 30+r, 50+r, fill="#3498db", width=0)
        self.canvas.create_oval(70-r, 50-r, 70+r, 50+r, fill="#2ecc71", width=0)

        self.canvas.create_text(50, 92, text="LISTENING", fill="#dde5ef", font=("Sans", 7, "bold"))

        self.root.withdraw()
        self.visible = False
        self.anim_step = 0
        
        def animate():
            if self.visible:
                self.anim_step = (self.anim_step + 1) % 20
                scale = 14 + (self.anim_step % 10) * 0.4
                self.canvas.coords(self.pulse_ring, 50-scale, 50-scale, 50+scale, 50+scale)
                color = "#3498db" if (self.anim_step // 10) == 0 else "#2ecc71"
                self.canvas.itemconfig(self.pulse_ring, outline=color)
            if self.root:
                self.root.after(80, animate)

        def check_queue():
            try:
                while not self.queue.empty():
                    action = self.queue.get_nowait()
                    if action == "show":
                        self.visible = True
                        self.root.deiconify()
                    elif action == "hide":
                        self.visible = False
                        self.root.withdraw()
            except Exception:
                pass
            if self.root:
                self.root.after(50, check_queue)

        self.root.after(50, check_queue)
        self.root.after(80, animate)
        self.root.mainloop()

    def show(self):
        if self.thread.is_alive():
            self.queue.put("show")

    def hide(self):
        if self.thread.is_alive():
            self.queue.put("hide")


class App:
    def __init__(self, cfg: dict, db=None, feedback=None):
        self.cfg = cfg
        self.db = db
        self.feedback = feedback

        self._model = None
        self._model_lock = threading.Lock()
        self._last_used = time.monotonic()

        self._audio_q = queue.Queue()
        self._work_q = queue.Queue()
        self._recording = False
        self._stream = None
        self._verbose = bool(cfg.get("verbose"))
        self._overlay = None
        try:
            self._overlay = RecordingOverlay()
        except Exception as e:
            print(f"omnihear: warning: overlay could not start: {e}")

    def _log(self, msg):
        """Per-transcription chatter; printed only with --verbose."""
        if self._verbose:
            print(msg)

    # -- status for the dashboard ------------------------------------
    def status(self) -> dict:
        return {
            "model": self.cfg["model"],
            "hotkey": self.cfg["hotkey"],
            "hotkey_display": config_mod.hotkey_display(self.cfg["hotkey"]),
            "model_loaded": self._model is not None,
            "recording": self._recording,
        }

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
    def _type_text(self, text):
        if self.cfg["type_method"] == "xdotool":
            import subprocess
            subprocess.run(["xdotool", "type", "--clearmodifiers", "--", text])
        else:
            self._kb_controller.type(text)

    # -- recording ----------------------------------------------------
    def _audio_callback(self, indata, frames_count, time_info, status):
        if status:
            print(status)
        self._audio_q.put(indata.copy())

    def _start_recording(self):
        import sounddevice as sd
        if self._recording:
            return
        self._recording = True
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

    def _stop_recording(self):
        import numpy as np
        if not self._recording:
            return
        self._recording = False
        if self._overlay:
            self._overlay.hide()
        stream = self._stream
        stream.stop()
        stream.close()

        chunks = []
        while not self._audio_q.empty():
            chunks.append(self._audio_q.get())
        if not chunks:
            self._log("No audio captured.")
            return
        audio = np.concatenate(chunks, axis=0).flatten()

        duration = len(audio) / self.cfg["sample_rate"]
        if duration < self.cfg["min_duration"]:
            self._log("Too short, ignoring.")
            return

        self._log(f"Queued {duration:.2f}s of audio for transcription...")
        self._work_q.put((audio, duration))

    # -- transcription worker -----------------------------------------
    def _worker_loop(self):
        while True:
            audio, duration = self._work_q.get()
            try:
                self._transcribe_one(audio, duration)
            except Exception as e:
                print(f"Transcription error: {e}")
                if self.feedback:
                    self.feedback.notify("omnihear error", str(e),
                                         urgency="normal")

    @staticmethod
    def _rss_mb():
        """Current process RSS in MB, read from /proc (Linux); None elsewhere."""
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return round(int(line.split()[1]) / 1024, 1)
        except (OSError, ValueError, IndexError):
            pass
        return None

    def _transcribe_one(self, audio, duration):
        model = self._get_model()
        t0 = time.monotonic()
        cpu0 = time.process_time()
        language = self.cfg["language"]
        if language in ("", "auto"):
            language = None  # let faster-whisper auto-detect
        segments, _ = model.transcribe(
            audio,
            language=language,
            beam_size=self.cfg["beam_size"],
            vad_filter=self.cfg["vad_filter"],
            no_speech_threshold=self.cfg["no_speech_threshold"],
            log_prob_threshold=self.cfg["log_prob_threshold"],
            compression_ratio_threshold=self.cfg["compression_ratio_threshold"],
            condition_on_previous_text=self.cfg["condition_on_previous_text"],
        )
        segments = list(segments)
        text = "".join(seg.text for seg in segments).strip()
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
        self._type_text(text + " ")
        if self.feedback:
            self.feedback.notify("omnihear", text)
        if self.db:
            try:
                self.db.insert(text, duration, elapsed_ms, self.cfg["model"],
                               cpu_percent=cpu_percent, memory_mb=memory_mb,
                               avg_logprob=avg_logprob, no_speech_prob=no_speech_prob,
                               compression_ratio=compression_ratio)
            except Exception as e:
                print(f"History write failed: {e}")

    # -- main loop -----------------------------------------------------
    def run(self):
        from pynput import keyboard

        combo = parse_hotkey(self.cfg["hotkey"])
        self._kb_controller = keyboard.Controller()

        threading.Thread(target=self._worker_loop, daemon=True).start()
        threading.Thread(target=self._idle_unload_loop, daemon=True).start()

        pressed = set()

        def on_press(key):
            if key in combo:
                pressed.add(key)
                if pressed == combo:
                    self._start_recording()

        def on_release(key):
            if key in combo:
                pressed.discard(key)
                self._stop_recording()

        print(f"Hold '{config_mod.hotkey_display(self.cfg['hotkey'])}' to "
              "record, release to transcribe & type. Ctrl+C to quit.")
        print("Model loads lazily on first press; first transcription "
              "after load takes a few extra seconds.")
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()


def list_devices():
    import sounddevice as sd
    print(sd.query_devices())
    sys.exit(0)
