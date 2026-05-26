"""FastAPI server: serves the React UI events over a WebSocket and exposes a
REST endpoint to (re)start a simulation."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .simulation import Simulation


app = FastAPI(title="Escapism — Black Vesper", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Hub:
    """Tracks connected WebSocket clients and replays history to new joiners."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.history: list[dict[str, Any]] = []
        self.sim_task: asyncio.Task[None] | None = None

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)
        await ws.send_text(json.dumps({"kind": "history", "events": self.history}))

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, event: dict[str, Any]) -> None:
        self.history.append(event)
        dead: list[WebSocket] = []
        for ws in self.clients:
            try:
                await ws.send_text(json.dumps(event))
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def start_simulation(self) -> None:
        if self.sim_task and not self.sim_task.done():
            return
        self.history.clear()
        sim = Simulation.build(broadcast=self.broadcast)
        self.sim_task = asyncio.create_task(sim.run_loop())


hub = Hub()


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/start")
async def start() -> dict[str, str]:
    await hub.start_simulation()
    return {"status": "started"}


@app.post("/api/reset")
async def reset() -> dict[str, str]:
    if hub.sim_task and not hub.sim_task.done():
        hub.sim_task.cancel()
    hub.history.clear()
    await hub.broadcast({"kind": "reset", "actor": "system", "tick": 0, "payload": {}})
    await hub.start_simulation()
    return {"status": "reset"}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await hub.connect(ws)
    try:
        while True:
            # We don't currently expect inbound messages, but keep the socket open.
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(ws)


@app.on_event("startup")
async def _autostart() -> None:
    await hub.start_simulation()
