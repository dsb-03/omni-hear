# omnihear

Push-to-talk local Whisper transcription for Linux (X11 and Wayland),
Windows, and macOS.

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
omnihear --doctor                          # check permissions/deps, print fixes
omnihear --help                            # full CLI options
```

While you hold the hotkey, a small pill at the bottom of the screen shows a
red dot and a waveform that follows your voice. It switches to an amber
spinner while transcribing, and turns grey if the microphone sends no
signal.

The terminal stays quiet during normal use (transcriptions are visible in
the web dashboard); pass `--verbose` (or set `verbose = true`) to print
per-transcription output for debugging.

What's coming next: [FEATURES.md](FEATURES.md) (checklist) and
[ROADMAP.md](ROADMAP.md) (plan and rollout).

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
`history`, and `idle_unload_minutes`. `type_method` defaults to `auto`
(pynput on X11/Windows/macOS; the built-in uinput typer on Wayland).

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

## Wayland (Linux)

Ubuntu 24.04+ (and every GNOME release since GNOME 49, which removed the
X11 session) defaults to Wayland. Wayland has no X11 global grabs or
`xdotool`, so omnihear switches backends automatically when
`XDG_SESSION_TYPE=wayland`:

1. **Hotkeys** — reads `/dev/input/event*` directly (keyboards plugged in
   or paired later are picked up automatically). Your user must be in the
   `input` group — the one manual step:

   ```bash
   sudo usermod -aG input $USER
   # then log out and back in
   ```

2. **Typing** — built in. omnihear creates its own virtual keyboard on
   `/dev/uinput`, which works on GNOME, KDE and wlroots compositors with no
   daemon. The `.deb` installs a udev rule
   (`/usr/lib/udev/rules.d/70-omnihear-uinput.rules`) that gives the
   logged-in desktop user access — the same `uaccess` rule Steam uses for
   controllers. Accented characters and emoji are entered with IBus's
   `Ctrl+Shift+U` (GNOME's default input method).

Check everything with:

```bash
omnihear --doctor
```

`type_method = "auto"` (the default) picks `uinput`, then `ydotool`, then
`wtype` (wlroots only — GNOME and KDE don't support it). Force one with
`--type-method uinput|ydotool|wtype`. Running from source, install the udev
rule yourself:

```bash
sudo cp udev/70-omnihear-uinput.rules /usr/lib/udev/rules.d/
sudo modprobe uinput && sudo udevadm control --reload-rules && sudo udevadm trigger --sysname-match=uinput
```

Known limits: typing assumes a US QWERTY layout (other layouts can get some
symbols wrong — clipboard paste is on the [roadmap](ROADMAP.md)), and
`terminal_commands` stays X11-only.

## Requirements

- **Linux:** X11 or Wayland (see Wayland section above for the extra setup)
- **Windows:** via the installer above
- **macOS:** Apple Silicon (arm64), macOS 11+
- A microphone
