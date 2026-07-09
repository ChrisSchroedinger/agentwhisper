"""The DesktopBackend contract: everything that touches the display
server lives behind this, so Wayland later is a new module, not a
rewrite.
"""

from __future__ import annotations

from typing import Protocol


class DesktopError(Exception):
    """A desktop operation failed; the message says why and how to fix it."""


class DesktopBackend(Protocol):
    def check(self) -> list[str]:
        """Return problems that would break operations (missing tools, no
        display). Empty list = all good. Called once at startup so
        failures are loud and early, not silent and late."""
        ...

    def copy(self, text: str) -> None:
        """Put text on the clipboard. Raises DesktopError."""
        ...

    def type_text(self, text: str) -> None:
        """Type text into the currently focused window. Raises DesktopError."""
        ...

    def select_window(self) -> tuple[str, str]:
        """Let the user pick a window by clicking it; blocks until the
        click. Returns (window_id, title). Raises DesktopError (also on
        timeout)."""
        ...

    def window_title(self, window_id: str) -> str | None:
        """The window's current title, or None if the window is gone."""
        ...

    def type_into_window(self, window_id: str, text: str) -> None:
        """Bring the window to the front, type text into it, then press
        Enter to submit it. Raises DesktopError."""
        ...

    def notify(self, summary: str, body: str = "") -> None:
        """Show a desktop notification, replacing the previous one from
        this app (no notification stacking). Raises DesktopError."""
        ...
