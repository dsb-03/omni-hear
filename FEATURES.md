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
  - Spoken lists are turned into bullets by the per-app Document style
    (1.11), not here: a typed newline is Enter, which sends the message in
    chat apps.
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

### Built in this branch (1.11, Personal)

All on the dashboard's new **Personal** tab (Insights are on the main
Dashboard). Nothing changes until you add an entry, and edits apply to the
next dictation without a restart. Stored in `history.db`, so they need
history on.

- [x] **Personal dictionary**: add names and jargon, optionally with how
  they sound when Whisper gets them wrong ("omni hear" → "Omnihear").
  - Given to Whisper as hints, pinned words first, merged with the words
    Common Brain has learned (which also show up as one-click suggestions).
  - Fixed after transcription: the spoken forms you list, the exact
    spelling ("github" → "GitHub", also when split as "git hub"), and
    sound-alikes.
  - Import and export as plain text (`*` pins, `= a, b` lists sound-alikes).
- [x] **Snippets**: say a trigger phrase ("insert my address") on its own
  to type a saved block of text. Only the whole dictation triggers it, so
  it never fires mid-sentence. History keeps what you said.
- [x] **Per-app styles**: None, Casual (no final full stop, no automatic
  capital), Formal (capitalized sentences and "I", final full stop) or
  Document (see below), per app plus a default for every other app. The
  app is detected on X11 (needs xdotool), Windows and macOS; on Wayland
  the default style applies.
- [x] **Insights**: speaking speed, time saved vs. typing at 40 wpm,
  current and longest daily streak, and top apps.
- [x] **Spoken lists → bullets** (the Document style): "first …, second
  …, finally …" or "number one … number two …" becomes a numbered list,
  "bullet point … bullet point …" a bulleted one. Needs two or more items
  in order, and the list has to start a clause, so "the first time" or
  "I was number one in the class" stay prose. Lines are typed with Enter,
  so set it only for editors and documents, not chat apps.

### Built in this branch (1.12, Local AI editing, beta)

Off by default; Settings > "Local AI editing" and "Long & quiet dictation".
The AI features need [Ollama](https://ollama.com) running on this computer
with a model pulled (`ollama pull llama3.2`); `omnihear --doctor` checks it.
omnihear only talks to a local Ollama and refuses a non-local
`OLLAMA_HOST`.

- [x] **Command Mode** (`command_hotkey`): select text, hold the key, say
  "make this shorter" or "turn this into bullets", release. The local model
  rewrites the selection in place.
  - omnihear reads the selection by sending the copy key (Ctrl+Insert on
    Linux, so terminals work too; Ctrl+C on Windows, Cmd+C on macOS) and
    puts your clipboard back afterwards. Needs a clipboard tool on Linux
    (xclip, or wl-clipboard on KDE/wlroots).
  - Nothing selected: it answers like voice Q&A.
  - Ollama not running: the selection is left untouched and you get a
    notification.
- [x] **Smart cleanup** (`cleanup = "smart"`): the light rules, then a
  local-model pass for grammar and punctuation. If it takes longer than
  `smart_cleanup_ms` (default 1.5 s) or the answer doesn't look like an
  edit of what you said, the light result is typed. The model is pre-loaded
  as you start talking.
- [x] **Faster long dictations** (`chunked_transcription`): while you're
  still talking, audio is transcribed in chunks at natural pauses (after at
  least `chunk_seconds`, default 10). On release only the last piece is
  left to transcribe. Each chunk gets the previous text as context.
- [x] **Whisper mode** (`whisper_mode`): boosts quiet audio (loudness
  normalization instead of peak), lowers the voice-detection and
  no-speech thresholds, and boosts the overlay meter so a whisper still
  shows.
- [x] **Language switching** (`code_switching`, with language = auto):
  Whisper may change language within one dictation. Without it, a chunked
  dictation keeps the language detected in its first chunk.


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
