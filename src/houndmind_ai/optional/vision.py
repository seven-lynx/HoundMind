from __future__ import annotations

import logging

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class VisionModule(Module):
    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.available = False

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        try:
            from vilib import Vilib  # type: ignore
        except Exception as exc:  # noqa: BLE001
            self.disable(f"Vision unavailable: {exc}")
            return
        self.available = True
        context.set("vision", {"status": "ready"})
        Vilib.camera_start(vflip=False, hflip=False)
        Vilib.display(local=False, web=True)

    def stop(self, context) -> None:
        if not self.available:
            return
        try:
            from vilib import Vilib  # type: ignore

            Vilib.camera_close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to close camera: %s", exc)
