#!/usr/bin/env python3
"""
omnihear: Push-to-talk local Whisper transcription for X11.

Hold HOTKEY -> records mic audio.
Release HOTKEY -> transcribes with faster-whisper and types the
result into whichever field currently has keyboard focus.

Requires (system):
    sudo apt install portaudio19-dev xdotool   # xdotool is optional fallback

Requires (python):
    pip install faster-whisper sounddevice numpy pynput

Usage:
    python3 omnihear.py --model small.en --device cuda --compute-type float16
    python3 omnihear.py --hotkey f9 --type-method xdotool
    python3 omnihear.py --list-devices
"""

import argparse
import queue
import threading
import sys

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from pynput import keyboard


# Map of accepted --hotkey string values to pynput Key objects.
SPECIAL_KEYS = {
    "ctrl_r": keyboard.Key.ctrl_r,
    "ctrl_l": keyboard.Key.ctrl_l,
    "alt_r": keyboard.Key.alt_r,
    "alt_l": keyboard.Key.alt_l,
    "shift_r": keyboard.Key.shift_r,
    "shift_l": keyboard.Key.shift_l,
    "caps_lock": keyboard.Key.caps_lock,
    "f9": keyboard.Key.f9,
    "f10": keyboard.Key.f10,
    "f11": keyboard.Key.f11,
    "f12": keyboard.Key.f12,
    "pause": keyboard.Key.pause,
    "scroll_lock": keyboard.Key.scroll_lock,
}


def parse_args():
    p = argparse.ArgumentParser(
        description="Push-to-talk local Whisper transcription (X11).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--model", default="base.en",
        help="Whisper model size: tiny.en, base.en, small.en, medium.en, large-v3, etc.",
    )
    p.add_argument(
        "--device", default="cpu", choices=["cpu", "cuda"],
        help="Inference device.",
    )
    p.add_argument(
        "--compute-type", default="int8",
        help="Compute precision, e.g. int8 (cpu), float16 (cuda), int8_float16, float32.",
    )
    p.add_argument(
        "--hotkey", default="ctrl_r",
        help=f"Push-to-talk key. One of: {', '.join(SPECIAL_KEYS)} "
             "or a single character (e.g. 'q').",
    )
    p.add_argument(
        "--sample-rate", type=int, default=16000,
        help="Audio sample rate in Hz (16000 is what Whisper expects).",
    )
    p.add_argument(
        "--type-method", default="pynput", choices=["pynput", "xdotool"],
        help="How to inject transcribed text into the focused field.",
    )
    p.add_argument(
        "--language", default="en",
        help="Language code for transcription (use with multilingual models).",
    )
    p.add_argument(
        "--beam-size", type=int, default=1,
        help="Beam size for decoding. 1 = fastest (greedy), higher = more accurate/slower.",
    )
    p.add_argument(
        "--min-duration", type=float, default=0.3,
        help="Minimum recording length (seconds) to bother transcribing.",
    )
    p.add_argument(
        "--input-device", default=None,
        help="Input audio device name or index (see --list-devices). Default: system default mic.",
    )
    p.add_argument(
        "--list-devices", action="store_true",
        help="List available audio input devices and exit.",
    )
    return p.parse_args()


def resolve_hotkey(name):
    name = name.strip().lower()
    if name in SPECIAL_KEYS:
        return SPECIAL_KEYS[name]
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    raise ValueError(
        f"Unrecognized --hotkey '{name}'. Use one of {list(SPECIAL_KEYS)} or a single character."
    )


def main():
    args = parse_args()

    if args.list_devices:
        print(sd.query_devices())
        sys.exit(0)

    hotkey = resolve_hotkey(args.hotkey)

    print(f"Loading Whisper model '{args.model}' on {args.device} ({args.compute_type})...")
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    print("Model loaded. Ready.")

    kb_controller = keyboard.Controller()
    audio_q = queue.Queue()
    state = {"recording": False, "stream": None}

    def audio_callback(indata, frames_count, time_info, status):
        if status:
            print(status)
        audio_q.put(indata.copy())

    def start_recording():
        if state["recording"]:
            return
        state["recording"] = True
        stream = sd.InputStream(
            samplerate=args.sample_rate,
            channels=1,
            dtype="float32",
            device=args.input_device,
            callback=audio_callback,
        )
        stream.start()
        state["stream"] = stream
        print("Recording...")

    def type_text(text):
        if args.type_method == "xdotool":
            import subprocess
            subprocess.run(["xdotool", "type", "--clearmodifiers", "--", text])
        else:
            kb_controller.type(text)

    def stop_recording_and_transcribe():
        if not state["recording"]:
            return
        state["recording"] = False
        stream = state["stream"]
        stream.stop()
        stream.close()

        chunks = []
        while not audio_q.empty():
            chunks.append(audio_q.get())
        if not chunks:
            print("No audio captured.")
            return
        audio = np.concatenate(chunks, axis=0).flatten()

        duration = len(audio) / args.sample_rate
        if duration < args.min_duration:
            print("Too short, ignoring.")
            return

        print(f"Transcribing {duration:.2f}s of audio...")

        def run_transcription():
            segments, _ = model.transcribe(
                audio, language=args.language, beam_size=args.beam_size
            )
            text = "".join(seg.text for seg in segments).strip()
            if text:
                print(f"-> {text}")
                type_text(text + " ")
            else:
                print("(empty transcription)")

        threading.Thread(target=run_transcription, daemon=True).start()

    def on_press(key):
        if key == hotkey:
            start_recording()

    def on_release(key):
        if key == hotkey:
            stop_recording_and_transcribe()

    print(f"Hold '{args.hotkey}' to record, release to transcribe & type. Ctrl+C to quit.")
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


if __name__ == "__main__":
    main()
