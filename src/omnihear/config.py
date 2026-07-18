"""Config file handling for omnihear.

Reads ~/.config/omnihear/config.toml (respecting $XDG_CONFIG_HOME) via
stdlib tomllib, and writes it back with a tiny hand-rolled flat TOML
serializer (str/int/float/bool only).
"""

import os
import tomllib
from pathlib import Path

# Valid special hotkey names (single source of truth; app.py resolves
# these to pynput Key objects, the dashboard uses them for key capture).
SPECIAL_KEY_NAMES = [
    "ctrl_r", "ctrl_l", "alt_r", "alt_l", "shift_r", "shift_l",
    "caps_lock", "space", "pause", "scroll_lock",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
]

# Human-readable display names for the UI. The config file always stores
# the canonical (left column) name.
KEY_DISPLAY_NAMES = {
    "ctrl_r": "Ctrl Right", "ctrl_l": "Ctrl Left",
    "alt_r": "Alt Right", "alt_l": "Alt Left",
    "shift_r": "Shift Right", "shift_l": "Shift Left",
    "caps_lock": "Caps Lock", "space": "Space",
    "pause": "Pause", "scroll_lock": "Scroll Lock",
    **{f"f{i}": f"F{i}" for i in range(1, 13)},
}


def hotkey_display(name: str) -> str:
    """Human-readable form of a canonical hotkey string, e.g.
    'ctrl_l+space' -> 'Ctrl Left + Space'."""
    parts = [p for p in name.strip().lower().split("+") if p]
    return " + ".join(KEY_DISPLAY_NAMES.get(p, p.upper()) for p in parts)


def validate_hotkey(name: str) -> str | None:
    """Return the canonical combo string, or None if invalid.

    Accepts single keys ('f9', 'q') and '+'-joined combos ('ctrl_l+space').
    """
    parts = [p.strip() for p in str(name).strip().lower().split("+")]
    if not parts or any(not p for p in parts):
        return None
    for p in parts:
        if p not in SPECIAL_KEY_NAMES and len(p) != 1:
            return None
    return "+".join(parts)

# Official faster-whisper model names (_MODELS in faster_whisper/utils.py),
# grouped: English-only, multilingual, distilled/turbo. Custom HF repo ids
# are also accepted, so this list feeds the UI dropdown, not validation.
MODEL_NAMES = [
    "tiny.en", "base.en", "small.en", "medium.en",
    "tiny", "base", "small", "medium",
    "large-v1", "large-v2", "large-v3", "large",
    "distil-small.en", "distil-medium.en",
    "distil-large-v2", "distil-large-v3", "distil-large-v3.5",
    "large-v3-turbo", "turbo",
]

# Official faster-whisper language codes (_LANGUAGE_CODES in
# faster_whisper/tokenizer.py) with the standard Whisper English display
# names, in Whisper's rough by-usage order. "auto" (auto-detect) is
# handled separately.
LANGUAGE_NAMES = {
    "en": "English", "zh": "Chinese", "de": "German", "es": "Spanish",
    "ru": "Russian", "ko": "Korean", "fr": "French", "ja": "Japanese",
    "pt": "Portuguese", "tr": "Turkish", "pl": "Polish", "ca": "Catalan",
    "nl": "Dutch", "ar": "Arabic", "sv": "Swedish", "it": "Italian",
    "id": "Indonesian", "hi": "Hindi", "fi": "Finnish", "vi": "Vietnamese",
    "he": "Hebrew", "uk": "Ukrainian", "el": "Greek", "ms": "Malay",
    "cs": "Czech", "ro": "Romanian", "da": "Danish", "hu": "Hungarian",
    "ta": "Tamil", "no": "Norwegian", "th": "Thai", "ur": "Urdu",
    "hr": "Croatian", "bg": "Bulgarian", "lt": "Lithuanian", "la": "Latin",
    "mi": "Maori", "ml": "Malayalam", "cy": "Welsh", "sk": "Slovak",
    "te": "Telugu", "fa": "Persian", "lv": "Latvian", "bn": "Bengali",
    "sr": "Serbian", "az": "Azerbaijani", "sl": "Slovenian", "kn": "Kannada",
    "et": "Estonian", "mk": "Macedonian", "br": "Breton", "eu": "Basque",
    "is": "Icelandic", "hy": "Armenian", "ne": "Nepali", "mn": "Mongolian",
    "bs": "Bosnian", "kk": "Kazakh", "sq": "Albanian", "sw": "Swahili",
    "gl": "Galician", "mr": "Marathi", "pa": "Punjabi", "si": "Sinhala",
    "km": "Khmer", "sn": "Shona", "yo": "Yoruba", "so": "Somali",
    "af": "Afrikaans", "oc": "Occitan", "ka": "Georgian", "be": "Belarusian",
    "tg": "Tajik", "sd": "Sindhi", "gu": "Gujarati", "am": "Amharic",
    "yi": "Yiddish", "lo": "Lao", "uz": "Uzbek", "fo": "Faroese",
    "ht": "Haitian Creole", "ps": "Pashto", "tk": "Turkmen", "nn": "Nynorsk",
    "mt": "Maltese", "sa": "Sanskrit", "lb": "Luxembourgish", "my": "Myanmar",
    "bo": "Tibetan", "tl": "Tagalog", "mg": "Malagasy", "as": "Assamese",
    "tt": "Tatar", "haw": "Hawaiian", "ln": "Lingala", "ha": "Hausa",
    "ba": "Bashkir", "jw": "Javanese", "su": "Sundanese", "yue": "Cantonese",
}

DEFAULTS = {
    "model": "base.en",
    "device": "cpu",
    "compute_type": "int8",
    "hotkey": "ctrl_r",
    "sample_rate": 16000,
    "type_method": "pynput",
    "language": "en",
    "beam_size": 1,
    "min_duration": 0.3,
    "vad_filter": True,
    "no_speech_threshold": 0.6,
    "log_prob_threshold": -1.0,
    "compression_ratio_threshold": 2.4,
    "condition_on_previous_text": False,
    "input_device": "",
    "dashboard": True,
    "dashboard_port": 4738,
    "notify": True,
    "beep": False,
    "history": True,
    "idle_unload_minutes": 10,
    "verbose": False,
}

# Keys editable via the dashboard, with expected types.
KEY_TYPES = {k: type(v) for k, v in DEFAULTS.items()}


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "omnihear" / "config.toml"


def load_config(path: Path | None = None) -> dict:
    """Return DEFAULTS overlaid with values from the config file (if any)."""
    path = path or config_path()
    cfg = dict(DEFAULTS)
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return cfg
    except (tomllib.TOMLDecodeError, OSError) as e:
        print(f"omnihear: warning: could not read {path}: {e}")
        return cfg
    for k, v in data.items():
        if k not in DEFAULTS:
            continue
        want = KEY_TYPES[k]
        if want is float and isinstance(v, int) and not isinstance(v, bool):
            v = float(v)
        if want is not bool and isinstance(v, bool):
            continue
        if isinstance(v, want):
            cfg[k] = v
    return cfg


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    raise TypeError(f"unsupported TOML value type: {type(v)!r}")


def save_config(cfg: dict, path: Path | None = None) -> Path:
    """Write a flat TOML file with the known keys from cfg."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# omnihear configuration (restart omnihear after editing)"]
    for k in DEFAULTS:
        if k in cfg:
            lines.append(f"{k} = {_toml_value(cfg[k])}")
    path.write_text("\n".join(lines) + "\n")
    return path


def validate_updates(updates: dict) -> tuple[dict, list[str]]:
    """Validate a dict of proposed config changes (e.g. from the dashboard).

    Returns (clean, errors): coerced valid values and a list of error strings.
    """
    clean = {}
    errors = []
    for k, v in updates.items():
        if k not in DEFAULTS:
            errors.append(f"unknown key: {k}")
            continue
        want = KEY_TYPES[k]
        try:
            if want is bool:
                if isinstance(v, bool):
                    coerced = v
                elif isinstance(v, str):
                    coerced = v.strip().lower() in ("1", "true", "yes", "on")
                else:
                    coerced = bool(v)
            elif want is int:
                coerced = int(v)
            elif want is float:
                coerced = float(v)
            else:
                coerced = str(v)
        except (TypeError, ValueError):
            errors.append(f"invalid value for {k}: {v!r}")
            continue
        clean[k] = coerced
    if "device" in clean and clean["device"] not in ("cpu", "cuda"):
        errors.append("device must be cpu or cuda")
        del clean["device"]
    if "type_method" in clean and clean["type_method"] not in ("pynput", "xdotool"):
        errors.append("type_method must be pynput or xdotool")
        del clean["type_method"]
    if "language" in clean:
        lang = clean["language"].strip().lower()
        if lang in ("", "auto") or lang in LANGUAGE_NAMES:
            clean["language"] = lang or "auto"
        else:
            errors.append(f"unknown language code: {clean['language']!r}")
            del clean["language"]
    if "hotkey" in clean:
        hk = validate_hotkey(clean["hotkey"])
        if hk:
            clean["hotkey"] = hk
        else:
            errors.append("hotkey must be known key names or single characters, "
                          "joined with '+' for combos")
            del clean["hotkey"]
    for key in ("dashboard_port", "sample_rate", "beam_size"):
        if key in clean and clean[key] <= 0:
            errors.append(f"{key} must be positive")
            del clean[key]
    if "idle_unload_minutes" in clean and clean["idle_unload_minutes"] < 0:
        errors.append("idle_unload_minutes must be >= 0")
        del clean["idle_unload_minutes"]
    return clean, errors
