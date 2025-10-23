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
        logger: Optional[Any] = None,
    ) -> None:
        self.voice_service = voice_service
        self.wake_word = (wake_word or "pidog").lower()
        self.on_command = on_command
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
        microphone = sr.Microphone()
        with microphone as source:
            try:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
            except Exception:
                pass

        if self.logger:
            self.logger.info(f"Listening for wake word: '{self.wake_word}'")

        while self._running:
            try:
                with sr.Microphone() as source:
                    audio = recognizer.listen(source, timeout=3, phrase_time_limit=4)
                text = recognizer.recognize_google(audio).lower()
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
