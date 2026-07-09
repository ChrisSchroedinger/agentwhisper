"""agentwhisperd — the daemon.

Milestone 3 scope: the daemon TRANSCRIBES.
- the hotkey is reserved system-wide via XGrabKey; press/release drive
  the debounced state machine; recording is real microphone capture
- the whisper model loads in a background thread at startup (the app
  stays instantly responsive; the first-ever run downloads the model)
- on stop, audio goes through the Engine and the text lands on the
  clipboard (xclip); every stage is visible in tray + `status` + log

Auto-typing into the active window and desktop notifications arrive in
milestone 4.
"""

from __future__ import annotations

import logging
import os
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path

from agentwhisper import __version__, autostart, ipc
from agentwhisper import config as config_mod
from agentwhisper.audio import AudioError, Recorder
from agentwhisper.desktop.base import DesktopError
from agentwhisper.desktop.x11 import X11Desktop
from agentwhisper.engines.base import EngineError
from agentwhisper.engines.whisper_local import WhisperLocalEngine
from agentwhisper.state import RELEASE_DEBOUNCE_SECONDS, Action, DictationStateMachine

log = logging.getLogger("agentwhisper")

LOG_DIR = Path.home() / ".local" / "state" / "agentwhisper"
LOG_PATH = LOG_DIR / "daemon.log"

# Recordings shorter than this are accidental taps, not speech.
MIN_RECORDING_SECONDS = 0.3


def _shorten(title: str, limit: int = 40) -> str:
    return title if len(title) <= limit else title[: limit - 1] + "…"


class Daemon:
    """Wires hotkey events through the state machine to real effects."""

    def __init__(self, cfg: config_mod.Config, *, recorder=None, engine=None,
                 desktop=None):
        self.config = cfg
        self.sm = DictationStateMachine(mode=cfg.mode)
        self.recorder = recorder if recorder is not None else Recorder()
        self.engine = engine if engine is not None else WhisperLocalEngine(
            cfg.model, cfg.device, cfg.compute_type)
        self.desktop = desktop if desktop is not None else X11Desktop()
        self.desktop_problems = self.desktop.check()
        self.started_at = time.time()
        self.hotkey_status = "inactive"
        self._lock = threading.RLock()
        self._shutdown = threading.Event()
        self._tray = None
        self._visualizer = None
        # Session-only (window ids do not survive restarts): when set,
        # every dictation is typed into this window and submitted.
        self._target_window: tuple[str, str] | None = None  # (id, title)
        self._settle_timer: threading.Timer | None = None
        self._max_timer: threading.Timer | None = None

    def start_engine(self) -> None:
        """Load the model in the background; the daemon stays responsive."""
        threading.Thread(target=self._load_engine, name="engine-load",
                         daemon=True).start()

    def _load_engine(self) -> None:
        threading.Thread(target=self._loading_ticker, name="load-ticker",
                         daemon=True).start()
        if not self.engine.is_cached():
            self._notify("Downloading the speech model",
                         f"One-time download of '{self.config.model}' — the tray "
                         f"menu shows the progress.")
        self.engine.load()
        if self._tray is not None:
            self._tray.set_state("idle")  # refresh the status line
        if self.engine.status == "ready":
            if self.engine.downloaded:
                self._notify("AgentWhisper is ready",
                             "The speech model is installed — you can dictate now.")
        else:
            self._notify("Speech model failed to load", self.engine.status)

    # -- hotkey events (called from the listener thread) -----------------

    def on_hotkey_press(self) -> None:
        with self._lock:
            self._dispatch(self.sm.key_pressed())

    def on_hotkey_release(self) -> None:
        with self._lock:
            self._dispatch(self.sm.key_released())

    def _on_settle_timer(self) -> None:
        with self._lock:
            self._dispatch(self.sm.release_settled())

    def _loading_ticker(self) -> None:
        """Refresh the tray status line until the model is loaded.

        Keyed on load_finished, NOT on the status string: the status is
        'not loaded' for a moment before load() flips it, and a string
        check would make this loop exit before it ever ticked.
        """
        while not self.engine.load_finished:
            if self._tray is not None and self.sm.phase.name == "IDLE":
                self._tray.set_state("idle")  # re-renders the status label
            time.sleep(2)

    def _on_max_duration(self) -> None:
        log.warning("recording hit the %ds cap; stopping",
                    self.config.max_record_seconds)
        with self._lock:
            self._dispatch(self.sm.max_duration_reached())

    # -- state machine actions → real effects ----------------------------

    def _dispatch(self, actions: list[Action]) -> None:
        for action in actions:
            if action is Action.START_RECORDING:
                self._start_recording()
            elif action is Action.STOP_RECORDING:
                self._stop_recording(discard=False)
            elif action is Action.ABORT_RECORDING:
                self._stop_recording(discard=True)
            elif action is Action.SCHEDULE_SETTLE:
                self._cancel_timer("_settle_timer")
                self._settle_timer = threading.Timer(
                    RELEASE_DEBOUNCE_SECONDS, self._on_settle_timer)
                self._settle_timer.daemon = True
                self._settle_timer.start()
            elif action is Action.CANCEL_SETTLE:
                self._cancel_timer("_settle_timer")

    def _start_recording(self) -> None:
        try:
            self.recorder.start()
        except AudioError as e:
            log.error("%s", e)
            self._dispatch(self.sm.max_duration_reached())  # back to idle
            return
        log.info("recording started")
        self._max_timer = threading.Timer(
            self.config.max_record_seconds, self._on_max_duration)
        self._max_timer.daemon = True
        self._max_timer.start()
        if self._tray is not None:
            self._tray.set_state("recording")
        if self._visualizer is not None:
            self._visualizer.show()

    def _stop_recording(self, discard: bool) -> None:
        self._cancel_timer("_max_timer")
        samples, duration = self.recorder.stop()
        if self._visualizer is not None:
            self._visualizer.hide()

        if discard:
            log.info("recording aborted (%.1fs discarded)", duration)
        elif duration < MIN_RECORDING_SECONDS:
            log.info("recording too short (%.2fs) — ignoring accidental tap", duration)
            discard = True

        if discard:
            if self._tray is not None:
                self._tray.set_state("idle")
            self._dispatch(self.sm.transcription_finished())
            return

        log.info("recording stopped: %.1fs captured — transcribing", duration)
        if self.engine.status.startswith(("downloading", "loading")):
            self._notify("Preparing the speech model",
                         "Your dictation is queued and will be transcribed "
                         "as soon as the model is ready.")
        if self._tray is not None:
            self._tray.set_state("transcribing")
        threading.Thread(target=self._transcribe, args=(samples,),
                         name="transcribe", daemon=True).start()

    def _transcribe(self, samples) -> None:
        try:
            text = self.engine.transcribe(samples, 16_000)
            if text:
                self._deliver(text)
            else:
                log.info("no speech detected")
                self._notify("No speech detected", "")
        except (EngineError, DesktopError) as e:
            log.error("transcription failed: %s", e)
            self._notify("Transcription failed", str(e))
        except Exception:
            log.exception("unexpected transcription error")
            self._notify("Transcription failed", "unexpected error — see daemon log")
        finally:
            if self._tray is not None:
                self._tray.set_state("idle")
            with self._lock:
                self._dispatch(self.sm.transcription_finished())

    def _deliver(self, text: str) -> None:
        """Clipboard always; typing on top when enabled. Clipboard goes
        first so the text is safe even if typing fails. A chosen target
        window takes precedence over normal typing (and ignores the
        auto-type switch — the user explicitly picked a destination)."""
        self.desktop.copy(text)
        preview = text if len(text) <= 80 else text[:77] + "…"
        if self._target_window is not None and self._deliver_to_target(text, preview):
            return
        typed = False
        if self.config.auto_type:
            try:
                self.desktop.type_text(text)
                typed = True
            except DesktopError as e:
                log.error("auto-type failed (text is still in the clipboard): %s", e)
                self._notify("Auto-type failed", f"{e} — the text is in your clipboard")
                return
        log.info("transcribed %d characters → %s", len(text),
                 "typed + clipboard" if typed else "clipboard")
        self._notify("Typed & copied" if typed else "Copied to clipboard", preview)

    def _deliver_to_target(self, text: str, preview: str) -> bool:
        """Type into the chosen window and press Enter. False means the
        window is gone and the text should be delivered normally."""
        window_id, title = self._target_window
        if self.desktop.window_title(window_id) is None:
            log.warning("target window %s (%r) is gone — typing normally again",
                        window_id, title)
            self.clear_target_window()
            self._notify("Target window closed",
                         "Typing into the active window again.")
            return False
        try:
            self.desktop.type_into_window(window_id, text)
        except DesktopError as e:
            log.error("sending to %r failed (text is in the clipboard): %s", title, e)
            self._notify("Sending failed", f"{e} — the text is in your clipboard")
            return True  # handled; don't type it a second time
        log.info("transcribed %d characters → sent to %r + Enter", len(text), title)
        self._notify(f"Sent to {_shorten(title)}", preview)
        return True

    def _notify(self, summary: str, body: str) -> None:
        if not self.config.notifications:
            return
        try:
            self.desktop.notify(summary, body)
        except DesktopError as e:
            log.warning("notification failed: %s", e)

    def _cancel_timer(self, name: str) -> None:
        timer = getattr(self, name)
        if timer is not None:
            timer.cancel()
            setattr(self, name, None)

    # -- interface used by the tray ---------------------------------------

    def is_enabled(self) -> bool:
        return self.sm.enabled

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._dispatch(self.sm.set_enabled(enabled))
        log.info("dictation %s", "enabled" if enabled else "disabled")

    def get_mode(self) -> str:
        return self.sm.mode

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self._dispatch(self.sm.set_mode(mode))
            self.config.mode = mode
        config_mod.save(self.config)
        log.info("mode set to %s", mode)

    def hotkey_name(self) -> str:
        return self.config.hotkey

    def get_max_record_seconds(self) -> int:
        return self.config.max_record_seconds

    def get_target_title(self) -> str | None:
        target = self._target_window
        return target[1] if target else None

    def choose_target_window(self) -> str | None:
        """Let the user pick a window by clicking it; every dictation is
        then typed into that window and submitted with Enter, until the
        target is cleared. Blocks until the click (~30 s timeout).
        Returns the window title, or None if nothing was selected."""
        self._notify("Choose a window",
                     "Click the window that should receive your dictations.")
        try:
            window_id, title = self.desktop.select_window()
        except DesktopError as e:
            log.error("window selection failed: %s", e)
            self._notify("Window selection failed", str(e))
            return None
        with self._lock:
            self._target_window = (window_id, title)
        log.info("target window set: %s (%r)", window_id, title)
        if self._tray is not None:
            self._tray.refresh_target()
        self._notify(f"Dictating into: {_shorten(title)}",
                     "Each dictation is typed there and submitted with "
                     "Enter. Use the tray item again to stop.")
        return title

    def clear_target_window(self) -> None:
        with self._lock:
            self._target_window = None
        log.info("target window cleared")
        if self._tray is not None:
            self._tray.refresh_target()

    def set_max_record_seconds(self, seconds: int) -> None:
        self.config.max_record_seconds = seconds
        config_mod.save(self.config)
        log.info("recording limit set to %ds", seconds)

    def engine_status(self) -> str:
        return self.engine.status

    def is_autostart(self) -> bool:
        return autostart.is_enabled()

    def set_autostart(self, enabled: bool) -> None:
        if enabled:
            autostart.enable()
        else:
            autostart.disable()
        log.info("start at login %s", "on" if enabled else "off")

    def is_auto_type(self) -> bool:
        return self.config.auto_type

    def set_auto_type(self, enabled: bool) -> None:
        self.config.auto_type = enabled
        config_mod.save(self.config)
        log.info("auto-type %s", "on" if enabled else "off")

    def is_notifications(self) -> bool:
        return self.config.notifications

    def set_notifications(self, enabled: bool) -> None:
        self.config.notifications = enabled
        config_mod.save(self.config)
        log.info("notifications %s", "on" if enabled else "off")

    def quit(self) -> None:
        log.info("shutdown requested")
        with self._lock:
            self._dispatch(self.sm.shutdown())
        self._shutdown.set()
        if self._tray is not None:
            self._tray.stop()

    # -- IPC ----------------------------------------------------------------

    def handle_request(self, message: dict) -> dict:
        cmd = message.get("cmd")
        if cmd == "ping":
            return ipc.ok()
        if cmd == "status":
            return ipc.ok(
                version=__version__,
                phase=self.sm.phase.name.lower(),
                enabled=self.sm.enabled,
                model=self.config.model,
                engine=self.engine.status,
                desktop="; ".join(self.desktop_problems) or "ok",
                auto_type=self.config.auto_type,
                notifications=self.config.notifications,
                mode=self.sm.mode,
                max_record_seconds=self.config.max_record_seconds,
                target_window=self.get_target_title(),
                autostart=autostart.is_enabled(),
                hotkey=self.config.hotkey,
                hotkey_status=self.hotkey_status,
                tray="active" if self._tray is not None else "unavailable",
                visualizer="active" if self._visualizer is not None else "unavailable",
                uptime_seconds=round(time.time() - self.started_at),
                pid=os.getpid(),
            )
        if cmd == "toggle-enabled":
            self.set_enabled(not self.sm.enabled)
            return ipc.ok(enabled=self.sm.enabled)
        if cmd == "set-autostart":
            enabled = message.get("enabled")
            if not isinstance(enabled, bool):
                return ipc.error("set-autostart needs enabled: true/false")
            self.set_autostart(enabled)
            return ipc.ok(autostart=enabled)
        if cmd == "set-mode":
            mode = message.get("mode")
            if mode not in ("hold", "toggle"):
                return ipc.error(f"mode must be 'hold' or 'toggle', not {mode!r}")
            self.set_mode(mode)
            return ipc.ok(mode=mode)
        if cmd == "set-limit":
            seconds = message.get("seconds")
            if (isinstance(seconds, bool) or not isinstance(seconds, int)
                    or not config_mod.LIMIT_MIN <= seconds <= config_mod.LIMIT_MAX):
                return ipc.error(
                    f"set-limit needs seconds: an integer between "
                    f"{config_mod.LIMIT_MIN} and {config_mod.LIMIT_MAX}")
            self.set_max_record_seconds(seconds)
            return ipc.ok(max_record_seconds=seconds)
        if cmd == "set-target":
            title = self.choose_target_window()
            if title is None:
                return ipc.error("no window was selected")
            return ipc.ok(target_window=title)
        if cmd == "clear-target":
            self.clear_target_window()
            return ipc.ok(target_window=None)
        if cmd == "quit":
            # Reply first, then shut down, so the client gets its answer.
            timer = threading.Timer(0.1, self.quit)
            timer.daemon = True
            timer.start()
            return ipc.ok(quitting=True)
        return ipc.error(f"unknown command {cmd!r}")


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline(ipc.MAX_LINE_BYTES + 1)
        if not line:
            return
        try:
            request = ipc.decode(line.rstrip(b"\n"))
            response = self.server.daemon.handle_request(request)  # type: ignore[attr-defined]
        except ipc.ProtocolError as e:
            response = ipc.error(str(e))
        except Exception:
            log.exception("error handling request")
            response = ipc.error("internal error (see daemon log)")
        self.wfile.write(ipc.encode(response))


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path: str, daemon: Daemon):
        self.daemon = daemon
        super().__init__(path, _Handler)


def _claim_socket(path: Path) -> None:
    """Ensure we can bind: remove a stale socket, or exit if one is live."""
    if not path.exists():
        return
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(1.0)
        probe.connect(str(path))
    except OSError:
        log.info("removing stale socket %s", path)
        path.unlink()
        return
    finally:
        probe.close()
    print(
        "agentwhisperd is already running (socket in use).\n"
        "Check it with: agentwhisper status",
        file=sys.stderr,
    )
    sys.exit(1)


def _setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler(sys.stderr)],
    )


def main() -> int:
    if "--version" in sys.argv[1:]:
        print(f"agentwhisperd {__version__}")
        return 0

    _setup_logging()
    log.info("agentwhisperd %s starting", __version__)

    config_mod.write_default()
    try:
        cfg = config_mod.load()
    except config_mod.ConfigError as e:
        log.error("configuration invalid:\n%s", e)
        return 2
    log.info("config OK: model=%s mode=%s hotkey=%s", cfg.model, cfg.mode, cfg.hotkey)

    daemon = Daemon(cfg)
    for problem in daemon.desktop_problems:
        log.warning("desktop check: %s", problem)
    daemon.start_engine()

    sock_path = ipc.socket_path()
    _claim_socket(sock_path)
    server = _Server(str(sock_path), daemon)
    server_thread = threading.Thread(target=server.serve_forever, name="ipc", daemon=True)
    server_thread.start()
    log.info("IPC socket listening at %s", sock_path)

    # Reserve the hotkey system-wide. A grab failure is fatal only if it
    # is a conflict the user must resolve; a missing DISPLAY just means
    # a headless session (still controllable via the CLI).
    from agentwhisper.hotkey import HotkeyError, X11HotkeyListener

    listener = X11HotkeyListener(cfg.hotkey, daemon.on_hotkey_press,
                                 daemon.on_hotkey_release)
    try:
        listener.start()
        daemon.hotkey_status = "grabbed (exclusive)"
        log.info("hotkey %s reserved system-wide (XGrabKey)", cfg.hotkey.upper())
    except HotkeyError as e:
        daemon.hotkey_status = f"unavailable: {e}"
        log.error("hotkey unavailable: %s", e)

    exit_code = 0
    try:
        from agentwhisper.tray import TrayUnavailable, create_tray

        try:
            daemon._tray = create_tray(daemon)
            log.info("tray icon active (AyatanaAppIndicator)")
        except TrayUnavailable as e:
            log.warning("tray unavailable: %s", e)
            log.warning("running headless; control with: agentwhisper status|toggle|quit")

        if daemon._tray is not None:
            from agentwhisper.visualizer import Visualizer, VisualizerUnavailable

            try:
                daemon._visualizer = Visualizer(lambda: daemon.recorder.level)
                log.info("recording visualizer ready")
            except VisualizerUnavailable as e:
                log.warning("visualizer unavailable: %s", e)
            daemon._tray.run()  # blocks until quit
        else:
            _wait_headless(daemon)
    finally:
        listener.stop()
        server.shutdown()
        server.server_close()
        sock_path.unlink(missing_ok=True)
        log.info("agentwhisperd stopped")
        # Library worker threads (e.g. Hugging Face's model-download
        # pool) are non-daemon: a normal exit would wait minutes for
        # them, leaving a zombie process with a frozen tray icon while
        # the socket is already free — a restart then shows two icons.
        # Cleanup is done and the download resumes on next start, so
        # end the process for real.
        logging.shutdown()
        os._exit(exit_code)


def _wait_headless(daemon: Daemon) -> None:
    import signal

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: daemon.quit())
    daemon._shutdown.wait()


if __name__ == "__main__":
    sys.exit(main())
