"""X11 desktop backend. Clipboard via xclip (verified at startup)."""

from __future__ import annotations

import os
import shutil
import subprocess

from agentwhisper.desktop.base import DesktopError


class X11Desktop:
    def check(self) -> list[str]:
        problems = []
        if not os.environ.get("DISPLAY"):
            problems.append("no DISPLAY: clipboard needs a graphical X11 session")
        if shutil.which("xclip") is None:
            problems.append("xclip is not installed — fix: sudo apt install xclip")
        return problems

    def copy(self, text: str) -> None:
        try:
            # xclip forks and owns the selection; a short timeout only
            # guards the handover, not the clipboard's lifetime.
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode(),
                timeout=5,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise DesktopError("xclip is not installed — sudo apt install xclip") from e
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or b"").decode(errors="replace").strip()
            raise DesktopError(f"xclip failed: {stderr or e}") from e
        except subprocess.TimeoutExpired as e:
            raise DesktopError("xclip timed out taking the clipboard") from e
