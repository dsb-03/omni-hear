"""`omnihear --doctor`: check the machine's setup and print exact fixes.

Stdlib only and import-light, so it runs even when the heavy deps are
broken — which is one of the things it checks. Exit status is 0 when
nothing blocks dictation, 1 otherwise.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys

OK, WARN, FAIL = "ok", "warn", "FAIL"


def _gnome_layouts() -> list[str]:
    """XKB layouts configured in GNOME, e.g. ['us', 'de']."""
    if not shutil.which("gsettings"):
        return []
    try:
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.input-sources", "sources"],
            capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    # "[('xkb', 'us'), ('ibus', 'mozc-jp')]"
    layouts = []
    for chunk in out.split("("):
        parts = [p.strip(" ')],\n") for p in chunk.split(",")]
        if len(parts) >= 2 and parts[0] == "xkb":
            layouts.append(parts[1])
    return layouts


def _clipboard_row() -> tuple[str, str, str]:
    """type_method = "paste": the clipboard tool it uses, or what to install."""
    from . import clipboard
    label, tool = "clipboard (paste)", clipboard.backend()
    if sys.platform in ("win32", "darwin"):
        return (OK, label, tool) if tool else (FAIL, label, "pbcopy not found")
    from . import linux_session
    wayland, gnome = linux_session.is_wayland(), linux_session.is_gnome()
    # GNOME: X11 tools through XWayland (Mutter has no data-control, so
    # wl-copy has to steal focus); KDE/wlroots: wl-clipboard.
    x11_tools = not wayland or (gnome and bool(os.environ.get("DISPLAY")))
    if tool is None:
        pkg = "xclip" if x11_tools else "wl-clipboard"
        return (FAIL, label, f"no clipboard tool — `sudo apt install {pkg}` "
                "(dictation is typed until then)")
    if wayland and gnome and x11_tools and tool == "wl-copy/wl-paste":
        return (WARN, label, f"{tool} briefly steals focus on GNOME — "
                "`sudo apt install xclip`")
    return (OK, label, tool)


def _llm_row(cfg: dict) -> tuple[str, str, str]:
    """Command Mode / smart cleanup: is a local Ollama reachable?"""
    from . import llm
    label, model = "local AI (Ollama)", cfg.get("ask_model") or "llama3.2"
    if llm.base_url() is None:
        return (FAIL, label, "OLLAMA_HOST is not on this machine; omnihear "
                "only uses a local Ollama")
    if llm.available():
        return (OK, label, f"running; model {model} "
                f"(`ollama pull {model}` if it is missing)")
    how = ("install from ollama.com, then `ollama pull " + model + "`"
           if not shutil.which("ollama") else "installed but not running — "
           "start it (`ollama serve`)")
    return (WARN, label, how)


def checks(cfg: dict) -> list[tuple[str, str, str]]:
    """(status, label, detail) rows."""
    rows: list[tuple[str, str, str]] = []
    add = lambda st, label, detail="": rows.append((st, label, detail))

    add(OK if sys.version_info >= (3, 11) else FAIL,
        "Python", sys.version.split()[0])

    for mod in ("faster_whisper", "sounddevice", "numpy"):
        found = importlib.util.find_spec(mod) is not None
        add(OK if found else FAIL, f"module {mod}",
            "" if found else "missing — reinstall omnihear "
            "(`sudo apt install --reinstall omnihear`) or pip install -r requirements.txt")

    try:
        import sounddevice as sd
        inputs = [d for d in sd.query_devices() if d.get("max_input_channels", 0) > 0]
        add(OK if inputs else FAIL, "microphone",
            f"{len(inputs)} input device(s)" if inputs
            else "no input devices — check Settings > Sound > Input")
    except Exception as e:  # PortAudio missing, no audio server, ...
        add(FAIL, "microphone", f"could not query audio devices: {e}")

    if (cfg.get("type_method") or "auto") == "paste":
        rows.append(_clipboard_row())
    if cfg.get("command_hotkey") or cfg.get("cleanup") == "smart":
        rows.append(_llm_row(cfg))
    if cfg.get("command_hotkey") and (cfg.get("type_method") or "auto") != "paste":
        from . import clipboard
        if clipboard.backend() is None:
            add(WARN, "Command Mode", "needs a clipboard tool to read the "
                "selection (xclip, or wl-clipboard on KDE/wlroots)")

    if sys.platform in ("win32", "darwin"):
        add(OK, "platform", sys.platform)
        return rows

    from . import evdev_hotkey, linux_session
    session = linux_session.session_type()
    add(OK if session != "unknown" else WARN, "session",
        f"{session} ({linux_session.desktop() or 'unknown desktop'})")

    configured = cfg.get("type_method") or "auto"
    resolved = linux_session.resolve_type_method(configured)
    add(OK, "type_method", f"{configured} -> {resolved}")

    if session == "wayland":
        kbds = evdev_hotkey.keyboard_devices()
        total = evdev_hotkey.keyboard_device_count()
        if kbds:
            add(OK, "hotkey input", f"{len(kbds)}/{total} keyboard(s) readable")
        elif linux_session.in_input_group_pending():
            add(FAIL, "hotkey input",
                "in `input` group but not in this login — log out and back in")
        else:
            add(FAIL, "hotkey input",
                "cannot read /dev/input — `sudo usermod -aG input $USER`, "
                "then log out and back in")
        try:
            evdev_hotkey.parse_hotkey_codes(cfg.get("hotkey", ""))
            add(OK, "hotkey", cfg.get("hotkey", ""))
        except ValueError as e:
            add(FAIL, "hotkey", str(e))

        if resolved == "uinput":
            add(OK if linux_session.uinput_available() else FAIL,
                "typing (uinput)",
                "/dev/uinput writable" if linux_session.uinput_available()
                else "/dev/uinput not writable — reinstall the .deb (ships a "
                     "udev rule) or see README > Wayland")
            if linux_session.has_ibus_unicode_entry():
                add(OK, "non-ASCII text", "via IBus Ctrl+Shift+U")
            else:
                add(WARN, "non-ASCII text",
                    "no IBus detected — accented/emoji characters are skipped")
        elif resolved in ("ydotool", "wtype"):
            add(OK if shutil.which(resolved) else FAIL, f"typing ({resolved})",
                "installed" if shutil.which(resolved)
                else f"`sudo apt install {resolved}`")
        if resolved in ("uinput", "ydotool"):
            non_us = [l for l in _gnome_layouts() if not l.startswith("us")]
            if non_us:
                add(WARN, "keyboard layout",
                    f"{', '.join(non_us)} configured — typing assumes US "
                    "QWERTY; some characters may come out wrong")
        for hint in linux_session.missing_wayland_deps(configured):
            if "ydotool needs its daemon" in hint or "wtype does not work" in hint:
                add(WARN, "hint", hint)
        if cfg.get("terminal_commands"):
            add(WARN, "terminal_commands", "X11-only, disabled on Wayland")
    elif session == "x11" and resolved == "xdotool":
        add(OK if shutil.which("xdotool") else FAIL, "typing (xdotool)",
            "installed" if shutil.which("xdotool") else "`sudo apt install xdotool`")

    has_display = bool(os.environ.get("DISPLAY"))
    tk = importlib.util.find_spec("tkinter") is not None
    add(OK if (tk and has_display) else WARN, "recording overlay",
        "tkinter on " + ("X11/XWayland" if has_display else "no X display")
        if tk else "python3-tk missing — `sudo apt install python3-tk`")
    add(OK if shutil.which("notify-send") else WARN, "notifications",
        "notify-send" if shutil.which("notify-send")
        else "`sudo apt install libnotify-bin` for desktop notifications")
    return rows


def main(cfg: dict) -> int:
    rows = checks(cfg)
    width = max(len(label) for _, label, _ in rows)
    for status, label, detail in rows:
        print(f"[{status:>4}] {label.ljust(width)}  {detail}")
    failed = [r for r in rows if r[0] == FAIL]
    print()
    print("omnihear doctor: " + ("all good." if not failed
                                  else f"{len(failed)} problem(s) to fix."))
    return 1 if failed else 0
