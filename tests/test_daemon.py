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
        assert s["clipboard"] == "ok"
        assert s["mode"] == "hold"
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
