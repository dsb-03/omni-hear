# omnihear

Push-to-talk local Whisper transcription for X11 desktops.

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

## Web dashboard

While omnihear runs, a local-only dashboard is served at
`http://127.0.0.1:4738` (change with `dashboard_port`, disable with
`--no-dashboard`). It shows searchable transcription history, usage stats
with a words-per-day chart, and lets you edit the config file from the
browser (changes take effect after restarting omnihear; the Restart button
works when running under systemd).

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

## Requirements

- X11 session (Wayland not currently supported — global hotkeys and
  synthetic keystroke injection work differently there)
- A microphone
