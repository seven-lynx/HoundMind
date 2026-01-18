from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class TelemetryDashboardModule(Module):
    """Optional telemetry dashboard (Pi4-focused).

    Exposes a small HTTP server with JSON snapshots of selected context keys.
    Disabled by default and safe to leave off for Pi3.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.available = False
        self._http_server: ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._snapshot: dict = {}
        self._last_ts = 0.0
        self._last_vision_ts: float | None = None
        self._vision_fps: float | None = None

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        self.available = True
        settings = (context.get("settings") or {}).get("telemetry_dashboard", {})
        self._maybe_start_http(settings)
        context.set("telemetry_status", {"status": "ready"})

    def tick(self, context) -> None:
        if not self.available or not self.status.enabled:
            return

        settings = (context.get("settings") or {}).get("telemetry_dashboard", {})
        if not settings.get("enabled", True):
            return

        interval = float(settings.get("snapshot_interval_s", 0.5))
        now = time.time()
        if now - self._last_ts < interval:
            return

        keys = settings.get(
            "context_keys",
            [
                "sensor_reading",
                "scan_latest",
                "mapping_openings",
                "navigation_action",
                "behavior_action",
                "safety_action",
                "performance_telemetry",
                "slam_pose",
                "slam_map_data",
                "slam_trajectory",
                "faces",
                "semantic_labels",
            ],
        )

        vision_ts = context.get("vision_frame_ts")
        if isinstance(vision_ts, (int, float)):
            if self._last_vision_ts is not None:
                dt = float(vision_ts) - float(self._last_vision_ts)
                if dt > 0:
                    self._vision_fps = 1.0 / dt
            self._last_vision_ts = float(vision_ts)

        health_status = context.get("health_status") or {}
        runtime_perf = context.get("runtime_performance") or {}
        performance = {
            "timestamp": now,
            "tick_hz_target": runtime_perf.get("tick_hz_target"),
            "tick_hz_actual": runtime_perf.get("tick_hz_actual"),
            "tick_duration_s": runtime_perf.get("tick_duration_s"),
            "tick_duration_avg_s": runtime_perf.get("tick_duration_avg_s"),
            "tick_interval_s": runtime_perf.get("tick_interval_s"),
            "tick_interval_avg_s": runtime_perf.get("tick_interval_avg_s"),
            "tick_overrun_s": runtime_perf.get("tick_overrun_s"),
            "vision_fps": self._vision_fps,
            "cpu_load_1m": health_status.get("load_1m"),
            "cpu_temp_c": health_status.get("temp_c"),
            "gpu_temp_c": health_status.get("gpu_temp_c"),
            "mem_used_pct": health_status.get("mem_used_pct"),
            "cpu_cores": health_status.get("cpu_cores"),
            "health_degraded": health_status.get("degraded"),
        }
        context.set("performance_telemetry", performance)

        snapshot = {"timestamp": now}
        for key in keys:
            snapshot[key] = context.get(key)
        self._snapshot = snapshot
        self._last_ts = now

    def stop(self, context) -> None:
        if self._http_server is not None:
            try:
                self._http_server.shutdown()
                self._http_server.server_close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to stop telemetry server: %s", exc)

    def _maybe_start_http(self, settings: dict) -> None:
        http_settings = settings.get("http", {})
        if not http_settings.get("enabled", False):
            return
        host = http_settings.get("host", "0.0.0.0")
        port = int(http_settings.get("port", 8092))

        module = self

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, payload, status=200):
                data = json.dumps(payload, default=str).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/snapshot":
                    self._send_json(module._snapshot)
                    return
                if self.path == "/status":
                    self._send_json({"status": "ok"})
                    return
                if self.path == "/":
                    html = _DASHBOARD_HTML.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(html)))
                    self.end_headers()
                    self.wfile.write(html)
                    return
                self._send_json({"error": "Not found"}, status=404)

            def log_message(self, format, *args):
                return

        try:
            server = ThreadingHTTPServer((host, port), Handler)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to start telemetry server: %s", exc)
            return
        self._http_server = server
        self._http_thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._http_thread.start()
        logger.info("Telemetry dashboard on http://%s:%s/", host, port)


_DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>HoundMind Telemetry</title>
    <style>
      body { font-family: sans-serif; padding: 1rem; }
      pre { background: #111; color: #0f0; padding: 1rem; border-radius: 6px; }
    </style>
  </head>
  <body>
    <h1>HoundMind Telemetry</h1>
    <p>Live snapshot from <code>/snapshot</code></p>
    <pre id="output">Loading...</pre>
    <script>
      async function tick() {
        try {
          const res = await fetch('/snapshot');
          const data = await res.json();
          document.getElementById('output').textContent = JSON.stringify(data, null, 2);
        } catch (e) {
          document.getElementById('output').textContent = 'Error: ' + e;
        }
      }
      setInterval(tick, 500);
      tick();
    </script>
  </body>
</html>
"""
