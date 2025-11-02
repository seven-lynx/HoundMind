# Telemetry Dashboard (P1) — Quick Start
> Author: 7Lynx · Doc Version: 2025.11.01

This is an experimental, opt‑in web dashboard for PackMind. It provides a minimal status page and a WebSocket event stream.

## What you get now
- HTTP: `/health`, `/status`, `/` (simple HTML page)
- WebSocket: `/ws/events` (broadcast)
- A simple built‑in page that connects to the WebSocket and shows events

## Install (optional components)
You need FastAPI and Uvicorn:

```bash
pip install fastapi uvicorn
```

On Raspberry Pi (slow SD cards), consider adding `--no-cache-dir` and a venv.

## Run it
From the repo root:

```bash
python3 tools/run_telemetry.py --host 0.0.0.0 --port 8765
```

Then open a browser to `http://<pi-ip>:8765/`.

- Click “Ping Event” to fetch `/status` and display current server stats.
- The page subscribes to `/ws/events` and prints a heartbeat every ~2s when run standalone.

## Configuration
These keys are in `packmind/packmind_config.py`:

- `TELEMETRY_ENABLED = False`
- `TELEMETRY_HOST = "0.0.0.0"`
- `TELEMETRY_PORT = 8765`
- `TELEMETRY_BASIC_AUTH = None` (reserved; not used yet)

The dashboard is disabled by default. You can run it independently via the tool above. Integration hooks with the orchestrator will be added next.

## Notes and roadmap
- Current build is minimal and safe. When disabled, it adds no overhead.
- Next steps:
  - Orchestrator event hooks (health, scans, face‑lite, audio)
  - Optional basic auth and LAN‑only guard
  - Map snapshot endpoint and lightweight UI improvements
