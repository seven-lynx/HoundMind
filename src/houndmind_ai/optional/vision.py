from __future__ import annotations

import logging
import time

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class VisionModule(Module):
    """The `modules.vision` camera path: Vilib owns the camera, and this republishes its frame.

    `optional/vision_pi4.py` is the frame producer on a Pi 4/5; this is the same contract for the
    Pi 3 path, so `face_recognition`, `semantic_labeler` and `perception.occupancy` do not have to
    care which one is running (#98). A viewfinder that published no `vision_frame` reported `ready`
    while every consumer behind it read `None` for the life of the run.

    `Vilib.img` is the newest frame its own capture thread holds — SunFounder's examples crop and
    save it directly - so reading it costs no capture of ours. This module is a guest in that
    camera: it never starts a second one and never closes a camera it did not open.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.available = False
        self._last_frame: object | None = None
        self._warned_no_frames = False

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        try:
            from vilib import Vilib  # type: ignore
        except Exception as exc:  # noqa: BLE001
            self.disable(f"Vision unavailable: {exc}")
            return
        self.available = True
        Vilib.camera_start(vflip=False, hflip=False)
        # No stream and no preview (#15). `web=True` asks Vilib to serve the camera on its own
        # port, outside this repo's token gate, its audit trail and its interlock - a fifth
        # listener that a grep for `BaseHTTPRequestHandler` cannot see because it lives in the
        # vendor package. The port had no consumer here either: this module republishes
        # `Vilib.img` as `vision_frame`, which is what `services/camera.py` reads. `local=True`
        # is not the alternative: a preview window needs a display a headless runtime does not
        # have, and the capture thread `camera_start` owns does not depend on it.
        Vilib.display(local=False, web=False)
        # `vision_status` is the key the programming guide documents for a camera module. `frames`
        # says whether this build can feed a detector at all, which is the part a consumer needs:
        # `vision_frame` is published from `tick`.
        context.set(
            "vision_status",
            {"status": "ready", "backend": "vilib", "frames": hasattr(Vilib, "img")},
        )

    def tick(self, context) -> None:
        """Publish the newest frame, once per frame rather than once per tick.

        `vision_frame_ts` only moves when the array does. That is what lets occupancy age a frozen
        camera: a timestamp refreshed on every tick would make a dead frame look live, which is the
        one reading `perception.occupancy` must never be given (P4 PL4). The contract is
        `vision_pi4.py`'s — same two keys, same clock, so no consumer can tell the paths apart.
        """
        if not self.available or not self.status.enabled:
            return
        try:
            from vilib import Vilib  # type: ignore
        except Exception:  # noqa: BLE001
            return
        frame = getattr(Vilib, "img", None)
        if frame is None:
            if not self._warned_no_frames:
                self._warned_no_frames = True
                reason = "vilib exposes no frame; sensors behind vision_frame will stay blind"
                logger.warning("Vision is a viewfinder only: %s", reason)
                context.set(
                    "vision_status",
                    {"status": "ready", "backend": "vilib", "frames": False, "reason": reason},
                )
            return
        if frame is self._last_frame:
            return
        self._last_frame = frame
        context.set("vision_frame", frame)
        context.set("vision_frame_ts", time.time())

    def stop(self, context) -> None:
        if not self.available:
            return
        try:
            from vilib import Vilib  # type: ignore

            Vilib.camera_close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to close camera: %s", exc)
