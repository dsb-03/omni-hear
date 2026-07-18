# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Push-to-talk local Whisper transcription for X11. Hold a hotkey (or combo) → mic records → release → faster-whisper transcribes locally → text is typed into the focused field. Distributed as a .deb through a self-hosted, GPG-signed APT repo served from GitHub Pages out of `docs/`.

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

- **Stdlib only** for new Python code — the package's only pip deps are the four in `src/requirements.txt`. The dashboard is plain `http.server` + one self-contained HTML string (no CDN, no external assets; must work fully offline).
- **X11 only**; text injection via pynput or xdotool. No Wayland support.
- Never modify `docs/` by hand — it is the live APT repo, regenerated only by `scripts/update-apt-repo.sh`.

## Architecture

Single process, `src/omnihear/`:

- `__main__.py` — argparse; defaults are seeded from the config file, so precedence is CLI flag > `~/.config/omnihear/config.toml` > `config.DEFAULTS`. Wires App + db + dashboard together.
- `app.py` — recording/transcription. Key behaviors that span the file: the Whisper model is **lazy-loaded** on first hotkey press and **unloaded after idle** (`idle_unload_minutes`, guarded by a model lock); transcriptions are serialized through a single worker thread + queue (ordering guarantee — don't spawn per-utterance threads); hotkeys support `+`-combos ("ctrl_l+space") parsed into a frozenset of pynput keys, recording starts when the full set is held, stops when any member releases.
- `config.py` — the **single source of truth** for constants shared with the frontend: `SPECIAL_KEY_NAMES`, `KEY_DISPLAY_NAMES`, `MODEL_NAMES` (official faster-whisper list), `LANGUAGE_NAMES` (all 100 codes), `DEFAULTS`, validation (`validate_updates`, `validate_hotkey`). TOML read via `tomllib`, written by a small hand-rolled flat serializer (stdlib has no writer). Model names stay free-form (custom HF repo ids allowed); languages are validated against the list plus `"auto"` (mapped to `None` for faster-whisper auto-detect in app.py).
- `dashboard.py` — localhost-only (`127.0.0.1:4738`) server. `PAGE` is one HTML string with placeholders (`__HOTKEYS__`, `__MODELS__`, `__LANGS__`) substituted at serve time from config.py — add new shared constants that way, don't duplicate lists in the HTML. Two screens via hash routing: `#/` history (stats tiles, SVG chart, search) and `#/settings` (config form → `POST /api/config` → validate → write config.toml; changes need restart; `POST /api/restart` uses `systemctl --user` only when under systemd). Theming: light/dark via `prefers-color-scheme` plus a persisted manual toggle setting `data-theme`.
- `db.py` — SQLite at `~/.local/share/omnihear/history.db` (XDG-aware), WAL, one lock-guarded connection. Schema changes need a migration in `_migrate()` (PRAGMA table_info check + ALTER TABLE) — old DBs in the wild must keep working.
- `feedback.py` — best-effort `notify-send`/`paplay`; must stay silent-on-missing.

Terminal output is quiet by default; per-transcription logs only under `--verbose` (`_log()` in app.py). The dashboard is the primary log.

## Packaging

`build-deb.sh <version>` assembles `omnihear_<v>_amd64/` from `DEBIAN-template/` (version substituted into control), `src/omnihear/` → `/opt/omnihear/`, wrapper → `/usr/bin/omnihear`, `systemd/omnihear.service` → `/usr/lib/systemd/user/`. The .deb does **not** vendor Python deps: `postinst` creates a venv in `/opt/omnihear` and pip-installs `requirements.txt` at install time (internet required). `Depends: python3 (>= 3.11)` because of `tomllib`. Committed `omnihear_<v>_amd64/` trees are build artifacts of past releases.
