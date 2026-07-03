"""The DesktopBackend contract: everything that touches the display
server lives behind this, so Wayland later is a new module, not a
rewrite. Milestone 3 needs copy(); type_text() and notify() join in
milestone 4.
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
