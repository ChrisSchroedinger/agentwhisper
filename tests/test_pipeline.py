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
    def __init__(self):
        self.copied: list[str] = []

    def check(self):
        return []

    def copy(self, text):
        self.copied.append(text)


def make_daemon(mode="hold", duration=1.0, text="hello world", error=None):
    daemon = Daemon(
        Config(mode=mode),
        recorder=FakeRecorder(duration),
        engine=FakeEngine(text, error),
        desktop=FakeDesktop(),
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
