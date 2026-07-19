"""macOS permission onboarding for the three grants omnihear needs.

Recording, typing, and the global hotkey each need a Privacy grant that the
user must give once — and finding the right pane in System Settings is the
part people get stuck on. This module detects what's missing, fires the
native prompts for anything not-yet-decided, and can open the exact Settings
pane on request (used by the dashboard banner).

Uses only pyobjc frameworks already pulled in on macOS (Quartz /
ApplicationServices). Everything degrades to "unknown" if an API is absent,
and callers must stay best-effort — never block startup on this.
"""

import subprocess
import sys

# Human labels + the deep-link that opens each Privacy pane directly.
PERMISSIONS = {
    "accessibility": {
        "label": "Accessibility",
        "why": "type transcribed text into the focused field",
        "pane": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    },
    "input_monitoring": {
        "label": "Input Monitoring",
        "why": "detect the global push-to-talk hotkey",
        "pane": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    },
    "microphone": {
        "label": "Microphone",
        "why": "record audio to transcribe",
        "pane": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
    },
}


def _accessibility_status():
    try:
        from ApplicationServices import AXIsProcessTrusted
        return "authorized" if AXIsProcessTrusted() else "denied"
    except Exception:
        return "unknown"


def _input_monitoring_status():
    try:
        from Quartz import CGPreflightListenEventAccess
        return "authorized" if CGPreflightListenEventAccess() else "denied"
    except Exception:
        return "unknown"


def _microphone_status():
    # AVFoundation isn't a hard dependency; if it's absent we simply don't
    # report mic status (it prompts naturally on the first recording anyway).
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
        status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
        return {0: "not_determined", 1: "denied", 2: "denied", 3: "authorized"}.get(
            status, "unknown")
    except Exception:
        return "unknown"


def check() -> dict:
    """Return {permission: 'authorized'|'denied'|'not_determined'|'unknown'}."""
    if sys.platform != "darwin":
        return {}
    return {
        "accessibility": _accessibility_status(),
        "input_monitoring": _input_monitoring_status(),
        "microphone": _microphone_status(),
    }


def missing(status: dict | None = None) -> list:
    """Permission keys that are not authorized (unknown is treated as ok so we
    never nag when we can't actually tell)."""
    status = status or check()
    return [k for k, v in status.items() if v not in ("authorized", "unknown")]


def request_prompts(status: dict | None = None):
    """Fire the native permission prompts for anything not yet decided. These
    calls only pop a dialog when the state is 'not determined'; for an already
    'denied' grant they're no-ops, so this is safe to call on every launch."""
    if sys.platform != "darwin":
        return
    status = status or check()
    if status.get("input_monitoring") != "authorized":
        try:
            from Quartz import CGRequestListenEventAccess
            CGRequestListenEventAccess()
        except Exception:
            pass
    if status.get("microphone") == "not_determined":
        try:
            from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
            AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                AVMediaTypeAudio, lambda granted: None)
        except Exception:
            pass


def open_settings_pane(name: str) -> bool:
    """Open the System Settings Privacy pane for one permission."""
    info = PERMISSIONS.get(name)
    if not info:
        return False
    try:
        subprocess.Popen(["open", info["pane"]])
        return True
    except (OSError, ValueError):
        return False
