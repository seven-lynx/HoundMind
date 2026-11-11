from __future__ import annotations

import logging
import time
from typing import Any

from houndmind_ai.core.module import Module
from houndmind_ai.optional.vision_inference_scheduler import VisionInferenceScheduler
from houndmind_ai.optional.vision_preprocessing import VisionPreprocessor

logger = logging.getLogger(__name__)


class VisionPi4Module(Module):
    """Pi4-focused vision feed.

    Publishes two context keys per frame: `vision_frame` (the raw array, which
    `face_recognition`, `semantic_labeler` and `slam_pi4` read) and `vision_frame_jpeg`
    (the encoded bytes the control plane's `/api/v1/camera/*` routes serve). Supports
    Picamera2 if available, otherwise falls back to OpenCV VideoCapture.

    There is no HTTP server here. The legacy per-client MJPEG loop on port 8090 is gone;
    frames go to `services/camera.py`, which fans one producer out to N clients behind the
    API token.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.available = False
        self._camera: Any | None = None
        self._cv2: Any | None = None
        self._capture: Any | None = None
        self._last_frame_ts = 0.0

        self._preprocessor: VisionPreprocessor | None = None
        self._inference_scheduler: VisionInferenceScheduler | None = None
        self._last_inference_result = None

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        settings = (context.get("settings") or {}).get("vision_pi4", {})
        backend = settings.get("backend", "picamera2")

        # `cv2` is needed by the OpenCV backend and, for *every* backend, by the JPEG encode
        # that feeds `/api/v1/camera/*`. A missing wheel costs the still image, not the frames.
        try:
            import cv2  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenCV unavailable; camera frames will not be served: %s", exc)
        else:
            self._cv2 = cv2

        # Setup preprocessor and inference scheduler if enabled
        self._preprocessor = VisionPreprocessor(settings.get("preprocessing", {}))
        if settings.get("inference_scheduler_enabled", True):
            def _on_inference_result(result):
                self._last_inference_result = result
                context.set("vision_inference_result", result)
            # Dummy inference function, replace with actual model
            def _dummy_inference(frame):
                time.sleep(0.05)
                return {"frame_id": id(frame), "result": "ok"}
            self._inference_scheduler = VisionInferenceScheduler(
                _dummy_inference, result_callback=_on_inference_result
            )
            assert self._inference_scheduler is not None
            self._inference_scheduler.start()

        if backend == "picamera2":
            try:
                from picamera2 import Picamera2  # type: ignore
            except Exception as exc:  # noqa: BLE001
                logger.warning("Picamera2 unavailable: %s", exc)
            else:
                try:
                    cam = Picamera2()
                    config = cam.create_preview_configuration()
                    cam.configure(config)
                    cam.start()
                    self._camera = cam
                    self.available = True
                    context.set(
                        "vision_status", {"status": "ready", "backend": backend}
                    )
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Picamera2 init failed: %s", exc)

        cv2 = self._cv2
        if cv2 is None:
            self.disable("Vision backend unavailable: OpenCV is not installed")
            return

        device_index = int(settings.get("device_index", 0))
        capture = cv2.VideoCapture(device_index)
        if not capture.isOpened():
            self.disable("Failed to open camera device")
            return

        self._capture = capture
        self.available = True
        context.set("vision_status", {"status": "ready", "backend": "opencv"})

    def tick(self, context) -> None:
        if not self.available or not self.status.enabled:
            return

        settings = (context.get("settings") or {}).get("vision_pi4", {})
        if not settings.get("enabled", True):
            return

        override_interval = context.get("vision_frame_interval_override_s")
        if isinstance(override_interval, (int, float)):
            frame_interval = float(override_interval)
        else:
            frame_interval = float(settings.get("frame_interval_s", 0.2))
        now = time.time()
        if now - self._last_frame_ts < frame_interval:
            return

        frame = None
        if self._camera is not None:
            try:
                frame = self._camera.capture_array()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Picamera2 capture failed: %s", exc)
        elif self._capture is not None:
            ok, frame = self._capture.read()
            if not ok:
                frame = None

        if frame is not None:
            context.set("vision_frame", frame)
            context.set("vision_frame_ts", now)
            self._last_frame_ts = now
            self._publish_jpeg(frame, context)
            # Preprocess and schedule inference if enabled
            if self._preprocessor and self._inference_scheduler:
                try:
                    processed = self._preprocessor.process(frame)
                    self._inference_scheduler.submit_frame(processed)
                except Exception as exc:
                    logger.warning("Vision preprocessing/inference failed: %s", exc)

    def _publish_jpeg(self, frame, context) -> None:
        """Encode the frame once and publish it for `services/camera.py`.

        `vision_frame` stays the raw array: `face_recognition`, `semantic_labeler` and
        `slam_pi4` all read it, and making them decode a JPEG would cost more than this
        encode does. The retired port-8090 handler encoded once per *client*; this encodes
        once per frame, which is cheaper for one viewer and bounded for many.
        """
        cv2 = self._cv2
        if cv2 is None:
            return
        try:
            ok, buffer = cv2.imencode(".jpg", frame)
        except Exception as exc:  # noqa: BLE001
            logger.debug("JPEG encode failed: %s", exc)
            return
        if ok:
            context.set("vision_frame_jpeg", buffer.tobytes())

    def stop(self, context) -> None:
        if self._camera is not None:
            try:
                self._camera.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Picamera2 stop failed: %s", exc)
        if self._capture is not None:
            try:
                self._capture.release()
            except Exception as exc:  # noqa: BLE001
                logger.warning("VideoCapture release failed: %s", exc)
        if self._inference_scheduler:
            self._inference_scheduler.stop()
            self._inference_scheduler = None
