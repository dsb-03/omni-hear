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
from .config import SPECIAL_KEY_NAMES


def resolve_hotkey(name):
    from pynput import keyboard
    name = name.strip().lower()
    if name in SPECIAL_KEY_NAMES:
        return getattr(keyboard.Key, name)
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    raise ValueError(
        f"Unrecognized hotkey '{name}'. Use one of {SPECIAL_KEY_NAMES} "
        "or a single character."
    )


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

    def _log(self, msg):
        """Per-transcription chatter; printed only with --verbose."""
        if self._verbose:
            print(msg)

    # -- status for the dashboard ------------------------------------
    def status(self) -> dict:
        return {
            "model": self.cfg["model"],
            "hotkey": self.cfg["hotkey"],
            "model_loaded": self._model is not None,
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
        segments, _ = model.transcribe(
            audio,
            language=self.cfg["language"],
            beam_size=self.cfg["beam_size"],
        )
        text = "".join(seg.text for seg in segments).strip()
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
                               cpu_percent=cpu_percent, memory_mb=memory_mb)
            except Exception as e:
                print(f"History write failed: {e}")

    # -- main loop -----------------------------------------------------
    def run(self):
        from pynput import keyboard

        hotkey = resolve_hotkey(self.cfg["hotkey"])
        self._kb_controller = keyboard.Controller()

        threading.Thread(target=self._worker_loop, daemon=True).start()
        threading.Thread(target=self._idle_unload_loop, daemon=True).start()

        def on_press(key):
            if key == hotkey:
                self._start_recording()

        def on_release(key):
            if key == hotkey:
                self._stop_recording()

        print(f"Hold '{self.cfg['hotkey']}' to record, release to "
              "transcribe & type. Ctrl+C to quit.")
        print("Model loads lazily on first press; first transcription "
              "after load takes a few extra seconds.")
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()


def list_devices():
    import sounddevice as sd
    print(sd.query_devices())
    sys.exit(0)
