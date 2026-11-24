"""Ubuntu iPhone/iOS USB diagnostic and location-simulation probe CLI."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import os
import shutil
import subprocess
import sys
from contextlib import AsyncExitStack

from pymobiledevice3 import usbmux
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.rsd_tunnel import PreferredRsdTunnel
from pymobiledevice3.services.amfi import AmfiService
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.services.mobile_image_mounter import auto_mount

TAIPEI_101 = (25.03396, 121.56447)


def _run_cmd(args: list[str]) -> tuple[int, str]:
    if not shutil.which(args[0]):
        return -1, f"{args[0]} not found"
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    output = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode, output


def check_usb_environment() -> tuple[bool, list[str]]:
    """Return whether an Apple USB device is enumerated, plus diagnostic lines."""
    lines: list[str] = []
    _, lsusb_out = _run_cmd(["lsusb"])
    apple_lines = [
        line for line in lsusb_out.splitlines() if "05ac:" in line.lower() or "apple" in line.lower()
    ]
    socket_exists = os.path.exists("/var/run/usbmuxd")
    _, usbmux_status = _run_cmd(["systemctl", "is-active", "usbmuxd"])

    lines.append(f"pymobiledevice3: {importlib.metadata.version('pymobiledevice3')}")
    lines.append(f"usbmuxd service: {usbmux_status or 'unknown'}")
    lines.append(f"/var/run/usbmuxd socket: {'present' if socket_exists else 'missing'}")

    if apple_lines:
        lines.append("Apple USB devices (lsusb):")
        lines.extend(f"  {item}" for item in apple_lines)
        return True, lines

    lines.append("Apple USB devices (lsusb): none detected (no 05ac:* device)")
    return False, lines


async def select_usb_device(expected_serial: str | None = None) -> str:
    """Discover and return a single connected USB iOS device serial."""
    devices = [
        device for device in await asyncio.wait_for(usbmux.list_devices(), timeout=5) if device.is_usb
    ]
    if not devices:
        raise RuntimeError(
            "usbmuxd could not find any USB iPhone. Ensure usbmuxd is running, "
            "the cable supports data, and the iPhone is unlocked."
        )
    if expected_serial:
        for device in devices:
            if device.serial == expected_serial:
                return device.serial
        raise RuntimeError(f"Expected serial {expected_serial} not found among connected USB devices.")
    if len(devices) > 1:
        serials = ", ".join(d.serial for d in devices)
        raise RuntimeError(f"Multiple USB devices found ({serials}); specify --serial.")
    return devices[0].serial


async def cmd_probe(serial_arg: str | None, test_location: bool) -> int:
    has_apple_usb, diag_lines = check_usb_environment()
    for line in diag_lines:
        print(line)

    if not has_apple_usb:
        print(
            "\nNo Apple USB device is currently visible to the Linux kernel.\n"
            "Check: (1) use a data-capable USB cable, (2) unlock iPhone and replug, "
            "(3) try another direct USB port on the host."
        )
        return 2

    serial = await select_usb_device(serial_arg)
    print(f"Target USB serial: {serial}")

    lockdown = await asyncio.wait_for(
        create_using_usbmux(serial=serial, connection_type="USB", autopair=False),
        timeout=7,
    )
    paired = False
    async with lockdown:
        info = lockdown.short_info or {}
        paired = bool(lockdown.paired)
        print(f"DeviceName: {info.get('DeviceName', 'unknown')}")
        print(f"ProductType: {info.get('ProductType', 'unknown')}")
        print(f"ProductVersion: {lockdown.product_version}")
        print(f"Paired: {paired}")

        if not paired:
            print("DeveloperMode: unknown (device is not paired yet; run `probe_iphone.py pair`)")
            if test_location:
                print("Cannot run --test-location before pairing.", file=sys.stderr)
                return 1
            return 0

        try:
            dev_mode = await asyncio.wait_for(lockdown.get_developer_mode_status(), timeout=5)
            print(f"DeveloperMode: {'enabled' if dev_mode else 'disabled'}")
        except Exception as err:
            print(f"DeveloperMode: failed to query ({type(err).__name__}: {err})")
            dev_mode = None

    if not test_location:
        return 0

    if dev_mode is False:
        print(
            "Developer Mode is disabled on the iPhone. Enable it in "
            "Settings -> Privacy & Security -> Developer Mode first.",
            file=sys.stderr,
        )
        return 1

    print(f"Opening RSD tunnel and testing LocationSimulation at Taipei 101 {TAIPEI_101}...")
    async with AsyncExitStack() as stack:
        tunnel = PreferredRsdTunnel(serial=serial, autopair=False)
        rsd = await asyncio.wait_for(stack.enter_async_context(tunnel), timeout=15)
        dvt = await asyncio.wait_for(stack.enter_async_context(DvtProvider(rsd)), timeout=8)
        location = await asyncio.wait_for(
            stack.enter_async_context(LocationSimulation(dvt)), timeout=8
        )
        try:
            await asyncio.wait_for(location.set(*TAIPEI_101), timeout=5)
            print(f"LocationSimulation.set{TAIPEI_101} succeeded; holding for 2s...")
            await asyncio.sleep(2)
        finally:
            await asyncio.wait_for(location.clear(), timeout=5)
            print("LocationSimulation.clear() succeeded.")
    return 0


async def cmd_pair(serial_arg: str | None) -> int:
    has_apple_usb, diag_lines = check_usb_environment()
    for line in diag_lines:
        print(line)
    if not has_apple_usb:
        return 2

    serial = await select_usb_device(serial_arg)
    print(f"Pairing with USB serial: {serial} (tap 'Trust' on your iPhone if prompted)...")
    lockdown = await asyncio.wait_for(
        create_using_usbmux(serial=serial, connection_type="USB", autopair=True, pair_timeout=30),
        timeout=35,
    )
    async with lockdown:
        if not lockdown.paired:
            await asyncio.wait_for(lockdown.pair(timeout=30), timeout=35)
        print(f"Paired: {lockdown.paired}")
    return 0 if lockdown.paired else 1


async def cmd_reveal_dev_mode(serial_arg: str | None) -> int:
    has_apple_usb, diag_lines = check_usb_environment()
    for line in diag_lines:
        print(line)
    if not has_apple_usb:
        return 2

    serial = await select_usb_device(serial_arg)
    lockdown = await asyncio.wait_for(
        create_using_usbmux(serial=serial, connection_type="USB", autopair=False),
        timeout=7,
    )
    async with lockdown:
        if not lockdown.paired:
            raise RuntimeError("Device is not paired. Run `pair` first.")
        await asyncio.wait_for(AmfiService(lockdown).reveal_developer_mode_option_in_ui(), timeout=10)
        print("Requested iPhone to reveal Developer Mode in Settings -> Privacy & Security.")
    return 0


async def cmd_mount_ddi(serial_arg: str | None) -> int:
    has_apple_usb, diag_lines = check_usb_environment()
    for line in diag_lines:
        print(line)
    if not has_apple_usb:
        return 2

    serial = await select_usb_device(serial_arg)
    lockdown = await asyncio.wait_for(
        create_using_usbmux(serial=serial, connection_type="USB", autopair=False),
        timeout=7,
    )
    async with lockdown:
        if not lockdown.paired:
            raise RuntimeError("Device is not paired. Run `pair` first.")
        await asyncio.wait_for(auto_mount(lockdown), timeout=60)
        print("Developer Disk Image auto_mount completed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Diagnose iPhone USB connectivity and test iOS LocationSimulation on Ubuntu."
    )
    parser.add_argument("--serial", help="Optional iPhone UDID/serial if multiple USB devices exist.")

    sub = parser.add_subparsers(dest="command")
    probe_parser = sub.add_parser("probe", help="Inspect USB/lockdown state and optionally test GPS.")
    probe_parser.add_argument(
        "--test-location",
        action="store_true",
        help="Set simulated GPS to Taipei 101 for 2 seconds and then clear it.",
    )
    sub.add_parser("pair", help="Trigger USB pairing ('Trust This Computer') with the iPhone.")
    sub.add_parser("reveal-dev-mode", help="Reveal Developer Mode toggle in iPhone Settings.")
    sub.add_parser("mount-ddi", help="Mount Personalized Developer Disk Image via auto_mount.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    command = args.command or "probe"

    try:
        if command == "probe":
            return asyncio.run(cmd_probe(args.serial, getattr(args, "test_location", False)))
        if command == "pair":
            return asyncio.run(cmd_pair(args.serial))
        if command == "reveal-dev-mode":
            return asyncio.run(cmd_reveal_dev_mode(args.serial))
        if command == "mount-ddi":
            return asyncio.run(cmd_mount_ddi(args.serial))
        parser.print_help()
        return 1
    except Exception as err:
        print(f"ERROR: {type(err).__name__}: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
