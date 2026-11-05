# omnihear: features and improvements

Every new feature and improvement in one list. Checked items are built on
this branch (going out as **1.9.0**). Unchecked items are planned, tagged
with the release they're aimed at. [ROADMAP.md](ROADMAP.md) has the
reasoning, design notes and rollout process for each one.

## New features

### Built in this branch (1.9.0)

- [x] **New recording overlay.** A floating pill, the same on Linux,
  Windows and macOS:
  - **Listening:** a red dot with a pulsing halo, plus a waveform that
    follows your actual voice (live mic level; it used to be a canned
    animation). The newest sound sits in the middle and ripples outward.
  - **Transcribing:** the dot becomes an amber spinner and the bars ease
    into a smooth flowing wave with a highlight sweeping across.
  - **No mic signal:** if the mic sends nothing in the first 1.5 s (muted
    or wrong device), the pill turns grey so you know before you finish
    talking.
  - Fades in and out. Real rounded ends on Windows and macOS.
- [x] **Typing on Wayland with nothing else to install.** A built-in
  virtual keyboard works on GNOME, KDE and wlroots (Sway, Hyprland). No
  ydotool daemon, and no wtype (which never worked on GNOME or KDE).
- [x] **`omnihear --doctor`** checks your setup (session, keyboard access,
  typing, microphone, keyboard layout, model files, overlay, notifications)
  and prints the exact command to fix each problem.
- [x] **Accented letters and emoji on Wayland**, typed through IBus
  (GNOME's default input method).
- [x] **Keyboards connected after start work on Wayland**: Bluetooth
  keyboards, docks, USB hot-plug.
- [x] **Punctuation keys as hotkeys on Wayland** (for example
  `` ctrl_l+` ``).
- [x] **Landing page** at https://dsb-03.github.io/omni-hear/ with install
  steps per platform, features, FAQ, and a live demo of the new overlay.

### Planned

**1.10: Feel like Flow**
- [ ] **Paste insertion** (`type_method = "paste"`): instant for long text,
  works with every keyboard layout and script, and restores your clipboard
  afterwards. Falls back to typing, then to "copied, press Ctrl+V".
- [ ] **Hands-free mode**: double-tap the hotkey to keep recording without
  holding it, tap again to stop. Includes a maximum-length safety cap.
- [ ] **Cleanup, rule-based**: removes "um/uh", repeated words ("the the")
  and self-corrections ("at 2, actually 3" becomes "at 3"), and formats
  spoken lists as bullets.
- [ ] **First-run setup wizard** in the dashboard: doctor checks with
  one-click copy fixes, a mic test with a live meter, a hotkey test, and a
  practice box.
- [ ] **Paste last transcript**: a button and an optional hotkey for when
  the text went to the wrong window.

**1.11: Personal**
- [ ] **Personal dictionary**: add or pin names and jargon. Merges with the
  words Common Brain learns automatically. Import and export as plain text.
- [ ] **Snippets**: say a trigger phrase ("insert my address") to type a
  saved block of text.
- [ ] **Per-app styles**: casual in chat, formal in email, set per app in
  the dashboard (X11, Windows and macOS; GNOME Wayland uses the default).
- [ ] **Insights**: words per minute, time saved vs. typing, daily streak,
  and top apps.

**1.12: Local AI editing**
- [ ] **Command Mode**: select text, hold a key, and say "make this shorter"
  or "turn this into bullets". A local Ollama model rewrites it in place.
- [ ] **Smart cleanup**: an optional local-LLM pass for grammar and tone,
  with a latency budget that falls back to rule-based cleanup.
- [ ] **Faster long dictations**: transcribe in chunks at natural pauses
  while you're still talking.
- [ ] **Whisper mode**: a profile for speaking quietly (open-plan offices,
  late nights).
- [ ] **Language switching mid-session** when the language is set to auto.

## Other improvements

### Built in this branch (1.9.0)

- [x] **Fixed a fresh-install failure on Ubuntu.** The `.deb` failed to
  install on a stock desktop because a dependency (`evdev`, pulled in by
  pynput) needs a C compiler to build. It's now skipped; omnihear never
  used it.
- [x] **The `.deb` sets up Wayland typing permissions itself** (udev rule
  and kernel module autoload), with no reboot needed. Removing the package
  reverts it.
- [x] **Safer hotkeys:** omnihear ignores its own virtual keyboard, so
  typing a capital letter can no longer trigger a Shift hotkey. Held keys
  are released when a keyboard disconnects.
- [x] **Smarter backend choice:** never picks wtype on GNOME or KDE, and
  gives clearer hints (for example "you were added to the input group but
  need to log out").
- [x] **Overlay degrades gracefully** when there's no X display at all.
- [x] **Leaner package dependencies:** `libportaudio2` instead of the dev
  package, unused X11 libraries dropped, ydotool/wtype now optional.
- [x] **Ready for Python 3.14** (newer Ubuntu releases). Verified that all
  heavy dependencies ship wheels for it.
- [x] **One animation model for every platform** (`overlay_anim.py`) with a
  headless self-check, so Linux, Windows and macOS can't drift apart.

### Planned

- [ ] **Hotkeys on Wayland without the `input` group** via the desktop's
  GlobalShortcuts portal (GNOME 48+, KDE 6). Removes the last manual setup
  step and the broad keyboard-read permission. *(continuous)*
- [ ] **Non-US keyboard layouts** typed correctly by the built-in Wayland
  typer (de, fr, uk, es, it); paste covers the rest. *(continuous)*
- [ ] **More packages:** arm64 `.deb`, an offline `.deb` with bundled
  Python packages, Fedora RPM, AUR. *(continuous)*
- [ ] **Signed installers:** Windows (no SmartScreen warning) and macOS
  notarization (permissions persist across updates). *(continuous)*
- [ ] **Opt-in update notice** in the dashboard. *(continuous)*
- [ ] **Automated tests and CI:** stdlib unit tests on Python 3.11 to 3.14,
  plus an end-to-end Wayland typing test in a headless GNOME session.
  *(continuous)*
- [ ] **Release process:** a `testing` APT channel for release candidates,
  every new feature behind a setting for one release before it becomes the
  default, a "Linux setup" issue template that asks for `--doctor` output,
  and a validation matrix across Ubuntu 24.04, 25.10, 26.04, Kubuntu,
  Debian and wlroots. *(continuous)*
