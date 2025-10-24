from __future__ import annotations
from typing import Optional


class AudioProcessingService:
    """Optional audio processing helpers (VAD/noise).

    Uses webrtcvad if available; otherwise degrades to None/False.
    No audio capture is performed here; this is a pure utility.
    """

    def __init__(self, aggressiveness: int = 2) -> None:
        self._vad = None
        try:
            import webrtcvad  # type: ignore
            self._vad = webrtcvad.Vad(int(aggressiveness))
        except Exception:
            self._vad = None

    def has_vad(self) -> bool:
        return self._vad is not None

    def is_speech(self, pcm16_mono: bytes, sample_rate_hz: int) -> Optional[bool]:
        if self._vad is None:
            return None
        try:
            return bool(self._vad.is_speech(pcm16_mono, sample_rate_hz))
        except Exception:
            return None
