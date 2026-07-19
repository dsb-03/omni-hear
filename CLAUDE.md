# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Push-to-talk local Whisper transcription for Linux (X11) and Windows. Hold a hotkey (or combo) → mic records → release → faster-whisper transcribes locally → text is typed into the focused field. Linux: distributed as a .deb through a self-hosted, GPG-signed APT repo served from GitHub Pages out of `docs/`. Windows: PyInstaller + Inno Setup installer attached to GitHub Releases.

## Commands

```bash
# Run from source (deps: python3 -m venv .venv && .venv/bin/pip install -r src/requirements.txt;
# system: portaudio19-dev xdotool libnotify-bin)
cd src && ../.venv/bin/python3 -m omnihear            # dashboard on by default at http://127.0.0.1:4738
../.venv/bin/python3 -m omnihear --verbose             # re-enable per-transcription terminal logs
../.venv/bin/python3 -m omnihear --write-config        # dump effective settings to config.toml

# Syntax check (there is no test suite or linter)
python3 -m py_compile src/omnihear/*.py

# Build the .deb
./build-deb.sh 1.2.0

# Publish a release (updates the live APT repo in docs/)
GPG_KEY_ID=divyanshu.s.butola@gmail.com ./scripts/update-apt-repo.sh omnihear_1.2.0_amd64.deb
git add docs/ && git commit -m "Publish omnihear 1.2.0" && git push
# or push a tag v1.2.0 to trigger .github/workflows/release.yml (requires GPG_* repo secrets)
```

Modules importable without the heavy deps (`config`, `db`, `dashboard`) can be exercised standalone; heavy imports (faster_whisper, sounddevice, pynput, numpy) are deliberately kept inside functions in `app.py` so `--help`, `--write-config`, and the dashboard work in environments without them. Preserve this property.

## Hard constraints

- **Stdlib only** for new Python code — the package's base pip deps are the four in `src/requirements.txt` (the Windows/macOS builds add `pystray`/`pillow` for the tray, see `requirements-win.txt`/`requirements-mac.txt`). The dashboard is plain `http.server` + one self-contained HTML string (no CDN, no external assets; must work fully offline).
- **Cross-platform, but branch explicitly.** Linux is **X11 only** (no Wayland); text injection is pynput or xdotool there, pynput on Windows/macOS. Platform-specific logic branches on `sys.platform` (`"win32"` / `"darwin"` / else = Linux) — keep all three paths working when editing shared code (`config.py`, `db.py`, `feedback.py`, `tray.py`, `app.py`, `dashboard.py`). macOS is Apple Silicon (arm64) only and needs Microphone + Accessibility + Input Monitoring permissions to function.
- Never modify `docs/` by hand — it is the live APT repo, regenerated only by `scripts/update-apt-repo.sh`.

## Architecture

Single process, `src/omnihear/`:

- `__main__.py` — argparse; defaults are seeded from the config file, so precedence is CLI flag > config file (`config.config_path()`, per-platform) > `config.DEFAULTS`. Wires App + db + dashboard together, and starts the tray on Windows/macOS.
- `app.py` — recording/transcription. Key behaviors that span the file: the Whisper model is **lazy-loaded** on first hotkey press and **unloaded after idle** (`idle_unload_minutes`, guarded by a model lock); transcriptions are serialized through a single worker thread + queue (ordering guarantee — don't spawn per-utterance threads); hotkeys support `+`-combos ("ctrl_l+space") parsed into a frozenset of pynput keys, recording starts when the full set is held, stops when any member releases.
- `config.py` — the **single source of truth** for constants shared with the frontend: `SPECIAL_KEY_NAMES`, `KEY_DISPLAY_NAMES`, `MODEL_NAMES` (official faster-whisper list), `LANGUAGE_NAMES` (all 100 codes), `DEFAULTS`, validation (`validate_updates`, `validate_hotkey`). TOML read via `tomllib`, written by a small hand-rolled flat serializer (stdlib has no writer). Model names stay free-form (custom HF repo ids allowed); languages are validated against the list plus `"auto"` (mapped to `None` for faster-whisper auto-detect in app.py).
- `dashboard.py` — localhost-only (`127.0.0.1:4738`) server. `PAGE` is one HTML string with placeholders (`__HOTKEYS__`, `__MODELS__`, `__LANGS__`) substituted at serve time from config.py — add new shared constants that way, don't duplicate lists in the HTML. Two screens via hash routing: `#/` history (stats tiles, SVG chart, search) and `#/settings` (config form → `POST /api/config` → validate → write config.toml; changes need restart; `POST /api/restart` uses `systemctl --user` only when under systemd). Theming: light/dark via `prefers-color-scheme` plus a persisted manual toggle setting `data-theme`.
- `db.py` — SQLite `history.db` (Linux XDG `~/.local/share`, Windows `%LOCALAPPDATA%`, macOS `~/Library/Application Support`), WAL, one lock-guarded connection. Schema changes need a migration in `_migrate()` (PRAGMA table_info check + ALTER TABLE) — old DBs in the wild must keep working. (`config.py`'s `config_path()` follows the same per-platform convention for `config.toml`.)
- `feedback.py` — best-effort desktop notify + beep, per-platform (`notify-send`/`paplay` on Linux, `osascript`/`afplay` on macOS, `winsound` on Windows); must stay silent-on-missing.
- `tray.py` — shared menu-bar/system-tray icon (Open Dashboard / Quit) for **Windows and macOS**, imported behind a `sys.platform` check in `__main__.py` (Linux has no tray). `pystray`/`pillow` are lazy imports. macOS constraint: the tray must own the **main thread**, so on macOS `__main__.py` runs `app.run()` on a background thread and the tray blocks main.

Terminal output is quiet by default; per-transcription logs only under `--verbose` (`_log()` in app.py). The dashboard is the primary log.

## Packaging

### Linux (.deb)

**Linux (`.deb`):** `build-deb.sh <version>` assembles `omnihear_<v>_amd64/` from `DEBIAN-template/` (version substituted into control), `src/omnihear/` → `/opt/omnihear/`, wrapper → `/usr/bin/omnihear`, `systemd/omnihear.service` → `/usr/lib/systemd/user/`. The .deb does **not** vendor Python deps: `postinst` creates a venv in `/opt/omnihear` and pip-installs `requirements.txt` at install time (internet required). `Depends: python3 (>= 3.11)` because of `tomllib`. Committed `omnihear_<v>_amd64/` trees are build artifacts of past releases.

**Windows (`.exe`)** and **macOS (`.dmg`):** both freeze deps in at build time via PyInstaller (opposite of the Linux runtime-pip model). Windows: `windows/` (`entry.py`, `omnihear.ico`, `omnihear.iss` Inno Setup) → onedir `.exe` + installer. macOS: `macos/` (`entry.py`, `omnihear.spec`, `omnihear.png` source icon → `make-icns.sh`, `build-dmg.sh`, and the no-op-without-secrets `sign.sh`/`entitlements.plist` for Developer-ID signing) → `Omnihear.app` (arm64, `LSUIElement` menu-bar agent) → drag-install DMG. All three build paths run from tag pushes in `.github/workflows/release.yml`; `macos/update-cask.sh` pushes the Homebrew Cask to a separate `homebrew-omnihear` tap. Version is always the git tag / build arg — `__init__.py`'s `__version__` is stale and unused, don't wire builds to it.
