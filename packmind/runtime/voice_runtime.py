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
import os


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
        # Determine a usable microphone device index
        mic_index: Optional[int] = self.mic_index

        # Allow disabling voice via env (escape hatch)
        if os.getenv("PACKMIND_DISABLE_VOICE", "").strip() in {"1", "true", "yes"}:
            if self.logger:
                self.logger.warning("VoiceRuntime disabled by PACKMIND_DISABLE_VOICE=1")
            self._running = False
            return

        def _autodetect_mic() -> Optional[int]:
            try:
                names = sr.Microphone.list_microphone_names()
                for idx in range(len(names)):
                    try:
                        with sr.Microphone(device_index=idx) as _src:
                            # Open/close to validate; no recording yet
                            pass
                        return idx
                    except Exception:
                        continue
            except Exception:
                return None
            return None

        if mic_index is None:
            mic_index = _autodetect_mic()

        if mic_index is None:
            if self.logger:
                self.logger.warning(
                    "VoiceRuntime disabled: no working microphone device found. "
                    "Run 'I2S audio setup' (installer option 2) and 'Test I2S audio' (option 11), then retry."
                )
            self._running = False
            return

        # Try a brief ambient calibration (best-effort)
        try:
            with sr.Microphone(device_index=mic_index) as source:
                if self.noise_suppression:
                    recognizer.adjust_for_ambient_noise(source, duration=0.5)
                # Map VAD sensitivity (0..1) to an energy threshold range
                base = 100.0
                recognizer.dynamic_energy_threshold = True
                recognizer.energy_threshold = base + (1.0 - self.vad_sensitivity) * 900.0
        except Exception as e:
            if self.logger:
                self.logger.warning(
                    f"VoiceRuntime disabled: failed to initialize microphone (index={mic_index}): {e}"
                )
            self._running = False
            return

        if self.logger:
            cfg = {
                "mic_index": mic_index,
                "timeout_s": self.wake_timeout_s,
                "vad_sensitivity": self.vad_sensitivity,
                "language": self.language,
                "noise_suppression": self.noise_suppression,
                "phrase_time_limit": self.command_timeout_s,
            }
            self.logger.info(f"Listening for wake word: '{self.wake_word}' with {cfg}")

        while self._running:
            try:
                with sr.Microphone(device_index=mic_index) as source:
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
