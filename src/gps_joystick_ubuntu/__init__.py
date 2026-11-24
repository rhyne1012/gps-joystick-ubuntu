"""CLI entrypoint for GPS Joystick Ubuntu."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import uvicorn

from .server import create_app


def _open_ui(url: str, app_mode: bool) -> None:
    time.sleep(0.9)
    if app_mode:
        profile_dir = Path(tempfile.gettempdir()) / "gps-joystick-ubuntu-app-profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        for browser in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            binary = shutil.which(browser)
            if binary:
                try:
                    subprocess.Popen(
                        [
                            binary,
                            f"--app={url}",
                            f"--user-data-dir={profile_dir}",
                            "--no-first-run",
                        ],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    return
                except OSError:
                    pass

    for opener in ("gio", "xdg-open"):
        binary = shutil.which(opener)
        if binary:
            cmd = [binary, "open", url] if opener == "gio" else [binary, url]
            try:
                subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    env=os.environ.copy(),
                )
                return
            except OSError:
                pass


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
        help="Try launching Chromium/Chrome in an isolated --app window.",
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
