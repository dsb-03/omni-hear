"""Checks GitHub Releases for a newer omnihear build than the one running.

Windows only for now (see tray.py) -- there's no signed/notarized macOS
build or APT-managed Linux install to point this at yet. Stdlib only
(urllib), silent on any failure: offline, rate-limited, or running from
source (`python -m omnihear`) with no bundled VERSION file to compare.
"""

import json
import os
import sys
import urllib.error
import urllib.request

_REPO = "dsb-03/omni-hear"
_TIMEOUT = 4


def bundled_version() -> str | None:
    """The version written into windows/VERSION at build time (see
    .github/workflows/release.yml), read next to the frozen executable.
    None outside a PyInstaller build, where there's nothing to compare."""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return None
    try:
        with open(os.path.join(base, "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _parse(v: str) -> tuple[int, ...]:
    parts = []
    for p in v.lstrip("vV").split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def latest_release() -> tuple[str, str] | None:
    """(tag, html_url) of the latest GitHub release, or None on any
    network/parse failure."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{_REPO}/releases/latest",
        headers={"User-Agent": "omnihear", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    tag, html_url = data.get("tag_name"), data.get("html_url")
    return (tag, html_url) if tag and html_url else None


def check() -> tuple[str, str] | None:
    """(latest_tag, url) if a newer release exists than the running build,
    else None. Never raises."""
    current = bundled_version()
    if not current:
        return None
    latest = latest_release()
    if not latest:
        return None
    tag, url = latest
    return (tag, url) if _parse(tag) > _parse(current) else None
