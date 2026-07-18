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

## Updating

```bash
sudo apt update && sudo apt upgrade
```

## Development / publishing new versions

See [SETUP.md](./SETUP.md) for the full guide (GPG signing key, GitHub Pages,
manual publish steps, and the automated release workflow).

Quick version:
```bash
# edit src/omnihear.py, then:
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
