"""FastAPI server and WebSocket simulation loop for Ubuntu GPS Joystick."""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .iphone_session import IPhoneSessionManager, SessionError
from .navigation import GeoPoint, NavigationEngine
from .search import search_places

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _combined_state(nav: NavigationEngine, session: IPhoneSessionManager) -> dict[str, Any]:
    return {
        "navigation": nav.snapshot(),
        "device": session.snapshot(),
    }


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    nav = NavigationEngine()
    clients: set[WebSocket] = set()
    dirty_event = asyncio.Event()
    sync_immediate = asyncio.Event()

    def on_session_change() -> None:
        dirty_event.set()

    session = IPhoneSessionManager(on_change=on_session_change)

    async def broadcast_state() -> None:
        if not clients:
            return
        payload = json.dumps(_combined_state(nav, session), ensure_ascii=False)
        stale: list[WebSocket] = []
        for ws in list(clients):
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            clients.discard(ws)

    async def simulation_loop() -> None:
        last_tick = time.monotonic()
        last_broadcast = 0.0
        last_sync_at = 0.0
        sync_task: asyncio.Task[bool] | None = None
        last_sent_pos: GeoPoint | None = None

        try:
            while True:
                await asyncio.sleep(1.0 / 30.0)
                now = time.monotonic()
                dt = now - last_tick
                last_tick = now

                moved = nav.tick(dt)
                if moved:
                    dirty_event.set()

                if session.phase == "syncing":
                    need_immediate = sync_immediate.is_set()
                    pos_changed = last_sent_pos != nav.position
                    due = (now - last_sync_at) >= 0.25
                    if (sync_task is None or sync_task.done()) and (
                        need_immediate or (pos_changed and due)
                    ):
                        sync_immediate.clear()
                        target = nav.position
                        last_sent_pos = target
                        last_sync_at = now
                        sync_task = asyncio.create_task(session.set_location(target))

                if dirty_event.is_set() and (now - last_broadcast >= 0.065 or not moved):
                    dirty_event.clear()
                    last_broadcast = now
                    await broadcast_state()
        except asyncio.CancelledError:
            if sync_task is not None and not sync_task.done():
                sync_task.cancel()
            raise

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        loop_task = asyncio.create_task(simulation_loop())
        try:
            yield
        finally:
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass
            nav.pause()
            await session.disconnect()

    app = FastAPI(title="GPS Joystick Ubuntu", lifespan=lifespan)
    app.state.nav = nav
    app.state.session = session
    app.state.clients = clients
    app.state.dirty_event = dirty_event
    app.state.sync_immediate = sync_immediate

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/state")
    async def get_state() -> dict[str, Any]:
        return _combined_state(nav, session)

    @app.get("/api/search")
    async def api_search(
        q: str = Query(default="", max_length=200),
        lat: float | None = Query(default=None),
        lon: float | None = Query(default=None),
    ) -> dict[str, object]:
        return await search_places(q, lat=lat, lon=lon)

    @app.post("/api/device/inspect")
    async def device_inspect() -> dict[str, object]:
        return await session.inspect()

    @app.post("/api/device/pair")
    async def device_pair() -> dict[str, object]:
        return await session.pair()

    @app.post("/api/device/reveal-dev-mode")
    async def device_reveal_dev_mode() -> dict[str, object]:
        return await session.reveal_dev_mode()

    @app.post("/api/device/mount-ddi")
    async def device_mount_ddi() -> dict[str, object]:
        return await session.mount_ddi()

    @app.post("/api/device/connect")
    async def device_connect() -> dict[str, object]:
        return await session.connect()

    @app.post("/api/device/start-sync")
    async def device_start_sync() -> JSONResponse:
        try:
            snapshot = await session.start_sync(nav.position)
            return JSONResponse(snapshot)
        except SessionError as err:
            return JSONResponse({"error": str(err), **session.snapshot()}, status_code=400)

    @app.post("/api/device/restore")
    async def device_restore() -> JSONResponse:
        try:
            snapshot = await session.restore()
            return JSONResponse(snapshot)
        except SessionError as err:
            return JSONResponse({"error": str(err), **session.snapshot()}, status_code=400)

    @app.post("/api/device/disconnect")
    async def device_disconnect() -> dict[str, object]:
        nav.pause()
        dirty_event.set()
        return await session.disconnect()

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        clients.add(ws)
        try:
            await ws.send_text(json.dumps(_combined_state(nav, session), ensure_ascii=False))
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                action = msg.get("action")
                if action == "stick":
                    nav.set_stick(float(msg.get("east", 0.0)), float(msg.get("north", 0.0)))
                    dirty_event.set()
                elif action == "speed":
                    nav.set_speed(float(msg.get("speed_kph", 5.0)))
                    dirty_event.set()
                elif action == "toggle_motion":
                    nav.toggle_motion()
                    dirty_event.set()
                elif action == "pause":
                    nav.pause()
                    dirty_event.set()
                elif action == "set_start":
                    point = GeoPoint(
                        latitude=float(msg.get("latitude", 0.0)),
                        longitude=float(msg.get("longitude", 0.0)),
                    )
                    if nav.set_start(point):
                        sync_immediate.set()
                        dirty_event.set()
                elif action == "clear_trail":
                    nav.clear_trail()
                    dirty_event.set()
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(ws)

    return app


app = create_app()
