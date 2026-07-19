"""Supabase-backed account / beta status / feedback / opt-in analytics.

Stdlib only (urllib). Everything here is best-effort: network failures
never raise out of public functions and never block transcription.
Audio, transcripts, corrections, and learned data NEVER go through here —
only account auth, feedback the user typed, and consented metric pings.
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime

from . import config as config_mod

# ponytail: placeholders — set to the real project URL + anon (public) key.
# The anon key is safe to embed; RLS enforces access. Never the service_role key.
SUPABASE_URL = os.environ.get("OMNIHEAR_SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("OMNIHEAR_SUPABASE_ANON_KEY", "")

TIMEOUT = 5
_lock = threading.Lock()
_analytics = False  # set from config at startup


def account_path():
    return config_mod.config_path().parent / "account.json"


def _load() -> dict:
    try:
        return json.loads(account_path().read_text())
    except (OSError, ValueError):
        return {}


def _save(data: dict):
    p = account_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def _request(method: str, path: str, body=None, token=None):
    """Raw Supabase call. Raises urllib errors; callers decide tolerance."""
    if not SUPABASE_URL:
        raise RuntimeError("Supabase not configured")
    req = urllib.request.Request(
        SUPABASE_URL + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {token or SUPABASE_ANON_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def _authed(method, path, body=None):
    """Call with the user's token, refreshing once on 401."""
    acct = _load()
    try:
        return _request(method, path, body, token=acct.get("access_token"))
    except urllib.error.HTTPError as e:
        if e.code != 401 or not acct.get("refresh_token"):
            raise
        acct = _refresh(acct)
        return _request(method, path, body, token=acct["access_token"])


def _refresh(acct: dict) -> dict:
    data = _request("POST", "/auth/v1/token?grant_type=refresh_token",
                    {"refresh_token": acct["refresh_token"]})
    acct.update(access_token=data["access_token"],
                refresh_token=data["refresh_token"])
    with _lock:
        _save(acct)
    return acct


def _fetch_profile(acct: dict):
    rows = _authed("GET", "/rest/v1/profiles?select=beta_access,plan")
    if rows:
        acct["beta_access"] = bool(rows[0].get("beta_access"))
        acct["plan"] = rows[0].get("plan", "beta")
    acct["checked_at"] = datetime.now().isoformat(timespec="seconds")


# -- public API ------------------------------------------------------------

def sign_up(email: str, password: str) -> dict:
    data = _request("POST", "/auth/v1/signup",
                    {"email": email, "password": password})
    # If email confirmation is on, there's no session yet.
    if not data.get("access_token"):
        return {"ok": True, "confirm_email": True}
    return _store_session(data, email)


def sign_in(email: str, password: str) -> dict:
    data = _request("POST", "/auth/v1/token?grant_type=password",
                    {"email": email, "password": password})
    return _store_session(data, email)


def _store_session(data: dict, email: str) -> dict:
    acct = {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "user_id": (data.get("user") or {}).get("id"),
        "email": email,
    }
    with _lock:
        _save(acct)
    try:
        _fetch_profile(acct)
        with _lock:
            _save(acct)
    except Exception:
        acct.setdefault("beta_access", True)  # optimistic until first check
        with _lock:
            _save(acct)
    return {"ok": True, "status": status()}


def sign_out():
    try:
        account_path().unlink()
    except OSError:
        pass


def status(refresh: bool = False) -> dict:
    """Cached account status. Re-checks beta_access at most once/24h,
    best-effort — offline keeps the last cached status."""
    acct = _load()
    if not acct.get("access_token"):
        return {"signed_in": False, "beta_access": False}
    checked = acct.get("checked_at")
    stale = (not checked
             or (datetime.now() - datetime.fromisoformat(checked)).days >= 1)
    if refresh or stale:
        try:
            _fetch_profile(acct)
            with _lock:
                _save(acct)
        except Exception:
            pass  # offline: keep cache
    return {
        "signed_in": True,
        "email": acct.get("email"),
        "beta_access": bool(acct.get("beta_access")),
        "plan": acct.get("plan", "beta"),
    }


def beta_active() -> bool:
    acct = _load()
    return bool(acct.get("access_token")) and bool(acct.get("beta_access"))


def submit_feedback(kind: str, title: str, body: str,
                    diagnostics: str | None = None) -> dict:
    if kind not in ("bug", "feature"):
        return {"error": "kind must be 'bug' or 'feature'"}
    _authed("POST", "/rest/v1/feedback",
            {"kind": kind, "title": title, "body": body,
             "diagnostics": diagnostics})
    return {"ok": True}


def set_analytics(enabled: bool):
    global _analytics
    _analytics = bool(enabled)


def track(event: str, props: dict | None = None):
    """Fire-and-forget consented metric event. Never content data."""
    if not _analytics or not beta_active():
        return
    def _send():
        try:
            _authed("POST", "/rest/v1/events",
                    {"event": event, "props": props or {}})
        except Exception:
            pass
    threading.Thread(target=_send, daemon=True).start()


def daily_ping(cfg: dict):
    """Once-per-calendar-day usage ping (opt-in via cfg['analytics'])."""
    set_analytics(cfg.get("analytics", False))
    if not _analytics or not beta_active():
        return
    acct = _load()
    today = date.today().isoformat()
    if acct.get("last_ping") == today:
        return
    acct["last_ping"] = today
    with _lock:
        _save(acct)
    from . import __version__
    track("ping", {"version": __version__, "platform": sys.platform})


def track_activation():
    """One-time 'first successful transcription' event."""
    if not _analytics or not beta_active():
        return
    acct = _load()
    if acct.get("activated"):
        return
    acct["activated"] = True
    with _lock:
        _save(acct)
    track("activated", {})
