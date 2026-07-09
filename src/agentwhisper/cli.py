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
    print(f"  desktop:    {s['desktop']}")
    print(f"  auto-type:  {s['auto_type']}")
    print(f"  notify:     {s['notifications']}")
    print(f"  mode:       {s['mode']}")
    print(f"  limit:      {s['max_record_seconds']}s")
    print(f"  target:     {s['target_window'] or 'active window'}")
    print(f"  autostart:  {s['autostart']}")
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


def cmd_limit(seconds: int) -> int:
    s = _request({"cmd": "set-limit", "seconds": seconds})
    if not s.get("ok"):
        print(f"error: {s.get('error')}", file=sys.stderr)
        return 1
    print(f"recording limit set to {s['max_record_seconds']} seconds")
    return 0


def cmd_target(action: str) -> int:
    if action == "choose":
        print("Click the window that should receive your dictations…")
        # The daemon waits up to 30 s for the click; outlive that.
        s = _request({"cmd": "set-target"}, timeout=35.0)
        if not s.get("ok"):
            print(f"error: {s.get('error')}", file=sys.stderr)
            return 1
        print(f"dictating into: {s['target_window']} "
              "(typed there + submitted with Enter)")
        return 0
    s = _request({"cmd": "clear-target"})
    if not s.get("ok"):
        print(f"error: {s.get('error')}", file=sys.stderr)
        return 1
    print("back to typing into the active window")
    return 0


def cmd_autostart(state: str) -> int:
    s = _request({"cmd": "set-autostart", "enabled": state == "on"})
    if not s.get("ok"):
        print(f"error: {s.get('error')}", file=sys.stderr)
        return 1
    print(f"start at login {'enabled' if s['autostart'] else 'disabled'}")
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
    limit_parser = sub.add_parser("limit", help="set the max recording length")
    limit_parser.add_argument("seconds", type=int,
                              help="hard cap on a single recording, in seconds (30-600)")
    target_parser = sub.add_parser(
        "target", help="send every dictation to one chosen window (+ Enter)")
    target_parser.add_argument("action", choices=["choose", "clear"],
                               help="choose = click a window, clear = back to normal")
    autostart_parser = sub.add_parser("autostart", help="start AgentWhisper at login")
    autostart_parser.add_argument("state", choices=["on", "off"])
    sub.add_parser("quit", help="stop the daemon")
    args = parser.parse_args()

    try:
        if args.command == "mode":
            return cmd_mode(args.mode)
        if args.command == "limit":
            return cmd_limit(args.seconds)
        if args.command == "target":
            return cmd_target(args.action)
        if args.command == "autostart":
            return cmd_autostart(args.state)
        handlers = {"status": cmd_status, "toggle": cmd_toggle, "quit": cmd_quit}
        return handlers[args.command]()
    except (FileNotFoundError, ConnectionRefusedError):
        return _daemon_not_running()
    except (TimeoutError, ipc.ProtocolError) as e:
        print(f"error talking to the daemon: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
