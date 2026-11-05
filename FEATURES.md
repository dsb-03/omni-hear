# omnihear: features and improvements

Every new feature and improvement in one list. Checked items are built on
this branch: the Wayland and overlay work is planned as **1.9.0**, and the
dictation features as **1.10** (beta, off by default until they've had a
release of real use). Unchecked items are planned, tagged with the release
they're aimed at. [ROADMAP.md](ROADMAP.md) has the reasoning, design notes
and rollout process for each one.

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

### Built in this branch (1.10, beta)

These are off by default; turn them on in the dashboard (Settings >
Dictation) or `config.toml`.

- [x] **Paste insertion** (`type_method = "paste"`). The text goes on the
  clipboard and omnihear sends the paste shortcut (Shift+Insert on Linux,
  Ctrl+V on Windows, Cmd+V on macOS), then restores whatever you had copied
  about 0.6 s later. Instant for long text and works with every keyboard
  layout and script.
  - Never overwrites something you copied in the meantime. Rapid
    dictations paste in order and still restore your original clipboard.
  - Falls back to typing when no clipboard tool is available, and to
    "copied, press Ctrl+V" if the paste key can't be sent.
  - Linux uses xclip/xsel, or wl-clipboard on KDE and wlroots. On GNOME it
    goes through the X11 clipboard bridge, because GNOME lacks the
    clipboard protocol `wl-copy` needs. On Windows, dictated text is kept
    out of clipboard history and cloud sync.
- [x] **Hands-free mode** (`hands_free = true`). Double-tap the hotkey to
  keep recording without holding it; tap once more to stop. A single quick
  tap is discarded. The overlay's red dot turns into a stop square while
  locked.
- [x] **Maximum recording length** (`max_recording_seconds`, default 300):
  recording stops and is transcribed at the limit, with a notification.
- [x] **Cleanup** (`cleanup = "light"`). Removes "um/uh/er", stutters ("the
  the", "I I") and spoken self-corrections ("at 2, actually 3" becomes
  "at 3"; "send it to John, no wait, Sarah" becomes "send it to Sarah").
  - Deliberately cautious: it only rewrites a correction when both sides
    are clearly the same kind of thing (numbers, days, names, or the same
    phrase with one word changed). "That was, actually, quite good" stays
    as is.
  - English only.
  - Spoken lists are *not* turned into bullets yet: a typed newline is
    Enter, which sends the message in chat apps. Moved to per-app styles
    (1.11).
- [x] **First-run setup wizard** in the dashboard (Setup tab, opens by
  itself the first time). Three steps:
  1. The `--doctor` checks, with copy buttons for every fix command.
  2. A live hotkey and microphone test with a level meter.
  3. A practice box that confirms dictation really lands.
- [x] **Paste last transcript**: an optional hotkey (`paste_last_hotkey`)
  puts your last transcript at the cursor again, plus Copy buttons on every
  transcript in the dashboard.
- [x] **Record any hotkey by pressing it** in the dashboard: main hotkey,
  paste-last and voice Q&A, with a Clear button for the optional ones.

### Planned

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

### Built in this branch (1.9.0 and 1.10)

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
- [x] **Hotkeys can't be triggered by omnihear's own typing.** On X11,
  Windows and macOS, keys omnihear injects are visible to its own hotkey
  listener. Shift or single-letter hotkeys could start or lock a recording
  while text was typed, and a paste-last hotkey like Shift+V could fire on
  every capital V and loop. Those presses are now ignored while omnihear
  is inserting text. Your system paste shortcut can't be chosen as the
  paste-last hotkey.
- [x] **Releasing an unrelated key no longer cuts a recording short.**
  Each hotkey combo now tracks its own press and release, on X11 and
  Wayland alike.
- [x] **A missing or busy microphone no longer stops hotkeys working.**
  omnihear shows an error and keeps listening for the hotkey.
- [x] **Fully offline dashboard.** It loaded a Google font from the
  internet; it now uses local fonts only, as the project rules require.
- [x] **Dashboard fixes:**
  - Opening a History or detail link directly no longer crashes the page.
  - Searches containing an apostrophe work.
  - Pages fit phone screens.
  - The correction box is readable in dark mode.
- [x] **The overlay stays visible** while a newer recording is running
  (it could be hidden by the previous transcription finishing).

### Planned

- [ ] **Hotkeys on Wayland without the `input` group** via the desktop's
  GlobalShortcuts portal (GNOME 48+, KDE 6). Removes the last manual setup
  step and the broad keyboard-read permission. *(continuous)*
- [ ] **Non-US keyboard layouts** typed correctly by the built-in Wayland
  typer (de, fr, uk, es, it). Paste mode (1.10, beta) already handles
  every layout. *(continuous)*
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
