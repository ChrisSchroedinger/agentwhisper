# Changelog

All notable changes to AgentWhisper are documented here.

## 0.3.7 — 2026-07-04

### Changed
- `config.toml` now documents every setting inline: possible values,
  meanings, model size/speed trade-offs. The explanations survive
  settings changes made from the tray menu (previously a tray change
  rewrote the file without comments).

## 0.3.6 — 2026-07-04

### Fixed
- The tray status line could show "Ready" during the model download
  while `agentwhisper status` correctly said "downloading": the label
  was rendered before the download began and its refresh loop exited
  on a startup race. The refresh now runs until the model has actually
  finished loading, and the pre-download moment shows "Preparing
  speech model…" instead of "Ready".

## 0.3.5 — 2026-07-04

### Added
- Live download progress for the speech model: the tray status line
  shows "Downloading speech model… 47% (one time)" and `agentwhisper
  status` shows `engine: downloading 47%`. Measured from bytes on disk
  against the model's real size, so resumed downloads report correctly
  too.

## 0.3.4 — 2026-07-04

### Fixed
- After quitting mid-download, a restart claimed "Preparing speech
  model" instead of "Downloading": the cache check only looked for the
  model's directory, which a partial download already creates. The app
  now verifies the model is completely downloaded, so the resumed
  download is labeled (and notified) as a download again.

## 0.3.3 — 2026-07-04

### Fixed
- Quitting during the model download left a zombie process with a
  frozen tray icon (the downloader's worker threads kept the dead
  daemon alive), and a restart then showed two icons. The daemon now
  terminates for real after cleanup — the interrupted download simply
  resumes on the next start — and the tray icon unregisters itself the
  moment you quit.

## 0.3.2 — 2026-07-04

### Changed
- Quiet `.deb` installation: pip's download log no longer scrolls by.
  The postinst prints a few concise progress lines; real errors still
  show.

## 0.3.1 — 2026-07-04

### Fixed
- The `.deb` install printed alarming (but harmless) pip dependency
  errors about unrelated system packages: with system-site-packages,
  pip cross-checks apps that never see AgentWhisper's private
  virtualenv. Suppressed with `--no-warn-conflicts` — our own
  dependency set is resolved consistently from the lockfile.

## 0.3.0 — 2026-07-04

### Added
- **Start at login**: new tray checkbox and `agentwhisper autostart on|off`
  (XDG autostart entry, works on any desktop).
- **Friendly first-run experience**: the app now tells you when the
  speech model is downloading (one-time), when it's ready, and — if you
  dictate too early — that your dictation is queued. The tray status
  line shows the model state; a cached model is detected and loads
  without any download notice.
- **`.deb` package**: `./build-deb.sh` produces
  `dist/agentwhisper_<version>_all.deb` as an alternative, system-wide
  install method (dependencies installed into a private virtualenv at
  package configure time).

### Known limitations
- English only, X11 only (both designed-for future steps)

## 0.2.0 — 2026-07-04

First deployable release. Complete push-to-talk dictation on X11/XFCE,
verified in daily use on Debian/Ubuntu.

### Added
- **Daemon + clients architecture**: `agentwhisperd` owns all state; the
  Unix socket doubles as the single-instance lock. CLI client
  (`agentwhisper status|toggle|mode|quit`) for everything the tray does.
- **Exclusive system-wide hotkey** (X11 XGrabKey, F12 default): other
  apps never see the key while the daemon runs; Ctrl/Alt+F12 bindings
  elsewhere keep working. Grab conflicts are clear, actionable errors.
- **Two recording modes**, switchable live from the tray or CLI:
  hold-to-talk and press-to-toggle. Debounced against X11 auto-repeat.
- **Recording OSD**: semi-transparent popup near the bottom of the
  screen with green equalizer bars following the live microphone level.
- **Local transcription** (faster-whisper, English): model loads in the
  background at startup; first run downloads it to the shared
  Hugging Face cache.
- **Delivery**: clipboard always, auto-typing into the focused window
  (toggleable); a typing failure never loses the text.
- **Notifications** with transcript preview; replace instead of stack.
- **Tray icon** via direct GTK/AyatanaAppIndicator bindings; red icon
  while recording, live status line in the menu.
- **Self-checking startup**: config validation, desktop-tool checks,
  engine status — every failure names its fix. Logs at
  `~/.local/state/agentwhisper/daemon.log`.
- User-level `install.sh` / `uninstall.sh` (no sudo), XFCE menu entry.
- 53 automated tests (state machine, config, IPC, full pipeline).

### Known limitations
- English only (multilingual is a designed-for future step)
- X11 only (Wayland is a designed-for future step)
- No autostart on login yet (milestone 5)
