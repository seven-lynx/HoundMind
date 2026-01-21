from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from typing import Any

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class VoiceModule(Module):
    """Voice module with STT (VOSK or SpeechRecognition) and TTS (pidog or pyttsx3).

    Behavior:
    - Listens for microphone input (optional) and/or accepts HTTP commands (`/say`, `/command`).
    - Maps phrases to actions via `settings.voice_assistant.command_map` and `aliases`.
    - If a recognized utterance is a question and a `voice_question_handler` is present in
      `RuntimeContext`, forwards the question and will TTS the response.
    Config (settings.voice_assistant):
    - enabled: bool
    - cooldown_s: float
    - http.enabled/host/port
    - stt.enabled: bool
    - stt.backend: auto|vosk|speech_recognition
    - stt.vosk_model_path: path to VOSK model directory (optional)
    - tts.enabled: bool
    - tts.backend: auto|pyttsx3|pidog
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.available = False
        self._last_command_ts = 0.0
        self._http_server: ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._pending: list[dict] = []

        # STT/TTS runtime
        self._stt_thread: threading.Thread | None = None
        self._stt_stop = threading.Event()
        self._tts_engine: Any | None = None
        self._pidog: Any | None = None

    def start(self, context) -> None:
        if not self.status.enabled:
            return

        # pidog is optional; if present it may provide robot TTS and other helpers
        try:
            import pidog  # type: ignore[import-not-found]

            self._pidog = pidog
        except Exception:
            self._pidog = None

        self.available = True
        context.set("voice", {"status": "ready"})

        settings = (context.get("settings") or {}).get("voice_assistant", {})

        # Start HTTP control surface if enabled
        try:
            self._maybe_start_http(settings)
        except Exception:
            logger.exception("Failed to start voice HTTP server")

        # Start STT listener if requested
        stt_cfg = settings.get("stt", {})
        if stt_cfg.get("enabled", False):
            self._stt_thread = threading.Thread(
                target=self._stt_loop, args=(context,), daemon=True
            )
            self._stt_thread.start()

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

        # Handle explicit command injected via context
        command = context.get("voice_command")
        if isinstance(command, dict):
            action = command.get("action") or command.get("pidog_action")
            if action:
                self._apply_action(str(action), context)
                context.set("voice_command", None)
                self._last_command_ts = now
                return None

        mapping = settings.get("command_map", {})
        aliases = settings.get("aliases", {})

        # Drain pending HTTP/recognition items
        if self._pending:
            for item in list(self._pending):
                if "action" in item:
                    self._apply_action(str(item["action"]), context)
                    self._last_command_ts = now
                elif "text" in item:
                    text = str(item["text"])
                    normalized = self._normalize(text)
                    action = self._resolve_action(normalized, mapping, aliases)
                    if action:
                        self._apply_action(action, context)
                    else:
                        # Treat as question if ends with ? or if configured
                        self._handle_utterance(text, context)
                    self._last_command_ts = now
                self._pending.remove(item)

        # Also handle direct `voice_text` in context (other components may set it)
        text = context.get("voice_text")
        if isinstance(text, str) and text.strip():
            normalized = self._normalize(text)
            action = self._resolve_action(normalized, mapping, aliases)
            if action:
                self._apply_action(action, context)
            else:
                self._handle_utterance(text, context)
            context.set("voice_text", None)
            self._last_command_ts = now

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

    def _handle_utterance(self, text: str, context) -> None:
        # If a question handler exists in context, call it and speak the response.
        handler = context.get("voice_question_handler")
        try:
            # If it's a question (ends with ?) or handler is present, forward
            if (isinstance(text, str) and text.strip().endswith("?")) or callable(handler):
                if callable(handler):
                    try:
                        resp = handler(text)
                    except Exception:
                        logger.exception("voice_question_handler failed")
                        resp = None
                else:
                    resp = None
                if isinstance(resp, str) and resp.strip():
                    self._speak(resp)
                else:
                    # default fallback: echo
                    self._speak(f"I heard: {text}")
        except Exception:
            logger.exception("Failed handling utterance")

    def _speak(self, text: str) -> None:
        # Try pidog speak first
        try:
            if self._pidog is not None and hasattr(self._pidog, "speak"):
                try:
                    self._pidog.speak(text)
                    return
                except Exception:
                    logger.exception("pidog.speak failed")
        except Exception:
            logger.exception("pidog TTS check failed")

        # Try pyttsx3
        try:
            if self._tts_engine is None:
                import pyttsx3

                self._tts_engine = pyttsx3.init()
            self._tts_engine.say(text)
            self._tts_engine.runAndWait()
            return
        except Exception:
            logger.exception("pyttsx3 TTS failed")

        logger.info("TTS not available to speak: %s", text)

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

    def _stt_loop(self, context) -> None:
        """Background STT loop. Supports VOSK if available, otherwise SpeechRecognition.

        Recognized text is appended to self._pending as {'text': ...} so the main
        tick loop handles mapping and action invocation.
        """
        settings = (context.get("settings") or {}).get("voice_assistant", {})
        stt_cfg = settings.get("stt", {})
        backend = stt_cfg.get("backend", "speech_recognition")

        # Prefer SpeechRecognition (network or local via installed engines)
        if backend in ("auto", "speech_recognition", "speech-recognition"):
            try:
                import speech_recognition as sr  # type: ignore

                r = sr.Recognizer()
                mic = sr.Microphone()
                with mic as source:
                    r.adjust_for_ambient_noise(source, duration=1)
                logger.info("SpeechRecognition STT started (using default recognizer)")
                while not self._stt_stop.is_set():
                    try:
                        with mic as source:
                            audio = r.listen(source, phrase_time_limit=5)
                        try:
                            text = r.recognize_google(audio)
                        except sr.RequestError:
                            logger.exception("SpeechRecognition service error")
                            continue
                        except sr.UnknownValueError:
                            continue
                        if text:
                            self._pending.append({"text": text})
                    except Exception:
                        logger.exception("STT listen error")
                        time.sleep(0.5)
                return
            except Exception:
                logger.debug("SpeechRecognition not available or failed to initialize")

        # Fallback to VOSK if configured or available
        if backend in ("auto", "vosk"):
            try:
                from vosk import Model, KaldiRecognizer  # type: ignore
                import pyaudio  # type: ignore

                model_path = stt_cfg.get("vosk_model_path")
                if model_path:
                    try:
                        model = Model(model_path)
                        pa = pyaudio.PyAudio()
                        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=8000)
                        stream.start_stream()
                        rec = KaldiRecognizer(model, 16000)
                        logger.info("VOSK STT started")
                        while not self._stt_stop.is_set():
                            data = stream.read(4000, exception_on_overflow=False)
                            if len(data) == 0:
                                continue
                            if rec.AcceptWaveform(data):
                                res = rec.Result()
                                try:
                                    j = json.loads(res)
                                    text = j.get("text", "").strip()
                                except Exception:
                                    text = ""
                                if text:
                                    self._pending.append({"text": text})
                            else:
                                pass
                        try:
                            stream.stop_stream()
                            stream.close()
                            pa.terminate()
                        except Exception:
                            pass
                        return
                    except Exception:
                        logger.exception("VOSK model init failed")
                else:
                    logger.info("VOSK backend requested but no model path provided")
            except Exception:
                logger.debug("VOSK not available or failed to import")

        logger.info("No STT backend available; STT loop exiting")

    def stop(self, context) -> None:
        # Stop STT thread
        try:
            if self._stt_thread is not None:
                self._stt_stop.set()
                self._stt_thread.join(timeout=1)
        except Exception:
            logger.exception("Failed to stop STT thread")

        if self._http_server is not None:
            try:
                self._http_server.shutdown()
                self._http_server.server_close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to stop voice HTTP server: %s", exc)

        # Stop pyttsx3 engine if present
        try:
            if self._tts_engine is not None:
                try:
                    self._tts_engine.stop()
                except Exception:
                    pass
        except Exception:
            pass
