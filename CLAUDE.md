# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Push-to-talk local Whisper transcription for Linux (X11) and Windows. Hold a hotkey (or combo) → mic records → release → faster-whisper transcribes locally → text is typed into the focused field. Linux: distributed as a .deb through a self-hosted, GPG-signed APT repo served from GitHub Pages out of `docs/`. Windows: PyInstaller + Inno Setup installer attached to GitHub Releases.

## Commands

```bash
# Run from source (deps: python3 -m venv .venv && .venv/bin/pip install -r src/requirements.txt;
# system: portaudio19-dev xdotool libnotify-bin;
# Wayland also: membership in `input` group + ydotool or wtype)
cd src && ../.venv/bin/python3 -m omnihear            # dashboard on by default at http://127.0.0.1:4738
../.venv/bin/python3 -m omnihear --verbose             # re-enable per-transcription terminal logs
../.venv/bin/python3 -m omnihear --write-config        # dump effective settings to config.toml
../.venv/bin/python3 -m omnihear --doctor             # setup checks (Wayland perms, audio, deps)

# Landing page (site/ -> docs/, served by GitHub Pages)
./scripts/sync-site.sh

# Syntax check (there is no test suite or linter)
python3 -m py_compile src/omnihear/*.py

# Build the .deb
./build-deb.sh 1.2.0

# Publish a release (updates the live APT repo in docs/)
GPG_KEY_ID=divyanshu.s.butola@gmail.com ./scripts/update-apt-repo.sh omnihear_1.2.0_amd64.deb
git add docs/ && git commit -m "Publish omnihear 1.2.0" && git push
# or push a tag v1.2.0 to trigger .github/workflows/release.yml (requires GPG_* repo secrets)
# or Linux-only (APT repo, no tag/GitHub Release): Actions -> "Release (Linux only)" -> Run workflow on main with a version (.github/workflows/release-linux.yml)
```

Modules importable without the heavy deps (`config`, `db`, `dashboard`) can be exercised standalone; heavy imports (faster_whisper, sounddevice, pynput, numpy) are deliberately kept inside functions in `app.py` so `--help`, `--write-config`, and the dashboard work in environments without them. Preserve this property.

## Hard constraints

- **Stdlib only** for new Python code — the package's base pip deps are the four in `src/requirements.txt` (the Windows/macOS builds add `pystray`/`pillow` for the tray, see `requirements-win.txt`/`requirements-mac.txt`). The dashboard is plain `http.server` + one self-contained HTML string (no CDN, no external assets; must work fully offline).
- **Cross-platform, but branch explicitly.** Linux supports **X11 and Wayland**. Detect the session with `linux_session.session_type()` (`XDG_SESSION_TYPE` / `WAYLAND_DISPLAY`). X11 hotkeys + typing: pynput (default) or xdotool. Wayland hotkeys: stdlib evdev reader in `evdev_hotkey.py` (needs `input` group; rescans for hotplugged keyboards; ignores the virtual keyboards in `VIRTUAL_DEVICE_NAMES`). Wayland typing: stdlib `/dev/uinput` virtual keyboard in `uinput_keyboard.py` (`type_method=uinput`, the `auto` default; access via `udev/70-omnihear-uinput.rules` shipped in the .deb), else shell out to `ydotool` / `wtype` (wlroots only) via `linux_session`. `terminal_commands` stays X11-only (xdotool window probes). Windows/macOS stay on pynput. Platform-specific logic branches on `sys.platform` (`"win32"` / `"darwin"` / else = Linux) — keep all three paths working when editing shared code (`config.py`, `db.py`, `feedback.py`, `tray.py`, `app.py`, `dashboard.py`). macOS is Apple Silicon (arm64) only and needs Microphone + Accessibility + Input Monitoring permissions to function.
- Never modify `docs/` by hand — it is the live GitHub Pages site (APT repo + landing page), regenerated only by `scripts/update-apt-repo.sh` and `scripts/sync-site.sh` (copies the landing page from `site/`). Edit the landing page in `site/`.

## Architecture

Single process, `src/omnihear/`:

- `__main__.py` — argparse; defaults are seeded from the config file, so precedence is CLI flag > config file (`config.config_path()`, per-platform) > `config.DEFAULTS`. Wires App + db + dashboard together, and starts the tray on Windows/macOS.
- `app.py` — recording/transcription. Key behaviors that span the file: the Whisper model is **lazy-loaded** on first hotkey press and **unloaded after idle** (`idle_unload_minutes`, guarded by a model lock); all work is serialized through a single worker thread + queue of **tagged jobs** (`("transcribe", audio, duration, mode)`, `("paste_last", pressed_at)`) — ordering guarantee, don't spawn per-utterance threads; anything new on the queue must use a tagged tuple. Hotkeys support `+`-combos ("ctrl_l+space"): pynput key frozensets on X11/Windows/macOS, linux keycodes on Wayland; both backends feed `evdev_hotkey.ComboMatcher` bindings `(combo, on_press, on_release)` — exact-set match, release fires once per active combo. Presses/releases go through the hotkey state machine (`_on_hotkey_press`/`_on_hotkey_release`, under `_hk_lock`; states idle/held/armed/locked): hold-to-talk, plus `hands_free` (beta) double-tap lock (`TAP_SECONDS`/`DOUBLE_TAP_SECONDS`), and a `max_recording_seconds` watchdog per recording (generation counter makes stale timers no-ops). **All text insertion goes through `App._insert()`** (typing via `_type_text`, or clipboard paste via `_paste_text` when `type_method = "paste"`); it records an insertion window so hotkey presses our own injected keys could produce (Shift/single-char combos, Ctrl/Cmd+V in paste mode) are ignored — `_could_self_trigger`/`_guard_press` (pynput sees injected keys; evdev filters our virtual devices). An optional `ask_hotkey` (beta) triggers voice Q&A — see `qna.py`; `paste_last_hotkey` re-inserts `_last_inserted` via the worker (never written to history). `cleanup` (beta) runs `cleanup.clean()` on dictation prose. `rag_context` (beta) feeds relevant past transcriptions (`db.search_relevant`) into Whisper's `initial_prompt` alongside Common Brain's vocabulary hints.
- `clipboard.py` — stdlib clipboard get/set per platform for paste mode: xclip/xsel (X11, and GNOME Wayland via XWayland — Mutter has no data-control protocol, so `wl-copy` would steal focus), wl-copy/wl-paste (KDE/wlroots), pbcopy/pbpaste (macOS), ctypes Win32 (Windows; excluded from clipboard history/cloud). Linux sets PRIMARY too (VTE terminals paste PRIMARY on Shift+Insert). Selection-owner tools fork: run them with stdout/stderr DEVNULL or `subprocess.run` hangs. Never raises; callers fall back to typing.
- `cleanup.py` — rule-based dictation cleanup (fillers, function-word stutters, type-matched spoken self-corrections). Conservative by design and English-only; self-check: `python3 -m omnihear.cleanup`. Spoken-list → bullets is intentionally not done (newline = Enter sends chat messages).
- `linux_session.py` / `evdev_hotkey.py` / `uinput_keyboard.py` — Wayland session/desktop detection, typer selection and paste chords (`paste_chord`: Shift+Insert per backend), stdlib evdev hotkey monitor + `ComboMatcher` (owns the shared `US_KEYMAP`; per-device key tracking, hotplug, virtual-device filtering), and stdlib uinput virtual keyboard (US layout; non-ASCII via IBus Ctrl+Shift+U; KEY_INSERT for paste).
- `doctor.py` — `omnihear --doctor`: stdlib setup checks with exact fix commands; must stay runnable when heavy deps are missing.
- `config.py` — the **single source of truth** for constants shared with the frontend: `SPECIAL_KEY_NAMES`, `KEY_DISPLAY_NAMES`, `MODEL_NAMES` (official faster-whisper list), `LANGUAGE_NAMES` (all 100 codes), `DEFAULTS`, validation (`validate_updates`, `validate_hotkey`). TOML read via `tomllib`, written by a small hand-rolled flat serializer (stdlib has no writer). Model names stay free-form (custom HF repo ids allowed); languages are validated against the list plus `"auto"` (mapped to `None` for faster-whisper auto-detect in app.py).
- `dashboard.py` — localhost-only (`127.0.0.1:4738`) server. `PAGE` is one HTML string with placeholders (`__KEY_NAMES__`, `__MODELS__`, `__LANGS__`, `__TYPE_METHODS__`, `__CLEANUP_LEVELS__`, `__PLATFORM__`) substituted at serve time from config.py — add new shared constants that way, don't duplicate lists in the HTML. No external assets at all (no web fonts/CDNs). Screens via hash routing: `#/` dashboard, `#/history`, `#/log`, `#/settings` (config form → `POST /api/config` → validate → write config.toml; changes need restart; `POST /api/restart` uses `systemctl --user` only when under systemd), `#/beta`, and `#/welcome` (first-run setup wizard: `GET /api/doctor` checks, live hotkey/mic test polling `/api/status` `level`/`recording`/`locked`, practice box; auto-opens when history is empty and `localStorage['omnihear-onboarded']` is unset). Hotkey capture works on any `button[data-capture-key]`. `start_dashboard(..., cfg=)` gives handlers the live effective config (`server.cfg`). Don't add endpoints that inject keystrokes. Theming: light/dark via `prefers-color-scheme` plus a persisted manual toggle setting `data-theme`.
- `db.py` — SQLite `history.db` (Linux XDG `~/.local/share`, Windows `%LOCALAPPDATA%`, macOS `~/Library/Application Support`), WAL, one lock-guarded connection. Schema changes need a migration in `_migrate()` (PRAGMA table_info check + ALTER TABLE) — old DBs in the wild must keep working. (`config.py`'s `config_path()` follows the same per-platform convention for `config.toml`.) Also maintains an FTS5 index (`transcriptions_fts`, external-content table + triggers, applied best-effort so a build without FTS5 just disables retrieval) for `search_relevant()` — local keyword retrieval over past transcriptions, used for RAG context and voice Q&A. Never adds a network dependency: retrieval is pure SQLite.
- `qna.py` — local voice Q&A (beta): given a transcribed question and `db.search_relevant()` context, shells out to a locally-running `ollama` (stdlib `subprocess`, like `feedback.py`/`terminal_commands.py` shell out to other CLIs) to generate an answer; silent-on-missing, callers fall back to typing the raw question if Ollama isn't installed/running.
- `overlay_anim.py` — GUI-free animation model for the recording pill (live mic level → mirrored waveform; transcribing spinner + flowing wave; no-signal grey). `app.py`'s Tk `RecordingOverlay` (Linux/Windows) and `macos_overlay.py` (AppKit) only render its `Frame`s, and the landing page demo is a JS port of it — change the look there, keep the three in sync. User customisation (`overlay_*` config keys: scale, position + offset, container shape/colour/opacity, dot colour, bar count/width/gap/height/shape) goes through `overlay_anim.Style` (all geometry, pre-scaled) and `place()` (screen position); the option lists live there and `config.py` imports them. The dashboard's Settings → Recording Overlay live preview is another JS port of `Style`/`place()`, fed its constants via `__OVERLAY__` — keep it in sync too. On X11 the Tk window is clipped to the rounded shape with the X SHAPE extension (`_x11_shape_rounded`, ctypes, best-effort). `App._audio_callback` feeds block RMS via the overlay's `set_level()`.
- `feedback.py` — best-effort desktop notify + beep, per-platform (`notify-send`/`paplay` on Linux, `osascript`/`afplay` on macOS, `winsound` on Windows); must stay silent-on-missing.
- `tray.py` — shared menu-bar/system-tray icon (Open Dashboard / Quit) for **Windows and macOS**, imported behind a `sys.platform` check in `__main__.py` (Linux has no tray). `pystray`/`pillow` are lazy imports. macOS constraint: the tray must own the **main thread**, so on macOS `__main__.py` runs `app.run()` on a background thread and the tray blocks main.

Terminal output is quiet by default; per-transcription logs only under `--verbose` (`_log()` in app.py). The dashboard is the primary log.

## Packaging

### Linux (.deb)

**Linux (`.deb`):** `build-deb.sh <version>` assembles `omnihear_<v>_amd64/` from `DEBIAN-template/` (version substituted into control), `src/omnihear/` → `/opt/omnihear/`, wrapper → `/usr/bin/omnihear`, `systemd/omnihear.service` → `/usr/lib/systemd/user/`. The .deb does **not** vendor Python deps: `postinst` creates a venv in `/opt/omnihear` and pip-installs `requirements.txt` at install time (internet required). `Depends: python3 (>= 3.11)` because of `tomllib`. `postinst` installs `pynput` with `--no-deps` (its `evdev` dep has no wheels and won't build on a stock desktop; only the X11 backend is used). The .deb also ships `udev/` → `/usr/lib/udev/rules.d/` + `/usr/lib/modules-load.d/` for Wayland typing. Committed `omnihear_<v>_amd64/` trees are build artifacts of past releases.

**Windows (`.exe`)** and **macOS (`.dmg`):** both freeze deps in at build time via PyInstaller (opposite of the Linux runtime-pip model). Windows: `windows/` (`entry.py`, `omnihear.ico`, `omnihear.iss` Inno Setup) → onedir `.exe` + installer. macOS: `macos/` (`entry.py`, `omnihear.spec`, `omnihear.png` source icon → `make-icns.sh`, `build-dmg.sh`, and the no-op-without-secrets `sign.sh`/`entitlements.plist` for Developer-ID signing) → `Omnihear.app` (arm64, `LSUIElement` menu-bar agent) → drag-install DMG. All three build paths run from tag pushes in `.github/workflows/release.yml`; `macos/update-cask.sh` pushes the Homebrew Cask to a separate `homebrew-omnihear` tap. Version is always the git tag / build arg — `__init__.py`'s `__version__` is stale and unused, don't wire builds to it.
