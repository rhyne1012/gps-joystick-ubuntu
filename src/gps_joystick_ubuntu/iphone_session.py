"""Async iPhone USB session lifecycle and DVT LocationSimulation manager."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Literal

from pymobiledevice3 import usbmux
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.rsd_tunnel import PreferredRsdTunnel
from pymobiledevice3.services.amfi import AmfiService
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.services.mobile_image_mounter import auto_mount

from .navigation import GeoPoint

SessionPhase = Literal[
    "idle",
    "connecting",
    "ready",
    "syncing",
    "restoring",
    "disconnecting",
    "error",
]


class SessionError(Exception):
    """User-facing iPhone USB session error."""


def _format_error(err: Exception) -> str:
    if isinstance(err, SessionError):
        return str(err)
    if isinstance(err, asyncio.TimeoutError):
        return "iPhone 連線或服務逾時。請確認手機已解鎖、USB 線穩固且已開啟開發者模式。"
    kind = type(err).__name__
    if "Password" in kind or "Locked" in kind:
        return "請先解鎖 iPhone，再重新執行連線。"
    if "Pair" in kind:
        return "iPhone 尚未完成配對信任。請點選「配對信任」並在手機上按「信任」。"
    detail = " ".join(str(err).split())[:200]
    return f"iPhone 開發者服務連線失敗（{kind}: {detail}）"


async def _find_single_usb_serial(expected_serial: str | None = None) -> str:
    devices = [
        d for d in await asyncio.wait_for(usbmux.list_devices(), timeout=5) if d.is_usb
    ]
    if not devices:
        raise SessionError("找不到 USB iPhone。請確認使用可傳資料的 USB 線並已解鎖手機。")
    if len(devices) > 1:
        if expected_serial and any(d.serial == expected_serial for d in devices):
            return expected_serial
        raise SessionError("偵測到多台 USB iOS 裝置。請只連接這台要測試的 iPhone。")
    serial = devices[0].serial
    if expected_serial and serial != expected_serial:
        raise SessionError("請重新接回上次模擬定位的同一台 iPhone，再按「連接 iPhone」恢復定位。")
    return serial


@dataclass
class IPhoneSessionManager:
    """Manages iPhone USB inspection, pairing, RSD tunnel, and LocationSimulation."""

    on_change: Callable[[], None] | None = None
    phase: SessionPhase = "idle"
    device_label: str = ""
    serial: str | None = None
    ios_version: str = ""
    paired: bool | None = None
    developer_mode: bool | None = None
    error: str | None = None
    notice: str | None = None
    restore_unconfirmed: bool = False
    pending_restore_serial: str | None = None
    last_inspect_at: float | None = None

    _op_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _loc_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _stack: AsyncExitStack | None = None
    _location: LocationSimulation | None = None
    _keepalive_task: asyncio.Task[None] | None = None

    def _notify(self) -> None:
        if self.on_change is not None:
            self.on_change()

    def snapshot(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "device_label": self.device_label,
            "serial": self.serial,
            "ios_version": self.ios_version,
            "paired": self.paired,
            "developer_mode": self.developer_mode,
            "error": self.error,
            "notice": self.notice,
            "restore_unconfirmed": self.restore_unconfirmed,
            "pending_restore_serial": self.pending_restore_serial,
            "last_inspect_at": self.last_inspect_at,
        }

    async def inspect(self) -> dict[str, object]:
        """Inspect USB connection, pairing, and Developer Mode without opening DVT."""
        async with self._op_lock:
            if self.phase in ("ready", "syncing"):
                return self.snapshot()
            self.error = None
            self.notice = None
            try:
                serial = await _find_single_usb_serial(self.pending_restore_serial)
                lockdown = await asyncio.wait_for(
                    create_using_usbmux(serial=serial, connection_type="USB", autopair=False),
                    timeout=7,
                )
                async with lockdown:
                    info = lockdown.short_info or {}
                    name = info.get("DeviceName") or "iPhone"
                    version = str(lockdown.product_version or "")
                    self.serial = serial
                    self.ios_version = version
                    self.device_label = f"{name} · iOS {version}" if version else name
                    self.paired = bool(lockdown.paired)
                    if self.paired:
                        try:
                            self.developer_mode = bool(
                                await asyncio.wait_for(lockdown.get_developer_mode_status(), timeout=5)
                            )
                        except Exception:
                            self.developer_mode = None
                    else:
                        self.developer_mode = None
                self.last_inspect_at = time.time()
                if self.phase == "error":
                    self.phase = "idle"
                self.notice = "已偵測到 iPhone。"
            except Exception as err:
                self.serial = None
                self.device_label = ""
                self.ios_version = ""
                self.paired = None
                self.developer_mode = None
                self.last_inspect_at = time.time()
                self.error = _format_error(err)
            self._notify()
            return self.snapshot()

    async def pair(self) -> dict[str, object]:
        """Trigger USB trust pairing on the connected iPhone."""
        async with self._op_lock:
            self.error = None
            self.notice = None
            try:
                serial = await _find_single_usb_serial(self.pending_restore_serial)
                lockdown = await asyncio.wait_for(
                    create_using_usbmux(
                        serial=serial, connection_type="USB", autopair=True, pair_timeout=30
                    ),
                    timeout=35,
                )
                async with lockdown:
                    if not lockdown.paired:
                        await asyncio.wait_for(lockdown.pair(timeout=30), timeout=35)
                    info = lockdown.short_info or {}
                    name = info.get("DeviceName") or "iPhone"
                    version = str(lockdown.product_version or "")
                    self.serial = serial
                    self.ios_version = version
                    self.device_label = f"{name} · iOS {version}" if version else name
                    self.paired = bool(lockdown.paired)
                    if self.paired:
                        self.developer_mode = bool(
                            await asyncio.wait_for(lockdown.get_developer_mode_status(), timeout=5)
                        )
                self.notice = "已完成 USB 信任配對。" if self.paired else "尚未完成配對，請在手機點選「信任」。"
            except Exception as err:
                self.error = _format_error(err)
            self._notify()
            return self.snapshot()

    async def reveal_dev_mode(self) -> dict[str, object]:
        """Request iOS to show the Developer Mode switch in Settings."""
        async with self._op_lock:
            self.error = None
            self.notice = None
            try:
                serial = await _find_single_usb_serial(self.pending_restore_serial)
                lockdown = await asyncio.wait_for(
                    create_using_usbmux(serial=serial, connection_type="USB", autopair=False),
                    timeout=7,
                )
                async with lockdown:
                    if not lockdown.paired:
                        raise SessionError("iPhone 尚未配對信任。請先點選「配對信任」。")
                    await asyncio.wait_for(
                        AmfiService(lockdown).reveal_developer_mode_option_in_ui(), timeout=10
                    )
                self.notice = "已送出顯示指令：請到 iPhone「設定 → 隱私權與安全性 → 開發者模式」開啟並重開機。"
            except Exception as err:
                self.error = _format_error(err)
            self._notify()
            return self.snapshot()

    async def mount_ddi(self) -> dict[str, object]:
        """Download/mount Personalized Developer Disk Image if needed."""
        async with self._op_lock:
            self.error = None
            self.notice = None
            try:
                serial = await _find_single_usb_serial(self.pending_restore_serial)
                lockdown = await asyncio.wait_for(
                    create_using_usbmux(serial=serial, connection_type="USB", autopair=False),
                    timeout=7,
                )
                async with lockdown:
                    if not lockdown.paired:
                        raise SessionError("iPhone 尚未配對信任。請先點選「配對信任」。")
                    await asyncio.wait_for(auto_mount(lockdown), timeout=60)
                self.notice = "Developer Disk Image 掛載完成。"
            except Exception as err:
                self.error = _format_error(err)
            self._notify()
            return self.snapshot()

    async def connect(self) -> dict[str, object]:
        """Open RSD tunnel, DVT provider, and LocationSimulation session."""
        async with self._op_lock:
            if self.phase in ("ready", "syncing"):
                return self.snapshot()
            self.phase = "connecting"
            self.error = None
            self.notice = None
            self._notify()

            stack = AsyncExitStack()
            try:
                serial = await _find_single_usb_serial(self.pending_restore_serial)
                lockdown = await asyncio.wait_for(
                    create_using_usbmux(serial=serial, connection_type="USB", autopair=False),
                    timeout=7,
                )
                async with lockdown:
                    if not lockdown.paired:
                        raise SessionError("iPhone 尚未配對。請先點「配對信任」，並在手機點選「信任」。")
                    info = lockdown.short_info or {}
                    device_class = info.get("DeviceClass")
                    if device_class not in (None, "iPhone"):
                        raise SessionError("請連接要測試的 iPhone。")
                    version = str(lockdown.product_version or "")
                    major = int(version.split(".")[0]) if version and version.split(".")[0].isdigit() else 0
                    if major < 17:
                        raise SessionError("此工具需要 iOS 17 以上版本的開發者通道。")
                    dev_mode = bool(
                        await asyncio.wait_for(lockdown.get_developer_mode_status(), timeout=5)
                    )
                    if not dev_mode:
                        raise SessionError(
                            "iPhone 尚未開啟「開發者模式」。請先點下方「顯示開發者模式」並在手機設定開啟。"
                        )
                    name = info.get("DeviceName") or "iPhone"
                    self.serial = serial
                    self.ios_version = version
                    self.device_label = f"{name} · iOS {version}"
                    self.paired = True
                    self.developer_mode = True

                tunnel = PreferredRsdTunnel(serial=serial, autopair=False)
                rsd = await asyncio.wait_for(stack.enter_async_context(tunnel), timeout=15)
                dvt = await asyncio.wait_for(stack.enter_async_context(DvtProvider(rsd)), timeout=8)
                location = await asyncio.wait_for(
                    stack.enter_async_context(LocationSimulation(dvt)), timeout=8
                )

                self._stack = stack
                self._location = location
                self.phase = "ready"
                self.notice = (
                    "偵測到上次未確認恢復定位，請按「恢復定位」。"
                    if self.restore_unconfirmed
                    else "iPhone 已就緒，可開始同步位置。"
                )
                self._keepalive_task = asyncio.create_task(self._usb_keepalive(serial))
            except Exception as err:
                await stack.aclose()
                self._stack = None
                self._location = None
                self.phase = "error"
                self.error = _format_error(err)
            self._notify()
            return self.snapshot()

    async def start_sync(self, point: GeoPoint) -> dict[str, object]:
        """Enter syncing phase and push initial coordinate."""
        async with self._op_lock:
            if self.phase != "ready" or self._location is None:
                raise SessionError("請先連接 iPhone。")
            if self.restore_unconfirmed:
                raise SessionError("上次尚未確認恢復定位，請先按「恢復定位」。")
            self.phase = "syncing"
            self.error = None
            self.notice = "正在同步模擬位置至 iPhone。"
            self._notify()

        await self.set_location(point)
        return self.snapshot()

    async def set_location(self, point: GeoPoint) -> bool:
        """Send one simulated coordinate to the active iPhone session."""
        if not point.is_valid():
            return False
        async with self._loc_lock:
            location = self._location
            if location is None or self.phase != "syncing":
                return False
            try:
                await asyncio.wait_for(location.set(point.latitude, point.longitude), timeout=4)
                self.restore_unconfirmed = True
                self.pending_restore_serial = self.serial
                return True
            except Exception as err:
                self._handle_runtime_failure(err)
                return False

    def _handle_runtime_failure(self, err: Exception) -> None:
        self.error = _format_error(err)
        self.phase = "error"
        self._notify()
        asyncio.create_task(self._cleanup_stack_only())

    async def restore(self) -> dict[str, object]:
        """Clear simulated GPS on the iPhone and return to ready state."""
        async with self._op_lock:
            if self._location is None or self.phase not in ("ready", "syncing"):
                raise SessionError("目前沒有連線中的 iPhone。")
            prev_phase = self.phase
            self.phase = "restoring"
            self.error = None
            self._notify()

            try:
                async with self._loc_lock:
                    await asyncio.wait_for(self._location.clear(), timeout=5)
                self.restore_unconfirmed = False
                self.pending_restore_serial = None
                self.phase = "ready"
                self.notice = "已恢復 iPhone 真實定位。"
            except Exception as err:
                self.phase = prev_phase if prev_phase == "ready" else "error"
                self.error = _format_error(err)
            self._notify()
            return self.snapshot()

    async def disconnect(self) -> dict[str, object]:
        """Safely clear simulated GPS (if needed) and close the RSD/DVT session."""
        async with self._op_lock:
            if self._stack is None and self._location is None:
                self.phase = "idle"
                self.device_label = ""
                self.serial = None
                self._notify()
                return self.snapshot()

            self.phase = "disconnecting"
            self.error = None
            self._notify()

            keepalive = self._keepalive_task
            self._keepalive_task = None
            if keepalive is not None:
                keepalive.cancel()

            clear_failed: Exception | None = None
            try:
                if self.restore_unconfirmed and self._location is not None:
                    async with self._loc_lock:
                        try:
                            await asyncio.wait_for(self._location.clear(), timeout=4)
                            self.restore_unconfirmed = False
                            self.pending_restore_serial = None
                        except Exception as err:
                            clear_failed = err
            finally:
                if self._stack is not None:
                    try:
                        await self._stack.aclose()
                    except Exception:
                        pass
                self._stack = None
                self._location = None
                self.serial = None
                self.device_label = ""
                if clear_failed is not None:
                    self.phase = "error"
                    self.error = (
                        "中斷連線前未能確認恢復定位，請重新接回同一台 iPhone 並按「恢復定位」。"
                    )
                else:
                    self.phase = "idle"
                    self.notice = "已安全中斷 iPhone 連線。"
            self._notify()
            return self.snapshot()

    async def _cleanup_stack_only(self) -> None:
        keepalive = self._keepalive_task
        self._keepalive_task = None
        if keepalive is not None:
            keepalive.cancel()
        if self._stack is not None:
            try:
                await self._stack.aclose()
            except Exception:
                pass
        self._stack = None
        self._location = None

    async def _usb_keepalive(self, serial: str) -> None:
        try:
            while self.phase in ("ready", "syncing", "restoring"):
                await asyncio.sleep(2.0)
                if self.phase not in ("ready", "syncing", "restoring"):
                    break
                try:
                    devices = [
                        d
                        for d in await asyncio.wait_for(usbmux.list_devices(), timeout=3)
                        if d.is_usb
                    ]
                except Exception:
                    continue
                if not any(d.serial == serial for d in devices):
                    async with self._op_lock:
                        if self.serial == serial and self.phase in ("ready", "syncing", "restoring"):
                            await self._cleanup_stack_only()
                            self.serial = None
                            self.device_label = ""
                            self.phase = "error"
                            self.error = "iPhone 的 USB 連線已中斷。若尚未恢復定位，請重新接上同一台手機。"
                            self._notify()
                    break
        except asyncio.CancelledError:
            return
