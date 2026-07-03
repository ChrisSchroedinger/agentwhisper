# AgentWhisper — Design Document

> Status: **draft for discussion** — v0.1, 2026-07-04
> Successor to soupawhisper, built from scratch around its lessons.

## Vision

**v1: rock-solid push-to-talk dictation for Linux.** Speak, release, text
appears — every time, with no mystery failures. The architecture leaves
a clean seam for a future "agent mode" (speech → LLM → action), which is
where the name points, but v1 ships dictation only.

## Decisions (settled)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Scope v1 | Dictation only | Do one thing perfectly; agent mode is a future client, not a v1 feature |
| Platform | X11 now, Wayland-ready | MX Linux + XFCE = X11 for years; all display code behind one interface |
| Stack | Python 3.11+, uv, src/ layout | Fastest iteration for a solo project; uv kills the venv/packaging pain |
| STT | Pluggable engine, local faster-whisper first | Private/offline v1; cloud or agent engines drop in later |

## Lessons from soupawhisper (the "never again" list)

1. **No monolith.** 700 lines in one file made every fix risky. →
   Small modules, single responsibilities, unit tests.
2. **No invisible runtime failures.** pystray silently picked a dead
   backend; the venv silently hid GTK bindings. → Verify every
   integration at startup and **fail loudly** with an actionable message.
3. **No accidental multi-instance.** → The daemon's socket *is* the
   single-instance lock, by construction.
4. **No scattered desktop glue.** → One `DesktopBackend` interface owns
   typing, clipboard, and notifications. X11 implementation first;
   a Wayland one later is a new module, not a rewrite.

## Architecture: daemon + thin clients

```
┌─────────────────────────────────────────────────┐
│ agentwhisperd (systemd user service)            │
│                                                 │
│  hotkey listener ─▶ state machine ─▶ engine     │
│  (pynput/X11)       (record/idle)    (whisper)  │
│         │                 │             │       │
│         ▼                 ▼             ▼       │
│  audio capture      DesktopBackend (X11):      │
│  (sounddevice)      type / clipboard / notify   │
│                                                 │
│  IPC server: unix socket, JSON-lines protocol   │
└───────▲──────────────▲──────────────▲───────────┘
        │              │              │
   agentwhisper    tray client    (future: agent
   CLI (status,    (StatusNotifier) client, GUI)
   toggle, logs)
```

- **Daemon** owns all state: audio, model, recording lifecycle. It runs
  headless; a machine with no panel still dictates perfectly.
- **IPC**: Unix socket at `$XDG_RUNTIME_DIR/agentwhisper.sock`,
  newline-delimited JSON. Simple to test with `nc`, no D-Bus library
  dependency. Binding the socket doubles as the single-instance lock.
- **CLI client** (`agentwhisper status|toggle|start|stop|set|logs`) is
  the first client and the debugging story.
- **Tray** is a *client*, not a core feature. If it can't get an
  AppIndicator backend it says so on stderr and exits nonzero — the
  daemon keeps working either way.

## v1 feature list

- **English-only** (decided 2026-07-04): only the `*.en` models are
  offered; multilingual support is a designed-for later step. Removes
  the whole model/language-mismatch class of bugs from v1.
- Hold-to-record and tap-to-toggle modes (configurable hotkey, F12
  default), switchable live from the tray menu and `agentwhisper mode`
- The hotkey is reserved **exclusively** (XGrabKey): no collisions with
  other applications' F12 bindings while the daemon runs
- Debounced against X11 auto-repeat (carry over the 180 ms fix)
- Recording OSD: semi-transparent popup bottom-center (~15% above the
  edge) with green equalizer bars following the live mic level
- Local faster-whisper engine; model configurable
- Output: clipboard always; auto-type into the focused window (toggleable)
- Desktop notifications for state changes (toggleable)
- Tray icon with menu (toggle, model, quit)
- `agentwhisper` CLI for everything the tray does, plus `status` and `logs`
- Startup self-check: audio device, X11 tools, model availability —
  every failure explains its fix
- Hard cap on recording length; stale temp cleanup

## Technical choices

| Concern | Choice | Notes |
|---------|--------|-------|
| Audio capture | `sounddevice` (PortAudio) | Native, in-process; device selection + level metering become possible. No more arecord shell-out. |
| Hotkey | `python-xlib` XGrabKey | Exclusive system-wide grab: the key never reaches other apps while the daemon runs. BadAccess (someone else grabbed it) is a clear error. evdev is the future Wayland path |
| Typing/clipboard | xdotool/xclip subprocess **inside** the X11 backend | Proven; verified at startup; isolated so it's swappable |
| Config | TOML at `~/.config/agentwhisper/config.toml`, stdlib `tomllib`, dataclass-validated | No pydantic dependency for v1 |
| Logging | `logging` → file + stderr (journald picks it up) | `agentwhisper logs` tails it |
| Tests | pytest; unit tests for state machine, debounce, config, protocol; integration test with a fake engine + fake backend | The state machine is pure logic — fully testable without audio or X11 |
| Lint/format | ruff (lint + format) | One tool |
| Packaging | uv project; `install.sh` that installs uv if needed, creates the env, installs the systemd user unit + .desktop | .deb comes later, once v1 is stable — packaging a moving target is how soupawhisper got hurt |

## Repository layout

```
agentwhisper/
├── pyproject.toml            # uv-managed; deps, ruff, pytest config
├── DESIGN.md                 # this file
├── README.md
├── CHANGELOG.md
├── install.sh
├── src/agentwhisper/
│   ├── __init__.py           # version
│   ├── config.py             # load/validate/save TOML
│   ├── state.py              # recording state machine (pure logic)
│   ├── audio.py              # sounddevice capture → wav buffer
│   ├── hotkey.py             # key listener → events (debounce lives here)
│   ├── engines/
│   │   ├── base.py           # Engine protocol: transcribe(audio) -> text
│   │   └── whisper_local.py  # faster-whisper implementation
│   ├── desktop/
│   │   ├── base.py           # DesktopBackend protocol: type/copy/notify
│   │   └── x11.py            # xdotool/xclip/notify-send implementation
│   ├── ipc.py                # socket protocol (shared by daemon & clients)
│   ├── daemon.py             # wires everything; the service entry point
│   ├── cli.py                # client commands
│   └── tray.py               # tray client
├── packaging/                # systemd unit, .desktop, icons
└── tests/
```

## Milestones (step by step, each one usable and tested)

1. **Starts and shows up** ✅: daemon skeleton (config, logging,
   socket = single-instance lock, CLI `status/toggle/quit`), tray icon
   in the XFCE panel via direct GTK/AyatanaAppIndicator bindings (no
   pystray backend guessing), XFCE menu entry, user-level `install.sh`.
   For this milestone the tray runs inside the daemon process; the
   split into a separate tray client happens once the IPC surface has
   settled.
2. **Hears** ✅: audio capture (sounddevice), exclusive XGrabKey hotkey
   wired to the state machine, recording visible in tray + `status` +
   the OSD level visualizer, mode switching in the tray menu.
3. **Transcribes** ✅: Engine interface + faster-whisper implementation
   (background load at startup), clipboard via the X11 DesktopBackend.
4. **Types** ← current: auto-type via the X11 DesktopBackend;
   notifications.
5. **Hardens**: systemd unit, autostart option, model download UX,
   `.deb` packaging.

## Future seams (explicitly designed for, not built)

- **Languages beyond English**: re-add a `language` option plus the
  multilingual models, with validation that rejects impossible
  model/language combinations loudly.
- **Agent mode**: a new Engine that sends transcripts to an LLM and a
  new client that renders/executes responses. The daemon doesn't change.
- **Wayland**: `desktop/wayland.py` + an evdev hotkey listener.
- **Cloud STT**: another Engine implementation behind a config flag.

## Resolved questions (2026-07-04)

1. **Default model: `base.en`** (small, fast). v1 is English-only, so
   the language/model mismatch trap does not exist by construction;
   the config layer rejects multilingual models until languages land.
2. **No autostart during development.** Manual start (menu /
   `systemctl --user start agentwhisper`) while we iterate; autostart
   ships when v1 is trusted.
3. **Fresh icon design** — mic + spark/agent motif, distinguishable
   from soupawhisper in the panel during the transition.
