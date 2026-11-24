"""CLI entrypoint for GPS Joystick Ubuntu."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import threading
import time
import webbrowser

import uvicorn

from .server import create_app


def _open_ui(url: str, app_mode: bool) -> None:
    time.sleep(0.9)
    if app_mode:
        for browser in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            binary = shutil.which(browser)
            if binary:
                try:
                    subprocess.Popen(
                        [binary, f"--app={url}"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return
                except OSError:
                    pass
    webbrowser.open(url)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gps-joystick-ubuntu",
        description="Ubuntu 上的 iPhone USB GPS 定位模擬搖桿工具（支援 iOS 17+ / iOS 27）。",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start server without automatically opening a browser window.",
    )
    parser.add_argument(
        "--app",
        action="store_true",
        help="Try launching Chromium/Chrome in standalone --app window mode.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        threading.Thread(target=_open_ui, args=(url, args.app), daemon=True).start()

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
