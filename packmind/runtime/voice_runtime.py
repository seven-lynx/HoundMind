"""
VoiceRuntime: background wake-word + command loop.

- Defers ASR imports until runtime to keep PackMind import-safe on PCs.
- Provides simple start()/stop() lifecycle and logs through optional logger.
- Delegates command handling to an Orchestrator-provided callback.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional, Any


class VoiceRuntime:
    """Runs the microphone loop and calls a handler when the wake word is heard."""

    def __init__(
        self,
        voice_service: Any,
        wake_word: str,
        on_command: Callable[[str], None],
        mic_index: Optional[int] = None,
        wake_timeout_s: float = 5.0,
        vad_sensitivity: float = 0.5,
        language: str = "en-US",
        noise_suppression: bool = True,
        command_timeout_s: float = 5.0,
        logger: Optional[Any] = None,
    ) -> None:
        self.voice_service = voice_service
        self.wake_word = (wake_word or "pidog").lower()
        self.on_command = on_command
        self.mic_index = mic_index
        self.wake_timeout_s = float(wake_timeout_s)
        self.vad_sensitivity = max(0.0, min(1.0, float(vad_sensitivity)))
        self.language = language or "en-US"
        self.noise_suppression = bool(noise_suppression)
        self.command_timeout_s = float(command_timeout_s)
        self.logger = logger
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="VoiceRuntime", daemon=True)
        self._thread.start()
        if self.logger:
            self.logger.info(f"VoiceRuntime started (wake word: '{self.wake_word}')")

    def stop(self, timeout: float = 2.0) -> None:
        self._running = False
        t = self._thread
        if t is not None:
            t.join(timeout)
        if self.logger:
            self.logger.info("VoiceRuntime stopped")

    def _loop(self) -> None:
        # Import lazily so PackMind can import without sr installed
        try:
            import speech_recognition as sr  # type: ignore
        except Exception as e:  # pragma: no cover - environment dependent
            if self.logger:
                self.logger.warning(f"VoiceRuntime disabled (no ASR): {e}")
            self._running = False
            return

        recognizer = sr.Recognizer()
        microphone = sr.Microphone(device_index=self.mic_index) if self.mic_index is not None else sr.Microphone()
        with microphone as source:
            try:
                if self.noise_suppression:
                    recognizer.adjust_for_ambient_noise(source, duration=0.5)
                # Map VAD sensitivity (0..1) to an energy threshold range
                base = 100.0
                recognizer.dynamic_energy_threshold = True
                recognizer.energy_threshold = base + (1.0 - self.vad_sensitivity) * 900.0
            except Exception:
                pass

        if self.logger:
            cfg = {
                "mic_index": self.mic_index,
                "timeout_s": self.wake_timeout_s,
                "vad_sensitivity": self.vad_sensitivity,
                "language": self.language,
                "noise_suppression": self.noise_suppression,
                "phrase_time_limit": self.command_timeout_s,
            }
            self.logger.info(f"Listening for wake word: '{self.wake_word}' with {cfg}")

        while self._running:
            try:
                with (sr.Microphone(device_index=self.mic_index) if self.mic_index is not None else sr.Microphone()) as source:
                    audio = recognizer.listen(source, timeout=self.wake_timeout_s, phrase_time_limit=self.command_timeout_s)
                text = recognizer.recognize_google(audio, language=self.language).lower()
                if self.wake_word in text:
                    if self.logger:
                        self.logger.debug(f"Wake word heard: {text}")
                    # Delegate to orchestrator
                    self.on_command(text)
            except sr.WaitTimeoutError:
                pass
            except Exception as e:  # pragma: no cover
                if self.logger:
                    self.logger.debug(f"VoiceRuntime error: {e}")
            time.sleep(0.1)
