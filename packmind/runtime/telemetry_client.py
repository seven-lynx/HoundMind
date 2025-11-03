#!/usr/bin/env python3
"""
Tiny non-blocking telemetry client for PackMind.

- Uses a background thread with a queue to POST JSON events to the telemetry server /ingest endpoint.
- Standard library only (urllib); no external dependencies.
- Best-effort: drops events on queue overflow; logs only at debug level to avoid noise.

Usage:
    client = TelemetryClient(base_url="http://127.0.0.1:8765", basic_auth=("user","pass"))
    client.start()
    client.publish({"type": "heartbeat", "ts": time.time()})
    ...
    client.stop()
"""
from __future__ import annotations

import base64
import json
import queue
import threading
import time
import urllib.request
import urllib.error
from typing import Any, Dict, Optional, Tuple


class TelemetryClient:
    def __init__(self, base_url: str, basic_auth: Optional[Tuple[str, str]] = None, *, queue_maxsize: int = 1000, timeout: float = 2.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.ingest_url = f"{self.base_url}/ingest"
        self.basic_auth = basic_auth
        self.timeout = float(timeout)
        self._q: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=max(10, int(queue_maxsize)))
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._dropped = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="TelemetryClient", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout)

    def publish(self, event: Dict[str, Any]) -> None:
        try:
            self._q.put_nowait(dict(event))
        except queue.Full:
            self._dropped += 1

    # --- internals ---
    def _loop(self) -> None:
        backoff = 0.1
        while not self._stop.is_set():
            try:
                try:
                    ev = self._q.get(timeout=0.2)
                except queue.Empty:
                    continue
                self._post_json(self.ingest_url, ev)
                backoff = 0.1
            except Exception:
                # Backoff on errors, but keep draining queue to avoid unbounded growth
                time.sleep(backoff)
                backoff = min(5.0, backoff * 2.0)

    def _post_json(self, url: str, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        if self.basic_auth:
            user, pwd = self.basic_auth
            token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
            req.add_header("Authorization", f"Basic {token}")
        # Send
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            # Read/ignore body to allow connection reuse (even though we close quickly)
            try:
                _ = resp.read()
            except Exception:
                pass

__all__ = ["TelemetryClient"]
