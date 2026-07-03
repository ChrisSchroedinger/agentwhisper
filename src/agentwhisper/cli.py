"""agentwhisper — CLI client for the daemon."""

from __future__ import annotations

import argparse
import socket
import sys

from agentwhisper import __version__, ipc


def _request(message: dict, timeout: float = 5.0) -> dict:
    path = ipc.socket_path()
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(timeout)
    try:
        conn.connect(str(path))
        conn.sendall(ipc.encode(message))
        data = b""
        while not data.endswith(b"\n"):
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
    finally:
        conn.close()
    return ipc.decode(data.rstrip(b"\n"))


def _daemon_not_running() -> int:
    print(
        "The AgentWhisper daemon is not running.\n"
        "Start it from the XFCE menu (AgentWhisper) or run: agentwhisperd",
        file=sys.stderr,
    )
    return 3


def cmd_status() -> int:
    s = _request({"cmd": "status"})
    if not s.get("ok"):
        print(f"error: {s.get('error')}", file=sys.stderr)
        return 1
    print(f"agentwhisperd {s['version']} (pid {s['pid']})")
    print(f"  phase:      {s['phase']}")
    print(f"  enabled:    {s['enabled']}")
    print(f"  model:      {s['model']}")
    print(f"  engine:     {s['engine']}")
    print(f"  clipboard:  {s['clipboard']}")
    print(f"  mode:       {s['mode']}")
    print(f"  hotkey:     {s['hotkey']} — {s['hotkey_status']}")
    print(f"  tray:       {s['tray']}")
    print(f"  visualizer: {s['visualizer']}")
    print(f"  uptime:     {s['uptime_seconds']}s")
    return 0


def cmd_toggle() -> int:
    s = _request({"cmd": "toggle-enabled"})
    if not s.get("ok"):
        print(f"error: {s.get('error')}", file=sys.stderr)
        return 1
    print(f"dictation {'enabled' if s['enabled'] else 'disabled'}")
    return 0


def cmd_mode(mode: str) -> int:
    s = _request({"cmd": "set-mode", "mode": mode})
    if not s.get("ok"):
        print(f"error: {s.get('error')}", file=sys.stderr)
        return 1
    print(f"recording mode set to {s['mode']}")
    return 0


def cmd_quit() -> int:
    s = _request({"cmd": "quit"})
    if not s.get("ok"):
        print(f"error: {s.get('error')}", file=sys.stderr)
        return 1
    print("daemon shutting down")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="agentwhisper", description="Control the AgentWhisper dictation daemon."
    )
    parser.add_argument("--version", action="version", version=f"agentwhisper {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show daemon state")
    sub.add_parser("toggle", help="enable/disable dictation")
    mode_parser = sub.add_parser("mode", help="set the recording mode")
    mode_parser.add_argument("mode", choices=["hold", "toggle"],
                             help="hold = push-to-talk, toggle = press to start/stop")
    sub.add_parser("quit", help="stop the daemon")
    args = parser.parse_args()

    try:
        if args.command == "mode":
            return cmd_mode(args.mode)
        handlers = {"status": cmd_status, "toggle": cmd_toggle, "quit": cmd_quit}
        return handlers[args.command]()
    except (FileNotFoundError, ConnectionRefusedError):
        return _daemon_not_running()
    except (TimeoutError, ipc.ProtocolError) as e:
        print(f"error talking to the daemon: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
