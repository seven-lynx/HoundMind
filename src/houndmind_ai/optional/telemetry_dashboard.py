from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

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

    def get_snapshot_for_trace(self, trace_id: str) -> dict | None:
        """Return the current snapshot if its trace_id matches, otherwise None."""
        if not self._snapshot:
            return None
        if self._snapshot.get("trace_id") == trace_id:
            return self._snapshot
        return None

    def create_support_bundle_for_trace(self, trace_id: str):
        """Create a support bundle zip file for the given trace_id and return its Path.

        This uses the project's `tools/collect_support_bundle.py` helper to produce
        a zip file. The function returns the path to the created zip file or None
        on failure.
        """
        try:
            import tempfile
            from pathlib import Path
            # Import the collect function from tools
            from tools.collect_support_bundle import collect

            tmp = Path(tempfile.mkdtemp()) / f"support_bundle_{trace_id}.zip"
            # Set env var so the collector records the trace id
            import os

            old = os.environ.get("HOUNDMIND_TRACE_ID")
            os.environ["HOUNDMIND_TRACE_ID"] = str(trace_id)
            try:
                collect(tmp)
            finally:
                if old is None:
                    os.environ.pop("HOUNDMIND_TRACE_ID", None)
                else:
                    os.environ["HOUNDMIND_TRACE_ID"] = old
            if tmp.exists():
                return tmp
        except Exception:
            logger.exception("Failed to create support bundle for trace %s", trace_id)
        return None

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
        # Surface trace_id at the top-level of the snapshot for correlation.
        snapshot["trace_id"] = context.get("trace_id")
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
        # Configurable camera path for embedding a stream or single-frame URL
        self._camera_path = http_settings.get("camera_path", "/camera")

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
                if self.path.startswith("/snapshot"):
                    # Allow filtering by trace id via header or query parameter
                    parsed = urlparse(self.path)
                    params = parse_qs(parsed.query)
                    header_trace = self.headers.get("X-Trace-Id")
                    query_trace = params.get("trace_id", [None])[0]
                    req_trace = header_trace or query_trace
                    if req_trace:
                        snap = module.get_snapshot_for_trace(req_trace)
                        if snap is None:
                            self._send_json({"error": "not found"}, status=404)
                            return
                        self._send_json(snap)
                        return
                    self._send_json(module._snapshot)
                    return
                if self.path == "/download_slam_map":
                    data = module._snapshot.get("slam_map_data")
                    if data is None:
                        self._send_json({"error": "no map data"}, status=404)
                        return
                    # Serve as JSON
                    self.send_response(200)
                    payload = json.dumps({"map": data}, default=str).encode("utf-8")
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if self.path.startswith("/download_support_bundle"):
                    # Accept trace_id via header or query
                    parsed = urlparse(self.path)
                    params = parse_qs(parsed.query)
                    header_trace = self.headers.get("X-Trace-Id")
                    query_trace = params.get("trace_id", [None])[0]
                    req_trace = header_trace or query_trace or module._snapshot.get("trace_id")
                    if not req_trace:
                        self._send_json({"error": "trace_id required"}, status=400)
                        return
                    zip_path = module.create_support_bundle_for_trace(req_trace)
                    if not zip_path:
                        self._send_json({"error": "failed to create bundle"}, status=500)
                        return
                    try:
                        with open(zip_path, "rb") as fh:
                            data = fh.read()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/zip")
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                    except Exception as exc:  # noqa: BLE001
                        self._send_json({"error": str(exc)}, status=500)
                    return
                if self.path == "/download_slam_trajectory":
                    data = module._snapshot.get("slam_trajectory")
                    if data is None:
                        self._send_json({"error": "no trajectory"}, status=404)
                        return
                    self.send_response(200)
                    payload = json.dumps({"trajectory": data}, default=str).encode("utf-8")
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if self.path == "/status":
                    self._send_json({"status": "ok"})
                    return
                if self.path == "/":
                    # Inject configured camera path into the dashboard HTML
                    html = _DASHBOARD_HTML.replace(
                        "{{CAMERA_PATH}}", str(getattr(module, "_camera_path", "/camera"))
                    ).encode("utf-8")
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
        <meta name="viewport" content="width=device-width,initial-scale=1" />
        <title>HoundMind Telemetry</title>
        <style>
            :root{--bg:#0f1720;--card:#0b1220;--muted:#9aa6b2;--accent:#38bdf8}
            html,body{height:100%;margin:0}
            body{font-family:system-ui,-apple-system,Segoe UI,Roboto;display:flex;flex-direction:column;gap:0.75rem;padding:0.75rem;background:linear-gradient(180deg,#071026, #05101a);color:#e6eef6}
            header{display:flex;align-items:center;justify-content:space-between}
            h1{font-size:1.1rem;margin:0}
            .container{display:flex;flex:1;gap:0.75rem;flex-direction:column}
            .camera{background:var(--card);border-radius:8px;padding:0.25rem;display:flex;align-items:center;justify-content:center}
            #camera{width:100%;height:auto;max-height:60vh;border-radius:6px;background:#000}
            .panels{display:flex;gap:0.75rem;flex-direction:column}
            .card{background:var(--card);padding:0.5rem;border-radius:8px;overflow:auto}
            pre{background:#071018;color:#dff3ff;padding:0.5rem;border-radius:6px;white-space:pre-wrap}
            .row{display:flex;gap:0.75rem;flex-wrap:wrap}
            @media(min-width:900px){.container{flex-direction:row}.panels{flex:1}.camera{flex:1}}
            .meta{color:var(--muted);font-size:0.85rem}
            .controls{display:flex;gap:0.5rem}
            button{background:var(--accent);color:#042028;border:0;padding:0.4rem 0.6rem;border-radius:6px}
        </style>
    </head>
    <body>
        <header>
            <h1>HoundMind Telemetry</h1>
                <div style="display:flex;gap:0.5rem;align-items:center">
                <div class="meta">Live: <span id="vision_fps">-</span> FPS</div>
                <div class="meta">Trace: <span id="trace_id">-</span></div>
                <button id="copy_trace" style="background:transparent;border:1px solid #274454;color:var(--accent);padding:0.15rem 0.4rem;border-radius:6px">Copy</button>
                <button id="download_bundle" style="background:transparent;border:1px solid #274454;color:var(--accent);padding:0.15rem 0.4rem;border-radius:6px">Download Bundle</button>
            </div>
        </header>
        <div class="container">
            <div class="camera card">
                <img id="camera" src="{{CAMERA_PATH}}" alt="camera"/>
            </div>
            <div class="panels">
                <div class="card">
                    <div class="row">
                        <div style="flex:1">
                            <strong>Snapshot</strong>
                            <div class="meta">Updates every 0.5s</div>
                        </div>
                        <div class="controls">
                            <button id="refresh">Refresh</button>
                        </div>
                    </div>
                    <pre id="output">Loading...</pre>
                </div>
                <div class="card">
                        <strong>Quick Stats</strong>
                        <div id="quick" class="meta">—</div>
                    </div>
                    <div class="card">
                        <strong>SLAM</strong>
                        <div class="meta">Map / Trajectory</div>
                        <div style="margin-top:0.5rem">
                            <button id="download_map">Download Map</button>
                            <button id="download_traj">Download Trajectory</button>
                        </div>
                        <pre id="slam">No SLAM data</pre>
                </div>
            </div>
        </div>
        <script>
            const camera = document.getElementById('camera');
            const out = document.getElementById('output');
            const quick = document.getElementById('quick');
            const fpsLabel = document.getElementById('vision_fps');
            const refresh = document.getElementById('refresh');
            let last = 0;
            async function tick(){
                try{
                    const res = await fetch('/snapshot');
                    const data = await res.json();
                    out.textContent = JSON.stringify(data, null, 2);
                    // expose trace id in header for quick copying
                    const traceEl = document.getElementById('trace_id');
                    traceEl.textContent = data.trace_id || '-';
                    const perf = data.performance_telemetry || {};
                    fpsLabel.textContent = perf.vision_fps ? perf.vision_fps.toFixed(1) : '-';
                    quick.textContent = `tick ${perf.tick_hz_actual || '-'} • mem ${perf.mem_used_pct || '-'}%`;
                    const slamEl = document.getElementById('slam');
                    if(data.slam_map_data || data.slam_trajectory){
                        slamEl.textContent = JSON.stringify({map: data.slam_map_data, trajectory: data.slam_trajectory}, null, 2);
                    } else {
                        slamEl.textContent = 'No SLAM data';
                    }
                }catch(e){ out.textContent = 'Error: '+e }
            }
            // Avoid caching single-frame camera endpoints by adding a timestamp
            function reloadCamera(){
                const base = camera.getAttribute('src').split('?')[0];
                camera.src = base + '?ts=' + Date.now();
            }
            refresh.addEventListener('click', ()=>{ tick(); reloadCamera(); });
            document.getElementById('copy_trace').addEventListener('click', ()=>{
                const txt = document.getElementById('trace_id').textContent || '';
                if(!txt || txt === '-') return; try{ navigator.clipboard.writeText(txt); alert('Trace id copied') }catch(e){ alert('Copy failed') }
            });

            document.getElementById('download_bundle').addEventListener('click', async ()=>{
                const txt = document.getElementById('trace_id').textContent || '';
                if(!txt || txt === '-') { alert('No trace id available'); return }
                try{
                    const res = await fetch('/download_support_bundle?trace_id=' + encodeURIComponent(txt));
                    if(!res.ok){
                        const err = await res.json().catch(()=>null);
                        alert('Failed to create bundle: ' + (err && err.error ? err.error : res.statusText));
                        return
                    }
                    const blob = await res.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `support_bundle_${txt}.zip`;
                    a.click();
                    URL.revokeObjectURL(url);
                }catch(e){ alert('Download failed: '+e) }
            });
            document.getElementById('download_map').addEventListener('click', async ()=>{
                const res = await fetch('/download_slam_map');
                if(res.ok){
                    const blob = await res.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url; a.download = 'slam_map.json'; a.click();
                } else { alert('No map data') }
            });
            document.getElementById('download_traj').addEventListener('click', async ()=>{
                const res = await fetch('/download_slam_trajectory');
                if(res.ok){
                    const blob = await res.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url; a.download = 'slam_trajectory.json'; a.click();
                } else { alert('No trajectory') }
            });
            setInterval(()=>{ tick(); reloadCamera(); }, 500);
            tick();
        </script>
    </body>
</html>
"""
