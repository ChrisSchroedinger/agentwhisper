"""Daemon request handling and end-to-end IPC over a real socket."""

import socket
import threading

import pytest

from agentwhisper import ipc
from agentwhisper.config import Config
from agentwhisper.daemon import Daemon, _Server


class _FakeEngine:
    status = "ready"

    def load(self):
        pass

    def transcribe(self, samples, sample_rate):
        return ""


class _FakeDesktop:
    def check(self):
        return []

    def copy(self, text):
        pass

    def type_text(self, text):
        pass

    def select_window(self):
        return ("0xabc", "Terminal")

    def window_title(self, window_id):
        return "Terminal"

    def type_into_window(self, window_id, text):
        pass

    def notify(self, summary, body=""):
        pass


@pytest.fixture
def daemon():
    return Daemon(Config(), engine=_FakeEngine(), desktop=_FakeDesktop())


class TestHandleRequest:
    def test_ping(self, daemon):
        assert daemon.handle_request({"cmd": "ping"}) == {"ok": True}

    def test_status_shape(self, daemon):
        s = daemon.handle_request({"cmd": "status"})
        assert s["ok"] is True
        assert s["phase"] == "idle"
        assert s["enabled"] is True
        assert s["model"] == "base.en"
        assert s["engine"] == "ready"
        assert s["desktop"] == "ok"
        assert s["auto_type"] is True
        assert s["notifications"] is True
        assert s["mode"] == "hold"
        assert s["max_record_seconds"] == 60
        assert s["target_window"] is None
        assert isinstance(s["autostart"], bool)
        assert s["hotkey"] == "f12"
        assert s["hotkey_status"] == "inactive"
        assert s["tray"] == "unavailable"
        assert s["visualizer"] == "unavailable"

    def test_toggle_enabled_flips(self, daemon):
        assert daemon.handle_request({"cmd": "toggle-enabled"})["enabled"] is False
        assert daemon.handle_request({"cmd": "toggle-enabled"})["enabled"] is True

    def test_set_mode(self, daemon, monkeypatch, tmp_path):
        from agentwhisper import config as config_mod

        monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.toml")
        monkeypatch.setattr(config_mod.save, "__defaults__",
                            (tmp_path / "config.toml",))
        response = daemon.handle_request({"cmd": "set-mode", "mode": "toggle"})
        assert response["ok"] is True
        assert daemon.sm.mode == "toggle"
        # And it persisted.
        assert config_mod.load(tmp_path / "config.toml").mode == "toggle"

    def test_set_mode_rejects_garbage(self, daemon):
        response = daemon.handle_request({"cmd": "set-mode", "mode": "press"})
        assert response["ok"] is False

    def test_set_limit(self, daemon, monkeypatch, tmp_path):
        from agentwhisper import config as config_mod

        monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.toml")
        monkeypatch.setattr(config_mod.save, "__defaults__",
                            (tmp_path / "config.toml",))
        response = daemon.handle_request({"cmd": "set-limit", "seconds": 120})
        assert response["ok"] is True
        assert daemon.config.max_record_seconds == 120
        # And it persisted.
        assert config_mod.load(tmp_path / "config.toml").max_record_seconds == 120

    @pytest.mark.parametrize("seconds", ["60", 0, -5, True, None, 2.5, 29, 601])
    def test_set_limit_rejects_garbage(self, daemon, seconds):
        response = daemon.handle_request({"cmd": "set-limit", "seconds": seconds})
        assert response["ok"] is False
        assert daemon.config.max_record_seconds == 60

    def test_set_and_clear_target(self, daemon):
        response = daemon.handle_request({"cmd": "set-target"})
        assert response["ok"] is True
        assert response["target_window"] == "Terminal"
        assert daemon.handle_request({"cmd": "status"})["target_window"] == "Terminal"
        response = daemon.handle_request({"cmd": "clear-target"})
        assert response["ok"] is True
        assert daemon.handle_request({"cmd": "status"})["target_window"] is None

    def test_set_autostart(self, daemon, monkeypatch, tmp_path):
        from agentwhisper import autostart

        monkeypatch.setattr(autostart, "autostart_path",
                            lambda: tmp_path / "agentwhisper.desktop")
        assert daemon.handle_request(
            {"cmd": "set-autostart", "enabled": True})["autostart"] is True
        assert autostart.is_enabled()
        assert daemon.handle_request(
            {"cmd": "set-autostart", "enabled": False})["autostart"] is False
        assert not autostart.is_enabled()

    def test_set_autostart_rejects_non_bool(self, daemon):
        response = daemon.handle_request({"cmd": "set-autostart", "enabled": "yes"})
        assert response["ok"] is False

    def test_unknown_command(self, daemon):
        response = daemon.handle_request({"cmd": "make-coffee"})
        assert response["ok"] is False
        assert "make-coffee" in response["error"]


class TestSocketRoundtrip:
    def test_status_over_real_socket(self, daemon, tmp_path):
        sock_path = tmp_path / "test.sock"
        server = _Server(str(sock_path), daemon)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.settimeout(5)
            conn.connect(str(sock_path))
            conn.sendall(ipc.encode({"cmd": "status"}))
            data = conn.makefile("rb").readline()
            conn.close()
            response = ipc.decode(data.rstrip(b"\n"))
            assert response["ok"] is True
            assert response["phase"] == "idle"
        finally:
            server.shutdown()
            server.server_close()

    def test_garbage_gets_protocol_error(self, daemon, tmp_path):
        sock_path = tmp_path / "test.sock"
        server = _Server(str(sock_path), daemon)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.settimeout(5)
            conn.connect(str(sock_path))
            conn.sendall(b"this is not json\n")
            data = conn.makefile("rb").readline()
            conn.close()
            response = ipc.decode(data.rstrip(b"\n"))
            assert response["ok"] is False
        finally:
            server.shutdown()
            server.server_close()
