from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)

# `robot_hat.tts` class per backend name. Each is constructed with no arguments and driven with
# `say(text)`; the vendor examples are `examples/tts_*.py` in the robot-hat tree.
_VENDOR_TTS_CLASSES = {
    "piper": "Piper",
    "edge": "EdgeTTS",
    "espeak": "Espeak",
    "pico2wave": "Pico2Wave",
}


class VoiceModule(Module):
    """Voice module with STT (VOSK or SpeechRecognition) and TTS (pidog or pyttsx3).

    Behavior:
    - Listens for microphone input (optional) and/or accepts commands injected into the
      runtime context as `voice_command` / `voice_text`.
    - Maps phrases to actions via `settings.voice_assistant.command_map` and `aliases`.
    - If a recognized utterance is a question and a `voice_question_handler` is present in
      `RuntimeContext`, forwards the question and will TTS the response.

    There is no HTTP server here. The legacy port-8091 `/say` and `/command` endpoints were an
    unauthenticated motion path: they are gone, and a client drives the dog through
    `POST /api/v1/command` like everything else.

    Config (settings.voice_assistant):
    - enabled: bool
    - cooldown_s: float
    - stt.enabled: bool
    - stt.backend: auto|vosk|speech_recognition
    - stt.vosk_model_path: path to VOSK model directory (optional)
    - tts.enabled: bool (false = never speak)
    - tts.backend: auto|pidog|piper|edge|espeak|pico2wave|pyttsx3. The vendor engines
      (`piper`, `edge`, `espeak`, `pico2wave`) speak through the Robot HAT speaker: they are
      `robot_hat.tts` classes, which also switch the amplifier on. `pidog` is kept as the name of that
      vendor path - `Pidog.speak()` plays preset sound *files* by name and cannot speak a sentence
      (#245). `auto` walks the vendor engines and then falls back to `pyttsx3`, while a named backend
      never borrows another engine.
    """

    # The vendor engines, in the order `auto` and `pidog` try them. Each name maps to a
    # `robot_hat.tts` class that is constructed with no arguments and driven with `say(text)`
    # (vendor `examples/tts_piper.py`, `tts_edge.py`, `tts_espeak.py`).
    VENDOR_TTS = ("piper", "edge", "espeak", "pico2wave")

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.available = False
        self._last_command_ts = 0.0
        self._pending: list[dict] = []

        # STT/TTS runtime
        self._stt_thread: threading.Thread | None = None
        self._stt_stop = threading.Event()
        self._tts_engine: Any | None = None
        # One entry per vendor engine name: the instance, or None when it could not be built. Cached
        # so a missing dependency is reported once instead of on every utterance (#245).
        self._vendor_engines: dict[str, Any] = {}

    def start(self, context) -> None:
        if not self.status.enabled:
            return

        # No vendor import here on purpose: the TTS engines are built on first use, so a lite install
        # without `robot_hat` costs one log line rather than a failed start.
        self.available = True
        context.set("voice", {"status": "ready"})

        settings = (context.get("settings") or {}).get("voice_assistant", {})

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
                    self._speak(resp, context)
                else:
                    # default fallback: echo
                    self._speak(f"I heard: {text}", context)
        except Exception:
            logger.exception("Failed handling utterance")

    def _speak(self, text: str, context) -> None:
        """Speak `text` with the engine `settings.voice_assistant.tts` selects.

        `enabled: false` is a no-op. The vendor engines speak through the Robot HAT speaker and turn
        the amplifier on themselves; `pyttsx3` is the local fallback. `auto` tries the vendor engines
        first and then the local one, while a named backend disables every other path - so a missing
        speaker is a dropped answer, not an unexpected local voice (#8).
        """
        settings = (context.get("settings") or {}).get("voice_assistant", {})
        tts_cfg = settings.get("tts", {}) or {}
        if not tts_cfg.get("enabled", True):
            logger.debug("TTS disabled by settings; dropping utterance")
            return

        backend = str(tts_cfg.get("backend", "auto"))
        piper_model = str(tts_cfg.get("piper_model", "") or "")

        for name in self._tts_chain(backend):
            engine = self._vendor_tts(name, piper_model)
            if engine is None:
                continue
            try:
                engine.say(text)
                return
            except Exception:
                logger.exception("TTS backend %s failed to speak", name)
                if backend not in ("auto", "pidog"):
                    # A named backend does not borrow another engine (#8).
                    return

        if backend in ("auto", "pyttsx3"):
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

    def _tts_chain(self, backend: str) -> tuple[str, ...]:
        """The vendor engines to try, in order, for `backend`.

        `auto` and the compatibility name `pidog` both mean the vendor path; any other value names
        one engine. `pyttsx3` is not a vendor engine and therefore yields no names here.
        """
        if backend in ("auto", "pidog"):
            return self.VENDOR_TTS
        if backend in self.VENDOR_TTS:
            return (backend,)
        return ()

    def _vendor_tts(self, name: str, piper_model: str = "") -> Any | None:
        """The vendor engine `name`, built once, or None when it is unavailable.

        `robot_hat.tts` wraps `sunfounder_voice_assistant` and calls `enable_speaker()`, which is what
        raises the Robot HAT amplifier (GPIO 20). A lite install has neither, so the missing case is
        the common one: it is cached and logged at INFO once, not raised per utterance (#245, #246).

        Piper is skipped unless `tts.piper_model` names a model: without one its `say()` raises
        `Model not set`, and `set_model` downloads the weights on first use - not something a tick
        should start by surprise.
        """
        if name in self._vendor_engines:
            return self._vendor_engines[name]
        self._vendor_engines[name] = None
        if name == "piper" and not piper_model:
            logger.info("TTS backend piper skipped: set settings.voice_assistant.tts.piper_model")
            return None
        try:
            import robot_hat.tts as vendor_tts  # type: ignore[import-not-found]

            cls = getattr(vendor_tts, _VENDOR_TTS_CLASSES[name], None)
            if cls is None:
                logger.info("TTS backend %s is not in this robot_hat; skipping", name)
                return None
            engine = cls()
            if name == "piper":
                engine.set_model(piper_model)
        except Exception as exc:
            logger.info("TTS backend %s unavailable: %s", name, exc)
            return None
        self._vendor_engines[name] = engine
        return engine

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
                import pyaudio  # type: ignore
                from vosk import KaldiRecognizer, Model  # type: ignore

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

        # Stop pyttsx3 engine if present
        try:
            if self._tts_engine is not None:
                try:
                    self._tts_engine.stop()
                except Exception:
                    pass
        except Exception:
            pass
