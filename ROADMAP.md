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
| Hands-free mode (lock recording) | Double-tap / Fn+Space | Double-tap to lock, tap to stop (beta) | Built (1.10) |
| Insertion | Clipboard paste, restores clipboard | Typing, or clipboard paste with restore (beta) | Built (1.10) |
| Live "Flow bar" with mic level | Yes | Yes: live waveform, spinner while transcribing, no-signal warning | Done (1.9.0) |
| Filler-word removal, self-corrections ("2pm, actually 3") | AI auto-edit (cloud) | Rule-based cleanup, English (beta) | Built (1.10); local LLM in Phase 3 |
| Personal dictionary | Auto-learned + manual | Manual dictionary + Common Brain (auto, beta) | Built (1.11) |
| Snippets (voice shortcuts) | Yes | Yes | Built (1.11) |
| Per-app tone/style | Yes | Rule-based (X11, Windows, macOS) | Built (1.11) |
| Command Mode (select text, speak an edit) | Yes (cloud LLM) | Yes, local Ollama (beta) | Built (1.12) |
| Whispering / quiet speech | Yes | Whisper mode (beta) | Built (1.12) |
| Stats (WPM, time saved, streaks) | Yes | WPM, time saved, streaks, top apps | Built (1.11) |
| Guided onboarding + permission checks | Yes | Dashboard setup wizard + `--doctor` | Built (1.10) |
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

## Phase 1: Feel like Flow (1.10, built on this branch)

Theme: faster, more trustworthy insertion and a first run that just works.
Everything here is built and tested on this branch, beta and off by
default (see "Rollout" below). [FEATURES.md](FEATURES.md) has the
user-facing summary.

1. **`type_method = "paste"`** (`clipboard.py`). Save the clipboard, put the
   text on it, send the paste key through the auto-selected key backend,
   and restore the original about 0.6 s later.
   - **Paste key:** Linux sends **Shift+Insert**, which avoids the Ctrl+V
     vs Ctrl+Shift+V split between apps and terminals. Windows sends Ctrl+V
     (by virtual key, so non-Latin layouts work); macOS sends Cmd+V.
   - **Both selections on Linux:** omnihear sets PRIMARY as well as
     CLIPBOARD. Terminals built on VTE (GNOME Terminal, Ptyxis) have
     historically pasted PRIMARY on Shift+Insert, while GTK, Qt, Chromium
     and Firefox paste CLIPBOARD.
   - **Linux tool choice:** X11 uses xclip or xsel. KDE and wlroots use
     wl-copy/wl-paste first. On GNOME Wayland omnihear prefers xclip
     through XWayland: Mutter has no wlr/ext data-control protocol, so
     `wl-copy` would have to steal focus with a popup surface, while Mutter
     bridges X11 selections to Wayland apps.
   - **Restore rules:** a restore never clobbers a newer paste (each paste
     has a generation number) or something the user copied in the meantime.
     Back-to-back pastes are spaced so each app reads the right text. Image
     clipboards can't be restored; the dictated text is left in their place.
   - **Fallbacks:** if the clipboard is unavailable, omnihear types. If the
     paste key fails, it leaves the text on the clipboard and notifies
     "copied — press Ctrl+V".
   - **Windows:** dictated text is excluded from clipboard history and
     cloud sync.
   - **Tested:** X11 (pynput and xdotool), and headless sway with XWayland
     for the Wayland tools. GNOME and KDE themselves, Windows and macOS
     still need real-hardware checks.
   - **Default:** stays opt-in until it has been verified on GNOME and KDE.
2. **Hands-free mode.**
   - **Timing:** a press shorter than 0.3 s that's followed within 0.35 s by
     a second press locks the recording. The next tap stops it. A lone tap
     is discarded.
   - **Shared implementation:** the state machine lives in `App` and is
     backend-agnostic. pynput and evdev both feed it through one combo
     matcher (`evdev_hotkey.ComboMatcher`), so release semantics are
     identical on X11 and Wayland.
   - **Safety cap:** `max_recording_seconds` applies to every recording.
   - **Overlay:** shows a stop square while locked.
3. **Rule-based cleanup** (`cleanup.py`, `cleanup = "light"`).
   - **What it fixes:** fillers, function-word stutters, and spoken
     self-corrections.
   - **Guard on corrections:** a correction is only applied when the
     replaced phrase and the new one are clearly the same kind of thing
     (numbers or times, days or months, names, or a shared leading word).
     It also refuses negations, "when I say X, I mean Y", belief verbs and
     apologies.
   - **English only.**
   - **Tested:** 162 self-check cases, a 300,000-input fuzz, and 35,495 real
     English sentences with no wrong edits.
   - **Deferred:** spoken-list → bullets moves to per-app styles (Phase 2),
     because a typed newline is Enter and sends the message in chat apps.
4. **Onboarding wizard in the dashboard** (`#/welcome`, opens on first run).
   - **Step 1:** `/api/doctor` checks with copy buttons for fix commands.
   - **Step 2:** a live hotkey and mic-level test, polling `/api/status`
     only while visible.
   - **Step 3:** a practice box that detects whether dictation actually
     landed.
5. **Paste last transcript.** An optional `paste_last_hotkey` runs through
   the worker queue, so it lands after pending transcriptions and is never
   saved to history. Every transcript in the dashboard also gets a Copy
   button.
6. **Found while integrating:** omnihear's own injected keys could trigger
   its hotkeys on X11, Windows and macOS. With a Shift hotkey, typed
   capitals could lock a recording. A paste-last hotkey like Shift+V
   re-fired on every typed capital V and looped. Presses that land during
   one of our own insertions are now ignored, but only for combos the
   insertion could actually produce. The system paste shortcut is rejected
   as a paste-last hotkey.

**Rollout:**
- 1.10.x ships each item behind its own config key, off by default, in a
  "Dictation (new)" section of Settings, so it isn't hidden behind the
  sign-in Beta page.
- In 1.11, `hands_free` and `cleanup = "light"` become defaults once they've
  had a release with no regressions. `paste` follows once it's been
  checked on GNOME and KDE.

---

## Phase 2: Personalization (1.11, built on this branch)

Built in `personal.py` (dictionary, snippets, styles), `focus.py`
(focused-app detection) and `db.insights()`, on the dashboard's Personal
tab. Notes on what shipped vs. the plan below:
- The dictionary is its own `dictionary` table (word, spoken forms,
  pinned), not the Brain's `vocab` table, so it works without the beta
  sign-in. Hints merge dictionary words (pinned first) with Brain words.
- Post-correction is stdlib: listed spoken forms, exact-spelling and
  split-word matching, plus the metaphone sound-alike pass.
- Styles and app overrides live in an `app_styles` table (`*` = default)
  rather than `config.toml`, so changing them needs no restart.
- The focused app is probed on a thread while Whisper runs (no added
  latency) and stored in `transcriptions.app` for Insights.
- Spoken-list → bullets is the `document` style (Formal plus
  `personal.format_lists()`): ordinals at a clause start, "number/step N"
  and "bullet point" markers; two or more items in order, otherwise the
  text is left alone.

1. **Personal dictionary UI.** Add, remove and pin words. Merge them with
   Common Brain's learned terms, feed them to `hotwords` / `initial_prompt`,
   and apply post-correction (metaphone matching already exists in
   `brain.py`). Import/export as plain text.
2. **Snippets.** A spoken trigger ("insert my address", "sign off") expands
   to stored text. They live in a `snippets` table (`_migrate()` adds it),
   match only on the whole utterance after normalization so prose never
   misfires, and are edited in the dashboard.
3. **Per-app styles.** Also takes over spoken-list → bullets formatting,
   which is only safe where Enter doesn't send. Detect the focused app: X11 via `xdotool
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

## Phase 3: Local AI editing (1.12, built on this branch)

Built and beta, off by default. Notes on what shipped vs. the plan below:
- `llm.py` talks to Ollama's **HTTP API** on localhost (urllib) rather than
  the `ollama run` CLI that `qna.py` uses: smart cleanup needs a hard
  timeout, and the API can pre-load the model (`keep_alive`) when a
  recording starts. A non-local `OLLAMA_HOST` is refused.
- Command Mode reads the selection the same way on every platform: put a
  marker on the clipboard, send the copy key (Ctrl+Insert on Linux, which
  terminals honour too), read the clipboard back, restore it. No
  selection → voice Q&A. Ollama missing → nothing is typed over the
  selection.
- Smart cleanup runs the light rules first, then the LLM, and rejects
  answers that don't look like a light edit (length and word-overlap
  checks).
- Chunking runs on the audio thread (it must never take `_hk_lock`) and
  queues tagged `("chunk", gen, audio, duration)` jobs on the existing
  worker; the final `("transcribe", audio|None, duration, mode, gen)` job
  joins the chunk texts and runs the normal pipeline once.
- Models: smart cleanup defaults to Muesli's Qwen3.5-2B dictation-cleanup
  fine-tune (Q4_K_M GGUF, ~1.3 GB, pulled from Hugging Face through
  Ollama) in its exact raw training format; Command Mode and Q&A default
  to the general `qwen3.5:2b`. Chosen for speed, then RAM, then precision.
  `think: false` keeps Qwen3.5 from spending the budget reasoning.
- Whisper mode's overlay hint is a boosted meter, not a separate state, so
  the three overlay renderers didn't need changes.

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
