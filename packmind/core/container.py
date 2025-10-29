from __future__ import annotations
from typing import Any, Dict

from packmind.core.context import AIContext
from packmind.services.energy_service import EnergyService
from packmind.services.emotion_service import EmotionService
from packmind.services.log_service import LogService
from packmind.services.voice_service import VoiceService
from packmind.services.obstacle_service import ObstacleService
from packmind.services.scanning_service import ScanningService
from packmind.services.orientation_service import OrientationService


class ServiceContainer:
    """
    Minimal DI-style container to centralize service construction.
    Keeps a per-context set of service instances.
    """

    def __init__(self, context: AIContext, config: Any | None = None) -> None:
        self._ctx = context
        self._config = config
        self._services: Dict[str, Any] = {}

    def build_defaults(self) -> None:
        # Instantiate core services; adjust parameters as needed
        self._services["energy"] = EnergyService()
        self._services["emotion"] = EmotionService()
        self._services["log"] = LogService()
        self._services["voice"] = VoiceService()
        self._services["obstacle"] = ObstacleService()
        # Use config-derived scanning parameters when available
        head_speed = 90
        samples = 3
        cfg = getattr(self, "_config", None)
        try:
            if cfg is not None:
                head_speed = int(getattr(cfg, "HEAD_SCAN_SPEED", head_speed))
                samples = int(getattr(cfg, "SCAN_SAMPLES", samples))
        except Exception:
            pass
        self._services["scanning"] = ScanningService(self._ctx, head_scan_speed=head_speed, scan_samples=samples)
        # Optional orientation (IMU yaw integration)
        enable_orientation = True
        try:
            if self._config is not None:
                enable_orientation = bool(getattr(self._config, "ENABLE_ORIENTATION_SERVICE", True))
        except Exception:
            pass
        if enable_orientation:
            self._services["orientation"] = OrientationService(self._ctx, self._config)

    def get(self, name: str) -> Any:
        return self._services.get(name)

    def set(self, name: str, service: Any) -> None:
        self._services[name] = service

    # Convenience typed accessors
    def obstacle(self) -> ObstacleService:
        return self._services["obstacle"]

    def scanning(self) -> ScanningService:
        return self._services["scanning"]

    def energy(self) -> EnergyService:
        return self._services["energy"]

    def emotion(self) -> EmotionService:
        return self._services["emotion"]

    def voice(self) -> VoiceService:
        return self._services["voice"]

    def log(self) -> LogService:
        return self._services["log"]

    def orientation(self) -> OrientationService:
        return self._services["orientation"]
