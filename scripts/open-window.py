#!/usr/bin/python3
"""Single-instance native GTK3 + WebKit2GTK window for GPS Joystick Ubuntu."""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gio, GLib, Gtk, WebKit2  # noqa: E402

ICON_PATH = Path(__file__).resolve().parent.parent / "src/gps_joystick_ubuntu/static/icon.svg"


class GPSJoystickWindowApp(Gtk.Application):
    """Single-instance desktop window wrapping the local GPS Joystick UI."""

    def __init__(self, url: str) -> None:
        super().__init__(
            application_id="local.rhyne.gpsjoystickubuntu",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.url = url
        self.window: Gtk.ApplicationWindow | None = None

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        win = Gtk.ApplicationWindow(application=self)
        win.set_title("GPS 搖桿 · Ubuntu iPhone 定位模擬")
        win.set_default_size(1180, 760)
        win.set_position(Gtk.WindowPosition.CENTER)
        if ICON_PATH.exists():
            try:
                win.set_icon_from_file(str(ICON_PATH))
            except Exception:
                pass

        webview = WebKit2.WebView()
        settings = webview.get_settings()
        settings.set_javascript_can_access_clipboard(True)
        webview.load_uri(self.url)

        win.add(webview)
        win.show_all()
        self.window = win


def main() -> int:
    parser = argparse.ArgumentParser(description="Open GPS Joystick in a native WebKit2 window.")
    parser.add_argument("url", nargs="?", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify GTK3/WebKit2GTK imports cleanly and exit.",
    )
    args = parser.parse_args()
    if args.check:
        return 0

    app = GPSJoystickWindowApp(args.url)
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda _app=app: (_app.quit() or True))
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    raise SystemExit(main())
