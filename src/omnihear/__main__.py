"""omnihear entry point: arg parsing, config merge, wiring."""

import argparse
import sys

from . import config as config_mod
from .app import SPECIAL_KEY_NAMES


def build_parser(cfg: dict) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="omnihear",
        description="Push-to-talk local Whisper transcription (Linux/X11, Windows, macOS).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--model", default=cfg["model"],
                   help="Whisper model size: tiny.en, base.en, small.en, "
                        "medium.en, large-v3, etc.")
    p.add_argument("--device", default=cfg["device"], choices=["cpu", "cuda"],
                   help="Inference device.")
    p.add_argument("--compute-type", default=cfg["compute_type"],
                   help="Compute precision, e.g. int8 (cpu), float16 (cuda).")
    p.add_argument("--hotkey", default=cfg["hotkey"],
                   help=f"Push-to-talk key. One of: {', '.join(SPECIAL_KEY_NAMES)} "
                        "or a single character (e.g. 'q'). Combos join parts "
                        "with '+', e.g. 'ctrl_l+space'.")
    p.add_argument("--sample-rate", type=int, default=cfg["sample_rate"],
                   help="Audio sample rate in Hz.")
    p.add_argument("--type-method", default=cfg["type_method"],
                   choices=["pynput", "xdotool"],
                   help="How to inject transcribed text into the focused field.")
    p.add_argument("--language", default=cfg["language"],
                   help="Language code for transcription.")
    p.add_argument("--beam-size", type=int, default=cfg["beam_size"],
                   help="Beam size for decoding. 1 = fastest (greedy).")
    p.add_argument("--min-duration", type=float, default=cfg["min_duration"],
                   help="Minimum recording length (seconds) to transcribe.")
    p.add_argument("--input-device", default=cfg["input_device"] or None,
                   help="Input audio device name or index (see --list-devices).")
    p.add_argument("--list-devices", action="store_true",
                   help="List available audio input devices and exit.")
    p.add_argument("--dashboard", dest="dashboard", action="store_true",
                   default=cfg["dashboard"],
                   help="Serve the localhost web dashboard.")
    p.add_argument("--no-dashboard", dest="dashboard", action="store_false",
                   help="Disable the web dashboard.")
    p.add_argument("--dashboard-port", type=int, default=cfg["dashboard_port"],
                   help="Dashboard port (bound to 127.0.0.1 only).")
    p.add_argument("--no-history", dest="history", action="store_false",
                   default=cfg["history"],
                   help="Do not record transcription history in SQLite.")
    p.add_argument("--no-notify", dest="notify", action="store_false",
                   default=cfg["notify"],
                   help="Disable desktop notifications.")
    p.add_argument("--beep", dest="beep", action="store_true",
                   default=cfg["beep"],
                   help="Play a short sound when recording starts.")
    p.add_argument("--idle-unload-minutes", type=int,
                   default=cfg["idle_unload_minutes"],
                   help="Unload the model after this many idle minutes "
                        "(0 = never unload).")
    p.add_argument("--verbose", dest="verbose", action="store_true",
                   default=cfg["verbose"],
                   help="Print per-transcription output to the terminal "
                        "(recording, queued audio, transcribed text).")
    p.add_argument("--write-config", action="store_true",
                   help="Write the current effective settings to "
                        f"{config_mod.config_path()} and exit.")
    return p


def effective_config(args) -> dict:
    cfg = dict(config_mod.DEFAULTS)
    for key in cfg:
        val = getattr(args, key, None)
        if val is None:
            val = "" if isinstance(cfg[key], str) else cfg[key]
        cfg[key] = val
    return cfg


def main():
    file_cfg = config_mod.load_config()
    args = build_parser(file_cfg).parse_args()
    cfg = effective_config(args)

    if args.write_config:
        path = config_mod.save_config(cfg)
        print(f"Wrote {path}")
        sys.exit(0)

    if args.list_devices:
        from .app import list_devices
        list_devices()

    from .app import App
    from .feedback import Feedback

    db = None
    if cfg["history"]:
        from .db import HistoryDB
        db = HistoryDB()

    feedback = Feedback(notify_enabled=cfg["notify"], beep_enabled=cfg["beep"])
    app = App(cfg, db=db, feedback=feedback)

    if cfg["dashboard"]:
        from .dashboard import start_dashboard
        if start_dashboard(db, app.status, port=cfg["dashboard_port"]) is None:
            # Port already bound: almost certainly another omnihear instance.
            # Two instances both hear the hotkey and both type, interleaving
            # their output — exit instead.
            sys.exit(f"Port {cfg['dashboard_port']} is already in use — "
                     "is omnihear already running?")

    if sys.platform == "darwin":
        # On macOS the menu-bar icon must own the main thread (AppKit), so
        # run the recorder/listener on a background thread and let the tray
        # block the main thread.
        import threading
        from .tray import start_tray
        threading.Thread(target=app.run, daemon=True).start()
        try:
            start_tray(cfg["dashboard_port"], app.stop)
        except KeyboardInterrupt:
            pass
        return

    if sys.platform == "win32":
        from .tray import start_tray
        start_tray(cfg["dashboard_port"], app.stop)

    try:
        app.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
