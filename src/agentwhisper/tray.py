"""XFCE panel tray icon via GTK/AyatanaAppIndicator (StatusNotifier).

Deliberately NOT pystray: soupawhisper died on pystray silently picking
a dead XEmbed backend. Here we bind the real thing directly — if the
bindings are missing, create_tray() raises TrayUnavailable with the
exact command that fixes it, and the caller decides what to do.

Requires the system GTK bindings, visible because install.sh creates
the venv with --system-site-packages:
    sudo apt install python3-gi python3-gi-cairo gir1.2-ayatanaappindicator3-0.1
"""

from __future__ import annotations

from importlib import resources

from agentwhisper import __version__

APT_HINT = "sudo apt install python3-gi python3-gi-cairo gir1.2-ayatanaappindicator3-0.1"

MODE_LABELS = {
    "hold": "Hold to talk (hold the key)",
    "toggle": "Press to toggle (press to start/stop)",
}


class TrayUnavailable(Exception):
    """Tray cannot run; the message says why and how to fix it."""


def _import_gtk():
    try:
        import gi
    except ImportError as e:
        raise TrayUnavailable(
            "python3-gi (PyGObject) is not importable. If it is installed, the "
            "virtualenv was created without --system-site-packages (rerun install.sh); "
            f"if not: {APT_HINT}"
        ) from e
    try:
        gi.require_version("Gtk", "3.0")
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3, GLib, Gtk
    except (ImportError, ValueError) as e:
        raise TrayUnavailable(
            f"GTK/AyatanaAppIndicator bindings missing or wrong version: {e}. "
            f"Fix: {APT_HINT}"
        ) from e
    return Gtk, GLib, AyatanaAppIndicator3


def _icon_dir() -> str:
    """Directory holding the agentwhisper icons, shipped inside the package."""
    return str(resources.files("agentwhisper") / "icons")


class Tray:
    """Owns the GTK main loop. Constructed via create_tray()."""

    def __init__(self, app):
        """`app` provides: is_enabled(), set_enabled(bool), get_mode(),
        set_mode(str), hotkey_name(), quit()."""
        Gtk, GLib, AppIndicator = _import_gtk()
        self._gtk = Gtk
        self._glib = GLib
        self._app = app
        self._updating_menu = False  # guard against signal feedback loops

        self.indicator = AppIndicator.Indicator.new_with_path(
            "agentwhisper",
            "agentwhisper",
            AppIndicator.IndicatorCategory.APPLICATION_STATUS,
            _icon_dir(),
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("AgentWhisper")
        self.indicator.set_menu(self._build_menu())
        self._refresh_status_label()

    def _build_menu(self):
        Gtk = self._gtk
        menu = Gtk.Menu()

        header = Gtk.MenuItem(label=f"AgentWhisper {__version__}")
        header.set_sensitive(False)
        menu.append(header)

        self._status_item = Gtk.MenuItem(label="")
        self._status_item.set_sensitive(False)
        menu.append(self._status_item)

        menu.append(Gtk.SeparatorMenuItem())

        self._enabled_item = Gtk.CheckMenuItem(label="Enabled")
        self._enabled_item.set_active(self._app.is_enabled())
        self._enabled_item.connect("toggled", self._on_enabled_toggled)
        menu.append(self._enabled_item)

        mode_item = Gtk.MenuItem(label="Recording Mode")
        mode_menu = Gtk.Menu()
        self._mode_items = {}
        group = None
        for mode, label in MODE_LABELS.items():
            item = Gtk.RadioMenuItem(label=label, group=group)
            group = item
            item.connect("toggled", self._on_mode_toggled, mode)
            self._mode_items[mode] = item
            mode_menu.append(item)
        self._updating_menu = True
        self._mode_items[self._app.get_mode()].set_active(True)
        self._updating_menu = False
        mode_item.set_submenu(mode_menu)
        menu.append(mode_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit AgentWhisper")
        quit_item.connect("activate", lambda item: self._app.quit())
        menu.append(quit_item)

        menu.show_all()
        return menu

    # -- menu signal handlers ---------------------------------------------

    def _on_enabled_toggled(self, item):
        if not self._updating_menu:
            self._app.set_enabled(item.get_active())
            self._refresh_status_label()

    def _on_mode_toggled(self, item, mode):
        if not self._updating_menu and item.get_active():
            self._app.set_mode(mode)
            self._refresh_status_label()

    # -- state display (thread-safe) ----------------------------------------

    def set_state(self, state: str) -> None:
        """'idle' | 'recording' | 'transcribing' — safe from any thread."""
        self._glib.idle_add(self._set_state_on_gtk_thread, state)

    def _set_state_on_gtk_thread(self, state: str) -> bool:
        if state == "recording":
            self.indicator.set_icon_full("agentwhisper-recording", "recording")
            self._status_item.set_label("● Recording…")
        elif state == "transcribing":
            self.indicator.set_icon_full("agentwhisper", "transcribing")
            self._status_item.set_label("⋯ Transcribing…")
        else:
            self.indicator.set_icon_full("agentwhisper", "idle")
            self._refresh_status_label()
        return False

    def _refresh_status_label(self) -> None:
        key = self._app.hotkey_name().upper()
        if not self._app.is_enabled():
            text = "Disabled"
        elif self._app.get_mode() == "hold":
            text = f"Ready — hold {key} to dictate"
        else:
            text = f"Ready — press {key} to start/stop"
        self._status_item.set_label(text)

    # -- lifecycle -----------------------------------------------------------

    def run(self):
        """Blocks in the GTK main loop; call from the main thread."""
        import signal

        # Gtk.main() blocks Python-level signal delivery; register with GLib.
        for sig in (signal.SIGINT, signal.SIGTERM):
            self._glib.unix_signal_add(
                self._glib.PRIORITY_DEFAULT, sig, self._on_signal, None
            )
        self._gtk.main()

    def _on_signal(self, _data):
        self._app.quit()
        return self._glib.SOURCE_REMOVE

    def stop(self):
        """Thread-safe: ends the GTK main loop."""
        self._glib.idle_add(self._gtk.main_quit)


def create_tray(app) -> Tray:
    """Raise TrayUnavailable (with remediation) if the panel tray can't work."""
    import os

    if not os.environ.get("DISPLAY"):
        raise TrayUnavailable("no DISPLAY: not a graphical session")
    return Tray(app)
