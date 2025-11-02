"""
PackMind Telemetry Server (P1 scaffolding)

- HTTP: /health, /status, /
- WebSocket: /ws/events (broadcast-only)
- Minimal single-file FastAPI app with an in-process event hub.

Optional dependency: FastAPI + Uvicorn.
If not installed, importing this module will still succeed, but start() will raise
with a helpful message.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Set as TSet, TYPE_CHECKING, cast

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, JSONResponse
    import uvicorn
except Exception:  # pragma: no cover - optional
    FastAPI = None  # type: ignore
    WebSocket = None  # type: ignore
    WebSocketDisconnect = Exception  # type: ignore
    HTMLResponse = None  # type: ignore
    JSONResponse = None  # type: ignore
    uvicorn = None  # type: ignore


@dataclass
class TelemetryStatus:
    started_at: float
    uptime_s: float
    clients: int
    events_sent: int


class TelemetryHub:
    """Simple in-memory publisher for telemetry events."""

    def __init__(self) -> None:
        # Use Any to avoid analyzer issues when FastAPI isn't installed
        self._clients = set()  # type: ignore[var-annotated]
        self._events_sent = 0
        self._started = time.time()
        self._lock = asyncio.Lock()

    async def register(self, ws: Any) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def unregister(self, ws: Any) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def publish(self, event: Dict[str, Any]) -> None:
        # Broadcast to all connected clients; drop broken sockets
        payload = json.dumps(event, separators=(",", ":"))
        stale: TSet[Any] = set()
        async with self._lock:
            for ws in list(self._clients):
                try:
                    await ws.send_text(payload)
                    self._events_sent += 1
                except Exception:
                    stale.add(ws)
            for s in stale:
                self._clients.discard(s)

    def status(self) -> TelemetryStatus:
        return TelemetryStatus(
            started_at=self._started,
            uptime_s=time.time() - self._started,
            clients=len(self._clients),
            events_sent=self._events_sent,
        )


def build_app(hub: TelemetryHub) -> Any:
    if FastAPI is None:
        raise RuntimeError(
            "FastAPI/uvicorn are not installed. Install optional deps: pip install fastapi uvicorn"
        )
    app = FastAPI(title="PackMind Telemetry", version="2025.11.01")

    @app.get("/health")
    async def health() -> Any:
        return {"ok": True, "ts": time.time()}

    @app.get("/status")
    async def status() -> Any:
        return asdict(hub.status())

    INDEX_HTML = """
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8" />
      <title>PackMind Telemetry</title>
      <style>
        body { font-family: system-ui, Arial, sans-serif; margin: 1rem; }
        #events { height: 300px; overflow: auto; background: #111; color: #0f0; padding: .5rem; }
        .row { white-space: pre; font-family: ui-monospace, Consolas, monospace; }
      </style>
    </head>
    <body>
      <h1>PackMind Telemetry</h1>
      <div>
        <button id="btnPing">Ping Event</button>
        <button id="btnClear">Clear</button>
        <span id="status">connecting...</span>
      </div>
      <pre id="stats"></pre>
      <div id="events"></div>
      <script>
        const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new WebSocket(`${wsProto}://${location.host}/ws/events`);
        const eventsDiv = document.getElementById('events');
        const statsPre = document.getElementById('stats');
        const statusSpan = document.getElementById('status');
        ws.onopen = () => { statusSpan.textContent = 'connected'; };
        ws.onclose = () => { statusSpan.textContent = 'disconnected'; };
        ws.onmessage = (ev) => {
          const row = document.createElement('div');
          row.className = 'row';
          row.textContent = ev.data;
          eventsDiv.appendChild(row);
          eventsDiv.scrollTop = eventsDiv.scrollHeight;
        };
        document.getElementById('btnPing').onclick = async () => {
          try { await fetch('/status').then(r => r.json()).then(j => { statsPre.textContent = JSON.stringify(j, null, 2); }); } catch {}
        };
        document.getElementById('btnClear').onclick = () => { eventsDiv.innerHTML = ''; };
      </script>
    </body>
    </html>
    """

    @app.get("/")
    async def index() -> Any:
        return cast(Any, HTMLResponse)(INDEX_HTML)

    @app.websocket("/ws/events")
    async def ws_events(ws: Any) -> Any:
        await ws.accept()
        await hub.register(ws)
        # Send a welcome event
        await ws.send_text(json.dumps({"type": "welcome", "ts": time.time()}))
        try:
            while True:
                # Keep the connection alive by reading (even if we don't use the data)
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await hub.unregister(ws)
        return None

    return app


def start(host: str = "0.0.0.0", port: int = 8765) -> None:
    if uvicorn is None:
        raise RuntimeError(
            "Uvicorn is not installed. Install optional deps: pip install uvicorn fastapi"
        )
    hub = TelemetryHub()
    app = build_app(hub)

    # Optional: demo publisher task emitting a heartbeat every 2s if run standalone
    async def _demo():
        while True:
            await hub.publish({"type": "heartbeat", "ts": time.time()})
            await asyncio.sleep(2.0)

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    async def _run():
        asyncio.create_task(_demo())
        await server.serve()

    asyncio.run(_run())


__all__ = ["TelemetryHub", "build_app", "start"]
