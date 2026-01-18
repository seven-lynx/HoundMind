from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class VoiceModule(Module):
    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.available = False
        self._last_command_ts = 0.0
        self._http_server: ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._pending: list[dict] = []

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        try:
            import pidog  # type: ignore[import-not-found]  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            self.disable(f"Voice unavailable: {exc}")
            return
        self.available = True
        context.set("voice", {"status": "ready"})
        self._maybe_start_http(
            (context.get("settings") or {}).get("voice_assistant", {})
        )

    def tick(self, context) -> None:
        if not self.available or not self.status.enabled:
            return None

        settings = (context.get("settings") or {}).get("voice_assistant", {})
        if not settings.get("enabled", True):
            return None

        now = time.time()
        cooldown = float(settings.get("cooldown_s", 1.0))
        if now - self._last_command_ts < cooldown:
            return None

        command = context.get("voice_command")
        if isinstance(command, dict):
            action = command.get("action") or command.get("pidog_action")
            if action:
                self._apply_action(str(action), context)
                context.set("voice_command", None)
                self._last_command_ts = now
                return None

        if self._pending:
            for item in list(self._pending):
                if "action" in item:
                    self._apply_action(str(item["action"]), context)
                    self._last_command_ts = now
                elif "text" in item:
                    action = self._resolve_action(
                        self._normalize(str(item["text"])), mapping, aliases
                    )
                    if action:
                        self._apply_action(action, context)
                        self._last_command_ts = now
                self._pending.remove(item)

        text = context.get("voice_text")
        if not isinstance(text, str) or not text.strip():
            return None

        normalized = self._normalize(text)
        mapping = settings.get("command_map", {})
        aliases = settings.get("aliases", {})

        action = self._resolve_action(normalized, mapping, aliases)
        if action:
            self._apply_action(action, context)
            context.set("voice_text", None)
            self._last_command_ts = now
            return None
        return None

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().strip().split())

    def _resolve_action(self, text: str, mapping: dict, aliases: dict) -> str | None:
        if text in mapping:
            return str(mapping[text])
        if text in aliases:
            alias = aliases[text]
            if isinstance(alias, str) and alias in mapping:
                return str(mapping[alias])
            if isinstance(alias, str):
                return alias
        for key, value in mapping.items():
            if key in text:
                return str(value)
        return None

    def _apply_action(self, action: str, context) -> None:
        # Use behavior override so safety/navigation still take priority.
        context.set("behavior_override", action)
        logger.info("Voice command -> %s", action)

    def _maybe_start_http(self, settings: dict) -> None:
        http_settings = settings.get("http", {})
        if not http_settings.get("enabled", False):
            return
        host = http_settings.get("host", "0.0.0.0")
        port = int(http_settings.get("port", 8091))

        module = self

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, payload, status=200):
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/status":
                    self._send_json({"status": "ok"})
                    return
                if parsed.path == "/say":
                    qs = parse_qs(parsed.query)
                    text = (qs.get("text") or [None])[0]
                    if not text:
                        self._send_json({"error": "Missing text"}, status=400)
                        return
                    module._pending.append({"text": text})
                    self._send_json({"status": "queued", "text": text})
                    return
                if parsed.path == "/command":
                    qs = parse_qs(parsed.query)
                    action = (qs.get("action") or [None])[0]
                    if not action:
                        self._send_json({"error": "Missing action"}, status=400)
                        return
                    module._pending.append({"action": action})
                    self._send_json({"status": "queued", "action": action})
                    return
                self._send_json({"error": "Not found"}, status=404)

            def do_POST(self):
                parsed = urlparse(self.path)
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
                if parsed.path in ("/say", "/command"):
                    try:
                        payload = json.loads(body) if body else {}
                    except Exception:
                        payload = {}
                    if parsed.path == "/say":
                        text = payload.get("text")
                        if not text:
                            self._send_json({"error": "Missing text"}, status=400)
                            return
                        module._pending.append({"text": text})
                        self._send_json({"status": "queued", "text": text})
                        return
                    action = payload.get("action")
                    if not action:
                        self._send_json({"error": "Missing action"}, status=400)
                        return
                    module._pending.append({"action": action})
                    self._send_json({"status": "queued", "action": action})
                    return
                self._send_json({"error": "Not found"}, status=404)

            def log_message(self, format, *args):
                return

        try:
            server = ThreadingHTTPServer((host, port), Handler)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to start voice HTTP server: %s", exc)
            return
        self._http_server = server
        self._http_thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._http_thread.start()
        logger.info("Voice HTTP server listening on %s:%s", host, port)

    def stop(self, context) -> None:
        if self._http_server is not None:
            try:
                self._http_server.shutdown()
                self._http_server.server_close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to stop voice HTTP server: %s", exc)
