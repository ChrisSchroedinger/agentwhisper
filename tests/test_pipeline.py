"""End-to-end pipeline: hotkey events → state machine → recorder →
engine → clipboard, with fake hardware and a fake model. Everything
else (state machine, dispatch, threading, timers) is the real code.
"""

import time

import numpy as np
import pytest

from agentwhisper.config import Config
from agentwhisper.daemon import Daemon
from agentwhisper.engines.base import EngineError
from agentwhisper.state import Phase


class FakeRecorder:
    def __init__(self, duration=1.0):
        self.duration = duration
        self.active = False
        self.level = 0.0

    def start(self):
        self.active = True

    def stop(self):
        self.active = False
        n = int(16_000 * self.duration)
        return np.zeros(n, dtype=np.int16), self.duration


class FakeEngine:
    def __init__(self, text="hello world", error=None):
        self.text = text
        self.error = error
        self.status = "ready"
        self.calls = 0

    def load(self):
        pass

    def transcribe(self, samples, sample_rate):
        self.calls += 1
        if self.error:
            raise self.error
        return self.text


class FakeDesktop:
    def __init__(self, type_error=None):
        self.copied: list[str] = []
        self.typed: list[str] = []
        self.sent: list[tuple[str, str]] = []  # (window_id, text) + Enter
        self.notifications: list[tuple[str, str]] = []
        self.type_error = type_error
        self.windows: dict[str, str] = {}  # id -> title of live windows
        self.select_result = ("0x123", "Agent Terminal")

    def check(self):
        return []

    def copy(self, text):
        self.copied.append(text)

    def type_text(self, text):
        if self.type_error:
            raise self.type_error
        self.typed.append(text)

    def select_window(self):
        window_id, title = self.select_result
        self.windows[window_id] = title
        return window_id, title

    def window_title(self, window_id):
        return self.windows.get(window_id)

    def type_into_window(self, window_id, text):
        self.sent.append((window_id, text))

    def notify(self, summary, body=""):
        self.notifications.append((summary, body))


def make_daemon(mode="hold", duration=1.0, text="hello world", error=None,
                type_error=None, **config_kwargs):
    daemon = Daemon(
        Config(mode=mode, **config_kwargs),
        recorder=FakeRecorder(duration),
        engine=FakeEngine(text, error),
        desktop=FakeDesktop(type_error),
    )
    return daemon


def wait_idle(daemon, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if daemon.sm.phase is Phase.IDLE:
            return
        time.sleep(0.01)
    pytest.fail(f"daemon did not return to idle (phase={daemon.sm.phase})")


def press_and_release(daemon):
    daemon.on_hotkey_press()
    daemon.on_hotkey_release()
    daemon._on_settle_timer()  # the debounce timer firing


class TestPipeline:
    def test_speech_lands_on_clipboard(self):
        daemon = make_daemon()
        press_and_release(daemon)
        wait_idle(daemon)
        assert daemon.desktop.copied == ["hello world"]
        assert daemon.engine.calls == 1

    def test_toggle_mode_full_cycle(self):
        daemon = make_daemon(mode="toggle")
        daemon.on_hotkey_press()   # start
        daemon.on_hotkey_release()
        daemon._on_settle_timer()
        assert daemon.sm.phase is Phase.RECORDING
        daemon.on_hotkey_press()   # stop
        wait_idle(daemon)
        assert daemon.desktop.copied == ["hello world"]

    def test_empty_transcript_copies_nothing(self):
        daemon = make_daemon(text="")
        press_and_release(daemon)
        wait_idle(daemon)
        assert daemon.desktop.copied == []

    def test_accidental_tap_is_ignored(self):
        daemon = make_daemon(duration=0.1)  # below MIN_RECORDING_SECONDS
        press_and_release(daemon)
        wait_idle(daemon)
        assert daemon.engine.calls == 0
        assert daemon.desktop.copied == []

    def test_engine_error_recovers_to_idle(self):
        daemon = make_daemon(error=EngineError("model exploded"))
        press_and_release(daemon)
        wait_idle(daemon)
        assert daemon.desktop.copied == []
        # And the next recording still works after the failure.
        daemon.engine.error = None
        press_and_release(daemon)
        wait_idle(daemon)
        assert daemon.desktop.copied == ["hello world"]

    def test_ready_for_next_dictation_immediately(self):
        daemon = make_daemon()
        for _ in range(3):
            press_and_release(daemon)
            wait_idle(daemon)
        assert daemon.desktop.copied == ["hello world"] * 3


class TestDelivery:
    def test_auto_type_types_and_copies(self):
        daemon = make_daemon(auto_type=True)
        press_and_release(daemon)
        wait_idle(daemon)
        assert daemon.desktop.copied == ["hello world"]
        assert daemon.desktop.typed == ["hello world"]
        assert daemon.desktop.notifications[-1][0] == "Typed & copied"

    def test_auto_type_off_only_copies(self):
        daemon = make_daemon(auto_type=False)
        press_and_release(daemon)
        wait_idle(daemon)
        assert daemon.desktop.copied == ["hello world"]
        assert daemon.desktop.typed == []
        assert daemon.desktop.notifications[-1][0] == "Copied to clipboard"

    def test_type_failure_keeps_clipboard_and_reports(self):
        from agentwhisper.desktop.base import DesktopError

        daemon = make_daemon(auto_type=True, type_error=DesktopError("no xdotool"))
        press_and_release(daemon)
        wait_idle(daemon)
        assert daemon.desktop.copied == ["hello world"]  # text not lost
        assert daemon.desktop.notifications[-1][0] == "Auto-type failed"

    def test_no_speech_notifies(self):
        daemon = make_daemon(text="")
        press_and_release(daemon)
        wait_idle(daemon)
        assert daemon.desktop.notifications[-1][0] == "No speech detected"

    def test_notifications_off_is_silent(self):
        daemon = make_daemon(notifications=False)
        press_and_release(daemon)
        wait_idle(daemon)
        assert daemon.desktop.copied == ["hello world"]
        assert daemon.desktop.notifications == []

    def test_long_text_preview_is_truncated(self):
        daemon = make_daemon(text="word " * 40)
        press_and_release(daemon)
        wait_idle(daemon)
        _summary, body = daemon.desktop.notifications[-1]
        assert len(body) <= 80
        assert body.endswith("…")


class TestTargetWindow:
    def test_target_gets_text_normal_typing_skipped(self):
        daemon = make_daemon(auto_type=True)
        assert daemon.choose_target_window() == "Agent Terminal"
        press_and_release(daemon)
        wait_idle(daemon)
        assert daemon.desktop.sent == [("0x123", "hello world")]
        assert daemon.desktop.typed == []                  # target replaces auto-type
        assert daemon.desktop.copied == ["hello world"]    # clipboard backup stays
        assert daemon.desktop.notifications[-1][0] == "Sent to Agent Terminal"

    def test_target_overrides_auto_type_off(self):
        daemon = make_daemon(auto_type=False)
        daemon.choose_target_window()
        press_and_release(daemon)
        wait_idle(daemon)
        assert daemon.desktop.sent == [("0x123", "hello world")]

    def test_closed_target_falls_back_and_clears(self):
        daemon = make_daemon(auto_type=True)
        daemon.choose_target_window()
        del daemon.desktop.windows["0x123"]  # the window went away
        press_and_release(daemon)
        wait_idle(daemon)
        assert daemon.desktop.sent == []
        assert daemon.desktop.typed == ["hello world"]  # delivered normally
        assert daemon.get_target_title() is None        # and the target is gone
        assert any(s == "Target window closed"
                   for s, _ in daemon.desktop.notifications)

    def test_clear_target_restores_normal_delivery(self):
        daemon = make_daemon(auto_type=True)
        daemon.choose_target_window()
        daemon.clear_target_window()
        press_and_release(daemon)
        wait_idle(daemon)
        assert daemon.desktop.sent == []
        assert daemon.desktop.typed == ["hello world"]
