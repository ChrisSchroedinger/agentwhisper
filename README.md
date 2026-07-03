# AgentWhisper

**Push-to-talk voice dictation for Linux.** Hold a key (F12 by default),
speak, release — your words are transcribed on your own computer and
land in your clipboard, optionally typed straight into whatever you were
writing. No cloud, no account, no internet needed after setup.

> ⚠️ **Project status: in active development — usable, with rough edges.**
> What works today: install, tray icon, exclusive hotkey, recording with
> a live voice visualizer, and **transcription — your speech becomes
> text in the clipboard** (paste it anywhere with Ctrl+V).
> Still missing: automatic typing into the active window and desktop
> notifications — that's the next milestone. See the [roadmap](#roadmap).

AgentWhisper is the from-scratch successor to
[soupawhisper](https://github.com/ChrisSchroedinger/soupawhisper) (now
archived), rebuilt around the lessons learned there — see
[DESIGN.md](DESIGN.md) if you care about the engineering.

## What it looks like

- A **microphone icon in your system tray**. Right-click it for the menu.
- While recording, the icon turns **red** and a small translucent panel
  appears near the bottom of your screen with **green bars dancing to
  your voice** — so you always know when the microphone is live.

## Requirements

- Linux with **X11** (not Wayland). Built and tested on
  **MX Linux with XFCE**; any Debian/Ubuntu-family desktop should work.
- **Python 3.11 or newer** (your distro's regular Python).
- A microphone.
- Two small system packages for the tray icon:

  ```bash
  sudo apt install python3-gi python3-gi-cairo gir1.2-ayatanaappindicator3-0.1
  ```

## Install

No root access needed except for the apt line above — everything else
goes into your home directory.

```bash
# 1. Get the code
git clone https://github.com/ChrisSchroedinger/agentwhisper.git
cd agentwhisper

# 2. Install uv (a fast Python package manager) — once, if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Install AgentWhisper
./install.sh
```

The installer creates a private Python environment, puts **AgentWhisper
in your applications menu** (Utility category), adds the `agentwhisper`
command to your terminal, and tells you clearly if anything is missing.

To remove everything again: `./uninstall.sh` (add `--purge` to also
delete your settings and logs).

## Using it

Start **AgentWhisper** from your applications menu. The mic icon appears
in the tray.

**Two ways to record** (switch anytime in the tray menu → *Recording Mode*):

| Mode | How it works |
|------|--------------|
| **Hold to talk** (default) | Hold F12, speak, release. |
| **Press to toggle** | Press F12 to start, press F12 again to stop. |

When you stop, the tray shows *Transcribing…* for a moment and then the
text is **in your clipboard** — paste it anywhere with Ctrl+V.

> **First run:** the speech model (~140MB for the default) downloads
> automatically in the background when AgentWhisper starts. Until it
> finishes, dictations wait for it. `agentwhisper status` shows the
> progress on the `engine:` line (`loading` → `ready`).

While AgentWhisper runs, **F12 belongs to it alone** — other programs
won't see the key, so it can't accidentally trigger something else.
(Combinations like Ctrl+F12 keep working normally.)

**The tray menu** (right-click the icon):

- a status line telling you what to do in the current mode
- **Enabled** — pause/resume dictation without quitting
- **Recording Mode** — hold-to-talk vs. press-to-toggle
- **Quit AgentWhisper**

**From the terminal** (optional, same controls):

```bash
agentwhisper status    # is it running? what's it doing?
agentwhisper toggle    # enable/disable dictation
agentwhisper mode toggle   # or: hold
agentwhisper quit
```

## Settings

Settings live in `~/.config/agentwhisper/config.toml` (created on first
run, with comments). The interesting ones:

| Setting | Default | Meaning |
|---------|---------|---------|
| `key` | `f12` | The push-to-talk key (`f1`…`f12`, `scroll_lock`, `pause`, …) |
| `mode` | `hold` | `hold` = push-to-talk, `toggle` = press to start/stop |
| `model` | `base.en` | Whisper model: `tiny.en` (fastest) … `medium.en` (most accurate) |
| `auto_type` | `true` | Type the text into the active window (besides copying it) |
| `max_record_seconds` | `60` | Safety cap on a single recording |

Restart AgentWhisper after editing the file. (Mode can also be changed
live from the tray.)

## Troubleshooting

**No tray icon?** Run `agentwhisper status` — the `tray:` line tells you
why, and the fix is always the apt command from
[Requirements](#requirements), followed by re-running `./install.sh`.

**"could not reserve 'f12'"?** Another program grabbed exactly that key.
Press F12 and see what reacts, then either unbind it there or pick a
different key in the config file.

**No green bars while recording?** Check `agentwhisper status` →
`visualizer:`. If unavailable, install `python3-gi-cairo` and restart.

**Dictated but nothing in the clipboard?** Check `agentwhisper status`:
`engine:` must say `ready` (`loading` means the model is still
downloading — first run only), and `clipboard:` must say `ok` (if not,
`sudo apt install xclip`). Very short taps (under ~0.3s) are ignored on
purpose, and silence transcribes to nothing.

**Where are the logs?** `~/.local/state/agentwhisper/daemon.log`.

## Roadmap

| Milestone | Status |
|-----------|:------:|
| 1. Installs, runs once, tray icon + menu | ✅ done |
| 2. Records: exclusive hotkey, mic capture, voice visualizer | ✅ done |
| 3. Transcribes: speech → text in your clipboard (English) | ✅ done |
| 4. Types the text into the active window + notifications | 🔜 next |
| 5. Polish: autostart, easy model download, .deb package | planned |
| Later: more languages, Wayland, agent mode | designed for |

## For developers

```bash
./install.sh       # sets up the venv (needs system Python + GTK bindings)
uv run pytest      # 47 tests
uv run ruff check .
```

Architecture, decisions, and rationale: [DESIGN.md](DESIGN.md).

## License

[MIT](LICENSE) — © 2026 Chris Schroedinger
