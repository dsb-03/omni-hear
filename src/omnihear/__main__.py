"""omnihear entry point: arg parsing, config merge, wiring."""

import argparse
import sys

from . import config as config_mod
from .app import SPECIAL_KEY_NAMES


def build_parser(cfg: dict) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="omnihear",
        description="Push-to-talk local Whisper transcription (Linux X11/Wayland, Windows, macOS).",
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
    p.add_argument("--hands-free", dest="hands_free", action="store_true",
                   default=cfg["hands_free"],
                   help="Hands-free mode (beta): double-tap the hotkey to keep "
                        "recording without holding it; tap again to stop.")
    p.add_argument("--no-hands-free", dest="hands_free", action="store_false",
                   help="Disable hands-free mode.")
    p.add_argument("--max-recording-seconds", type=int,
                   default=cfg["max_recording_seconds"],
                   help="Safety cap: stop and transcribe after this many "
                        "seconds of recording (10-3600).")
    p.add_argument("--paste-last-hotkey", default=cfg["paste_last_hotkey"],
                   help="Optional key/combo that re-inserts the last "
                        "transcript at the cursor (e.g. 'ctrl_l+shift_l+v'). "
                        "Empty disables it.")
    p.add_argument("--cleanup", default=cfg["cleanup"],
                   choices=list(config_mod.CLEANUP_LEVELS),
                   help="Clean up dictation before typing (beta): 'light' "
                        "removes filler words (um, uh), stutters and "
                        "spoken self-corrections; 'smart' adds a local "
                        "Ollama grammar pass within smart_cleanup_ms.")
    p.add_argument("--sample-rate", type=int, default=cfg["sample_rate"],
                   help="Audio sample rate in Hz.")
    p.add_argument("--type-method", default=cfg["type_method"],
                   choices=list(config_mod.TYPE_METHODS),
                   help="How to inject transcribed text into the focused field. "
                        "'auto' picks pynput on X11/Windows/macOS; on Wayland "
                        "the built-in uinput typer, else ydotool/wtype. "
                        "'paste' (beta) pastes via the clipboard and restores it.")
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
    p.add_argument("--no-brain", dest="brain", action="store_false",
                   default=cfg["brain"],
                   help="Disable the Common Brain learning engine (beta).")
    p.add_argument("--rag-context", dest="rag_context", action="store_true",
                   default=cfg["rag_context"],
                   help="Feed relevant past transcriptions (retrieved from "
                        "history.db) to Whisper as extra initial_prompt "
                        "context (beta).")
    p.add_argument("--no-rag-context", dest="rag_context", action="store_false",
                   help="Disable RAG context (default).")
    p.add_argument("--rag-context-limit", type=int,
                   default=cfg["rag_context_limit"],
                   help="Max past transcriptions to feed as RAG context.")
    p.add_argument("--ask-hotkey", default=cfg["ask_hotkey"],
                   help="Optional second push-to-talk key/combo for voice "
                        "Q&A (beta): hold, ask a question, release to get a "
                        "locally-generated answer typed instead of the raw "
                        "transcript. Empty disables it.")
    p.add_argument("--ask-model", default=cfg["ask_model"],
                   help="Ollama model name used to generate voice Q&A answers.")
    p.add_argument("--ask-context-limit", type=int,
                   default=cfg["ask_context_limit"],
                   help="Max past transcriptions retrieved as context for "
                        "voice Q&A.")
    p.add_argument("--command-hotkey", default=cfg["command_hotkey"],
                   help="Optional push-to-talk key/combo for Command Mode "
                        "(beta): select text, hold, say an edit (\"make this "
                        "shorter\"), release; a local Ollama model rewrites "
                        "the selection. Empty disables it.")
    p.add_argument("--chunked-transcription", dest="chunked_transcription",
                   action="store_true", default=cfg["chunked_transcription"],
                   help="Transcribe long dictations in chunks at pauses while "
                        "still recording (beta).")
    p.add_argument("--no-chunked-transcription", dest="chunked_transcription",
                   action="store_false", help="Disable chunked transcription.")
    p.add_argument("--whisper-mode", dest="whisper_mode", action="store_true",
                   default=cfg["whisper_mode"],
                   help="Quiet-speech profile (beta): more gain, lower "
                        "voice-detection thresholds.")
    p.add_argument("--no-whisper-mode", dest="whisper_mode",
                   action="store_false", help="Disable whisper mode.")
    p.add_argument("--code-switching", dest="code_switching",
                   action="store_true", default=cfg["code_switching"],
                   help="With --language auto, allow switching language "
                        "within one dictation (beta).")
    p.add_argument("--no-code-switching", dest="code_switching",
                   action="store_false", help="Disable code-switching.")
    p.add_argument("--analytics", dest="analytics", action="store_true",
                   default=cfg["analytics"],
                   help="Opt in to anonymous usage pings (version/platform "
                        "only, never transcript or audio content).")
    p.add_argument("--verbose", dest="verbose", action="store_true",
                   default=cfg["verbose"],
                   help="Print per-transcription output to the terminal "
                        "(recording, queued audio, transcribed text).")
    p.add_argument("--cleanup-model", default=cfg["cleanup_model"],
                   help="Ollama model for --cleanup smart (default: a "
                        "dictation-cleanup fine-tune of Qwen3.5-2B).")
    p.add_argument("--bench-llm", nargs="*", metavar="MODEL",
                   help="Time local Ollama models on sample dictations and "
                        "exit (default: the configured cleanup and "
                        "Command Mode models).")
    p.add_argument("--doctor", action="store_true",
                   help="Check this machine's setup (session, hotkey and "
                        "typing permissions, audio, model deps), print fixes, "
                        "and exit.")
    p.add_argument("--write-config", action="store_true",
                   help="Write the current effective settings to "
                        f"{config_mod.config_path()} and exit.")
    return p


def effective_config(args, file_cfg: dict | None = None) -> dict:
    # Seed from the config file so keys without CLI flags keep their
    # file-configured values instead of resetting to DEFAULTS.
    cfg = dict(file_cfg or config_mod.DEFAULTS)
    for key in cfg:
        if not hasattr(args, key):
            continue   # no CLI flag: keep the config file's value
        val = getattr(args, key)
        if val is None:  # e.g. --input-device defaults to None for ""
            val = "" if isinstance(cfg[key], str) else cfg[key]
        cfg[key] = val
    return cfg


def main():
    file_cfg = config_mod.load_config()
    args = build_parser(file_cfg).parse_args()
    cfg = effective_config(args, file_cfg)

    if args.write_config:
        path = config_mod.save_config(cfg)
        print(f"Wrote {path}")
        sys.exit(0)

    if args.doctor:
        from . import doctor
        sys.exit(doctor.main(cfg))

    if args.bench_llm is not None:
        from . import llm
        models = args.bench_llm or list(dict.fromkeys(
            [cfg["cleanup_model"], cfg["ask_model"]]))
        sys.exit(llm.bench(models))

    if args.list_devices:
        from .app import list_devices
        list_devices()

    from .app import App
    from .feedback import Feedback

    db = None
    if cfg["history"]:
        from .db import HistoryDB
        db = HistoryDB()

    brain = None
    if db is not None and cfg["brain"]:
        from .brain import Brain
        brain = Brain(db, min_count=cfg["brain_min_count"])

    personal = None
    if db is not None:
        from .personal import Personal
        personal = Personal(db)

    feedback = Feedback(notify_enabled=cfg["notify"], beep_enabled=cfg["beep"])
    app = App(cfg, db=db, feedback=feedback, brain=brain, personal=personal)

    # Opt-in daily usage ping (no-op unless analytics on + signed in).
    import threading as _threading
    from . import cloud
    _threading.Thread(target=cloud.daily_ping, args=(cfg,), daemon=True).start()

    if cfg["dashboard"]:
        from .dashboard import start_dashboard
        if start_dashboard(db, app.status, port=cfg["dashboard_port"],
                           brain=brain, cfg=cfg, personal=personal) is None:
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

        # First-run permission onboarding: prompt for anything not yet decided
        # and tell the user exactly what to grant (the dashboard has one-click
        # links). Best-effort — never let this block startup.
        try:
            from . import macos_permissions as macperm
            st = macperm.check()
            macperm.request_prompts(st)
            miss = macperm.missing(st)
            if miss:
                labels = ", ".join(macperm.PERMISSIONS[k]["label"] for k in miss)
                print(f"omnihear: needs these permissions — enable in System "
                      f"Settings > Privacy & Security: {labels}")
                print(f"          one-click links in the dashboard: "
                      f"http://127.0.0.1:{cfg['dashboard_port']}")
                if feedback:
                    feedback.notify("omnihear needs permissions",
                                    f"Enable {labels} in System Settings.")
        except Exception as e:
            print(f"omnihear: permission check skipped: {e}")

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
