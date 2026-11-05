# omnihear roadmap

What's next for omnihear, and how each piece ships. For the plain checklist
of features and improvements, see [FEATURES.md](FEATURES.md). The reference
point is
**Wispr Flow**, the most polished push-to-talk dictation app right now. The
plan is to match how it *feels* to use while keeping omnihear's rules:
everything runs locally, it works offline, new Python code is stdlib-only,
and Linux (X11 and Wayland), Windows and macOS all keep working.

## Where omnihear stands vs. Wispr Flow

| Capability | Wispr Flow | omnihear today | Plan |
|---|---|---|---|
| Hold-to-talk into any app | Fn key | Any key/combo | Done |
| Hands-free mode (lock recording) | Double-tap / Fn+Space | No | Phase 1 |
| Insertion | Clipboard paste, restores clipboard | Simulated typing | Phase 1: `paste` method |
| Live "Flow bar" with mic level | Yes | Yes: live waveform, spinner while transcribing, no-signal warning | Done (1.9.0) |
| Filler-word removal, self-corrections ("2pm, actually 3") | AI auto-edit (cloud) | Spoken punctuation, "scratch that" | Phase 1 (rules), Phase 3 (local LLM) |
| Personal dictionary | Auto-learned + manual | Common Brain (auto, beta) | Phase 2: manual UI |
| Snippets (voice shortcuts) | Yes | No | Phase 2 |
| Per-app tone/style | Yes | No | Phase 2 |
| Command Mode (select text, speak an edit) | Yes (cloud LLM) | Voice Q&A only (Ollama) | Phase 3 |
| Whispering / quiet speech | Yes | No | Phase 3 |
| Stats (WPM, time saved, streaks) | Yes | Words/day, latency, CPU/RAM | Phase 2 |
| Guided onboarding + permission checks | Yes | macOS prompts; `--doctor` CLI | Phase 1: dashboard wizard |
| Privacy | Cloud, with a zero-retention option | Fully local | Our edge, keep it |
| Linux / Wayland | No | Yes | Our edge, harden it (Phase 0, 4) |

Where we win: privacy, offline use, Linux support, choice of model, and history
in a SQLite file the user owns. Where Flow wins: polish, editing smarts,
insertion speed and reliability, and personalization. Phases 1–3 close those
gaps without a cloud dependency.

---

## Phase 0: Ubuntu Wayland works out of the box (1.9.0, this branch)

Ubuntu 24.04+ defaults to Wayland, and Ubuntu 25.10+ (GNOME 49+) has no X11
session at all, so Wayland is now the main Linux path.

**Shipped on this branch**

- **Built-in Wayland typer** (`uinput_keyboard.py`): a stdlib `/dev/uinput`
  virtual keyboard, now the `type_method = "auto"` default on Wayland. It
  works on GNOME, KDE and wlroots with no daemon. Before this, users needed
  ydotool plus its daemon and uinput setup, or wtype, which doesn't work on
  GNOME or KDE at all.
- **udev rule** (`udev/70-omnihear-uinput.rules`, `uaccess`, the same rule
  Steam ships) plus uinput module autoload, installed by the .deb and applied
  in `postinst` with no reboot.
- **Fix for a fresh-install failure:** pynput ≥ 1.8 depends on `evdev`, which
  has no wheels and won't build without gcc and python3-dev, so `postinst`
  failed on a stock Ubuntu desktop. pynput is now installed `--no-deps`
  (omnihear only uses its X11 backend).
- **Hotkey hardening:** keyboards plugged in or paired after start are picked
  up, held keys are released when a device disappears, omnihear's own virtual
  keyboard is ignored (otherwise typing "Hi" presses Shift and can fire a
  `shift_l` hotkey), and punctuation hotkeys work on Wayland.
- **New overlay on every platform**, drawn from one shared model
  (`overlay_anim.py`). Listening shows a red dot with a pulsing halo and a
  waveform driven by the live mic level (RMS from the audio callback),
  rippling out from the centre. Transcribing shows an amber spinner and a
  flowing wave with a sweeping highlight. It turns grey if no signal arrives
  in the first 1.5 s (muted or wrong mic), and fades in and out. Tk on
  Linux and Windows (real rounded pill via a colour key on Windows); AppKit
  on macOS.
- **`omnihear --doctor`**: checks the session, input-group access (including
  "added to the group but not logged out yet"), uinput, typer, keyboard
  layout, microphone, model deps and the overlay, and prints the exact fix
  for each problem.
- Package hygiene: `libportaudio2` instead of `portaudio19-dev`, unused X11
  libs dropped, ydotool/wtype moved to Suggests.
- Verified that cp314 wheels exist for every heavy dependency
  (ctranslate2, onnxruntime, av, numpy), so Ubuntu releases that ship Python
  3.14 install cleanly.

**Validation matrix (manual, before tagging stable)**

| Distro | Desktop | Session | Must pass |
|---|---|---|---|
| Ubuntu 26.04 LTS | GNOME | Wayland | install, doctor clean, dictate in Firefox, Chrome, GNOME Text Editor, GNOME Terminal, VS Code; accented text; voice undo |
| Ubuntu 25.10 | GNOME (no X11 session) | Wayland | same |
| Ubuntu 24.04 LTS | GNOME | Wayland **and** X11 | same, plus X11 regression check (pynput path) |
| Kubuntu 26.04 | KDE Plasma 6 | Wayland | typing via uinput (wtype is not auto-picked) |
| Debian 13 | GNOME | Wayland | install from APT |
| Any | Sway / Hyprland | Wayland | uinput first, wtype fallback |

Check for each: Bluetooth keyboard paired after start, the systemd user
service after a reboot, upgrade from 1.8.0 (an existing `ydotool` config still
works), and `apt remove` (udev rule reverted).

**Known limits, tracked below:** the uinput typer assumes a US QWERTY layout
(Phase 1 paste fixes it); non-ASCII goes through IBus `Ctrl+Shift+U`, so it
fails where IBus isn't the input method; hotkeys still need the `input`
group (Phase 4 portal removes that).

---

## Phase 1: Feel like Flow (1.10)

Theme: faster, more trustworthy insertion and a first run that just works.

1. **`type_method = "paste"`** (opt-in in 1.10, default in 1.11 where it
   tests well). Copy to the clipboard, send paste, then restore the previous
   clipboard after about 300 ms. This is instant for long text and works with
   any layout and any script.
   - X11: `xclip`/`xsel` (or Tk's clipboard) + Ctrl+V; Windows: `ctypes`
     clipboard + Ctrl+V; macOS: `pbcopy` + Cmd+V.
   - Wayland: `wl-copy` + **Shift+Insert** via the uinput keyboard
     (Shift+Insert pastes in GTK, Qt, Chromium, Firefox and VTE terminals,
     which avoids the Ctrl+V vs Ctrl+Shift+V split). Restore only text
     clipboards.
   - Fallback: if paste fails, type it; if typing fails, leave the text on
     the clipboard and notify "copied — press Ctrl+V".
2. **Hands-free mode.** Double-tap the hotkey to lock recording, tap again to
   stop. Uses a 350 ms window in both pynput and evdev monitors and a
   `max_recording_seconds` safety cap. The overlay adds a lock state to
   the 1.9.0 pill.
3. **Rule-based cleanup** (`cleanup = "off" | "light"`, stdlib in
   `commands.py`): drop fillers (um, uh, er, "you know" at clause edges),
   collapse stutters ("the the"), handle inline backtracking ("at 2, actually
   3" → "at 3", "no wait" / "I mean" patterns), and turn spoken lists into
   bullets when there's "first/second/third". Each rule ships with a
   self-check case like the existing ones.
4. **Onboarding wizard in the dashboard.** On first run, `#/welcome` shows the
   `--doctor` results (`/api/doctor`) with copy-to-clipboard fixes, a mic test
   with a live meter, a "press your hotkey" test, and a practice text box.
   Linux shows the `input` group step only when it's actually needed.
5. **"Paste last transcript"** dashboard button and optional hotkey,
   Flow's recovery path for when focus was in the wrong place.

**Rollout:** each item ships behind its own config key. The dashboard shows
it under "Beta" with default off for 1.10.x. Defaults flip in 1.11 after one
release with no regressions reported against the matrix.

---

## Phase 2: Personalization (1.11)

1. **Personal dictionary UI.** Add, remove and pin words. Merge them with
   Common Brain's learned terms, feed them to `hotwords` / `initial_prompt`,
   and apply post-correction (metaphone matching already exists in
   `brain.py`). Import/export as plain text.
2. **Snippets.** A spoken trigger ("insert my address", "sign off") expands
   to stored text. They live in a `snippets` table (`_migrate()` adds it),
   match only on the whole utterance after normalization so prose never
   misfires, and are edited in the dashboard.
3. **Per-app styles.** Detect the focused app: X11 via `xdotool
   getactivewindow getwindowclassname`, Windows via `GetForegroundWindow`
   (`ctypes`), macOS via `NSWorkspace` (already in pyobjc). GNOME Wayland has
   no API, so it falls back to the default style. A style is rule-based
   (casual: no trailing period, keep lowercase; formal: capitalize, full
   punctuation) plus an optional local-LLM pass in Phase 3. The dashboard
   maps app → style.
4. **Insights.** Words per minute (spoken vs. a 40 WPM typing baseline),
   time saved, daily streak, and top apps (where detectable), all from
   `history.db`.

---

## Phase 3: Local AI editing (1.12)

1. **Command Mode.** Select text, hold the command hotkey, and say "make this
   shorter" or "turn this into bullets". omnihear grabs the selection (X11
   PRIMARY; elsewhere copy-then-read-clipboard), rewrites it with the local
   Ollama model (same shell-out as `qna.py`), and pastes the result over the
   selection. With nothing selected, it falls back to today's voice Q&A.
2. **Smart cleanup** (`cleanup = "smart"`): an optional LLM pass for
   grammar, self-corrections and per-app style. It's skipped when Ollama is
   missing, and there's a latency budget (skip if over 1.5 s; insert the
   rule-cleaned text instead).
3. **Lower latency on long dictations.** Chunk audio at VAD pauses while
   still recording and transcribe the chunks in the existing worker queue,
   so release → text depends on the last chunk, not the whole clip. Ordering
   still goes through the single worker.
4. **Whisper mode.** A quiet-speech profile with gain normalization before
   VAD, lower VAD and no-speech thresholds, and a hint in the overlay.
5. **Code-switching.** Auto-detect the language per utterance when
   `language = "auto"`, and pin it for the rest of a hands-free session.

---

## Phase 4: Platform and distribution (continuous)

1. **Hotkeys without the `input` group on Wayland.** Use the XDG
   GlobalShortcuts portal (GNOME 48+, KDE 6), which has
   `Activated`/`Deactivated` signals, so push-to-talk works. It talks to the
   portal through the `gdbus` CLI (stdlib subprocess, like the other
   shell-outs), with evdev as the fallback. This removes the one manual setup
   step and the "can read every keystroke" permission.
2. **Keyboard-layout-aware typing.** Read the active XKB layout (GNOME
   `gsettings`, KDE `kxkbrc`) and map through per-layout tables for common
   layouts (de, fr, uk, es, it). Paste covers everything else.
3. **Packaging.** arm64 .deb; vendor wheels into the .deb so install needs no
   internet and no pip at install time (larger package, reproducible); RPM
   for Fedora; AUR; Flatpak investigated (uinput and evdev need host access,
   so probably not a fit).
4. **Signing.** Windows Authenticode (removes the SmartScreen warning) and
   macOS notarization (permission grants stick across updates).
5. **Update notice.** An opt-in dashboard banner when a newer GitHub release
   exists (one request per day, off by default, in keeping with the
   no-network-at-runtime promise).
6. **Tests and CI.** A stdlib `unittest` suite covering config validation,
   commands, keymaps, evdev parsing and uinput event encoding (with a pipe
   standing in for the device). CI runs py_compile + unittest on Python
   3.11–3.14 and a smoke test in a headless `mutter --wayland` session on the
   Ubuntu runner (modprobe uinput, type into a test window, assert the text).

---

## How releases roll out

- **Channels.** Stable is today's `stable` APT suite and GitHub releases.
  Add a **`testing` APT suite** (`dists/testing`, the same
  `update-apt-repo.sh` with a suite argument) that `-rc` tags publish to, so
  Linux testers get release candidates through APT. Prerelease tags already
  skip the stable APT publish. Windows and macOS RCs stay GitHub prereleases.
- **Sequence for each minor release:** `vX.Y.0-rc1` → validation matrix
  plus a week of testing-channel use → `vX.Y.0` → patch releases as needed.
- **Feature flags.** New behavior lands default-off behind a config key
  (shown as Beta in the dashboard) and flips default-on one minor release
  later. Destructive changes (insertion method, cleanup) never flip
  silently; the dashboard notes the change after upgrade.
- **Feedback.** Add a "Wayland/Linux setup" issue template that asks for
  `omnihear --doctor` output. Opt-in analytics stays version/platform only.
- **Rollback.** The APT pool keeps every version (`--multiversion`), so
  `sudo apt install omnihear=<previous>` works. Config keys are additive and
  old configs always load.
- **Success measures (from opt-in feedback and the dashboard):** doctor
  passes on first run, time from install to first dictation under 5 minutes,
  release-to-text p50 under 1 s for short utterances on `base.en`, and zero
  "typed nothing" reports per release on the matrix.
