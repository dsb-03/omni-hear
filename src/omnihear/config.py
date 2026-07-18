"""Config file handling for omnihear.

Reads ~/.config/omnihear/config.toml (respecting $XDG_CONFIG_HOME) via
stdlib tomllib, and writes it back with a tiny hand-rolled flat TOML
serializer (str/int/float/bool only).
"""

import os
import tomllib
from pathlib import Path

# Valid special hotkey names (single source of truth; app.py resolves
# these to pynput Key objects, the dashboard offers them in a dropdown).
SPECIAL_KEY_NAMES = [
    "ctrl_r", "ctrl_l", "alt_r", "alt_l", "shift_r", "shift_l",
    "caps_lock", "f9", "f10", "f11", "f12", "pause", "scroll_lock",
]

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
    if "hotkey" in clean:
        hk = clean["hotkey"].strip().lower()
        if hk in SPECIAL_KEY_NAMES or len(hk) == 1:
            clean["hotkey"] = hk
        else:
            errors.append("hotkey must be a known key name or a single character")
            del clean["hotkey"]
    for key in ("dashboard_port", "sample_rate", "beam_size"):
        if key in clean and clean[key] <= 0:
            errors.append(f"{key} must be positive")
            del clean[key]
    if "idle_unload_minutes" in clean and clean["idle_unload_minutes"] < 0:
        errors.append("idle_unload_minutes must be >= 0")
        del clean["idle_unload_minutes"]
    return clean, errors
