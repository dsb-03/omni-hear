# omnihear

Push-to-talk local Whisper transcription for Linux (X11), Windows, and macOS.

Hold a hotkey, speak, release — your speech is transcribed locally with
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) (no cloud, no
network calls at runtime) and typed directly into whatever field currently
has keyboard focus.

## Install

```bash
curl -fsSL https://dsb-03.github.io/omni-hear/pubkey.gpg | sudo gpg --dearmor -o /usr/share/keyrings/omnihear.gpg
echo "deb [signed-by=/usr/share/keyrings/omnihear.gpg] https://dsb-03.github.io/omni-hear/ stable main" \
  | sudo tee /etc/apt/sources.list.d/omnihear.list
sudo apt update
sudo apt install omnihear
```

## Usage

```bash
omnihear                                   # defaults: base.en model, right-Ctrl hotkey
omnihear --model small.en --hotkey f9      # custom model + hotkey
omnihear --list-devices                    # list microphones
omnihear --help                            # full CLI options
```

The terminal stays quiet during normal use (transcriptions are visible in
the web dashboard); pass `--verbose` (or set `verbose = true`) to print
per-transcription output for debugging.

## Web dashboard

While omnihear runs, a local-only dashboard is served at
`http://127.0.0.1:4738` — enabled by default (change the port with
`dashboard_port`, opt out with `--no-dashboard` or `dashboard = false`).
The History screen (home) shows usage stats — including per-transcription
CPU and memory averages — a words-per-day chart, and a searchable
transcription table; the Settings screen edits the config file from the
browser (changes take effect after restarting omnihear; the Restart button
works when running under systemd). A light/dark theme toggle is provided
and follows your system theme by default.

## Configuration

Settings live in `~/.config/omnihear/config.toml`. Precedence:
CLI flag > config file > built-in default. Generate the file with your
current settings:

```bash
omnihear --write-config
```

Keys mirror the CLI flags (`model`, `hotkey`, `device`, `compute_type`,
`language`, `beam_size`, `min_duration`, `input_device`, `type_method`,
`sample_rate`) plus `dashboard`, `dashboard_port`, `notify`, `beep`,
`history`, and `idle_unload_minutes`.

## Running as a service

```bash
systemctl --user enable --now omnihear
```

The package ships a systemd user unit that starts omnihear with your
graphical session and restarts it on failure.

## History

Every transcription is saved to `~/.local/share/omnihear/history.db`
(SQLite). Opt out with `--no-history` or `history = false` in the config.

## Resource usage

The Whisper model is loaded lazily on the first hotkey press and unloaded
after 10 idle minutes (`idle_unload_minutes`, 0 = never), so omnihear sits
at a few tens of MB of RAM when you're not dictating. The first press after
an unload takes a few extra seconds while the model reloads.

## Feedback

Desktop notifications (`notify-send`, needs `libnotify-bin`) fire on model
load, transcription results, and errors; disable with `--no-notify` or
`notify = false`. An optional record-start beep is available with `--beep`.

## Updating

```bash
sudo apt update && sudo apt upgrade
```

## Development / publishing new versions

See [SETUP.md](./SETUP.md) for the full guide (GPG signing key, GitHub Pages,
manual publish steps, and the automated release workflow).

Quick version:
```bash
# edit src/omnihear/, then:
./build-deb.sh 1.1.0
GPG_KEY_ID=you@example.com ./scripts/update-apt-repo.sh omnihear_1.1.0_amd64.deb
git add docs/
git commit -m "Publish omnihear 1.1.0"
git push
```

Or tag a release (`git tag v1.1.0 && git push origin v1.1.0`) to let
`.github/workflows/release.yml` build and publish it automatically.

## Windows

An unsigned installer is published on the
[GitHub Releases](../../releases) page as `omnihear-setup-*.exe`. Windows
SmartScreen will flag it as unrecognized — click "More info" then
"Run anyway" to proceed.

The first hotkey press downloads the selected Whisper model, so it takes a
few extra seconds. Config lives at `%APPDATA%\omnihear\config.toml`,
history at `%LOCALAPPDATA%\omnihear\history.db`. Omnihear runs from a
system tray icon (no terminal window) with "Open Dashboard" and "Quit"
menu items; the dashboard's Restart button relaunches the process directly
(no systemd equivalent needed on Windows).

## macOS

Apple Silicon (arm64) only. Install one of two ways:

```bash
# Homebrew (requires the tap to be set up once — see below)
brew install --cask <your-user>/omnihear/omnihear

# or download omnihear-<version>-arm64.dmg from the Releases page,
# open it, and drag Omnihear to Applications.
```

**First launch (unsigned builds):** until the build is notarized, Gatekeeper
blocks it. Either right-click the app → **Open** (then confirm once), or run:

```bash
xattr -dr com.apple.quarantine /Applications/omnihear.app
```

**Permissions** — grant these in **System Settings → Privacy & Security**
(macOS will prompt on first use):

- **Microphone** — to record audio.
- **Accessibility** — to type transcribed text into the focused field.
- **Input Monitoring** — to receive the global push-to-talk hotkey.

Omnihear runs as a menu-bar app (no Dock icon or terminal window) with
**Open Dashboard** and **Quit** items. The first hotkey press downloads the
selected Whisper model, so it takes a few extra seconds. Mac users can use ⌘
in hotkeys (e.g. `cmd_r`). Config lives at
`~/Library/Application Support/omnihear/config.toml`, history at
`~/Library/Application Support/omnihear/history.db`.

> Note: unsigned/ad-hoc-signed builds may re-prompt for Accessibility/Input
> Monitoring after each app update. Developer-ID signing (see SETUP.md) makes
> the grants stick.

## Requirements

- **Linux:** X11 session (Wayland not currently supported — global hotkeys and
  synthetic keystroke injection work differently there)
- **Windows:** via the installer above
- **macOS:** Apple Silicon (arm64), macOS 11+
- A microphone
