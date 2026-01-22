from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class SemanticLabelerModule(Module):
    """Pi4 semantic object labeling module.

    Backends:
    - "stub": publishes labels from `vision_objects_raw` if provided.
    - "opencv_dnn": uses OpenCV DNN for object detection with a provided model.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.available = False
        self.backend = "stub"
        self._cv2: Any | None = None
        self._net: Any | None = None
        self._labels: list[str] = []
        self._repo_root = Path(__file__).resolve().parents[3]
        self._last_ts = 0.0

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        settings = (context.get("settings") or {}).get("semantic_labeler", {})
        self.backend = settings.get("backend", "stub")

        if self.backend == "stub":
            self.available = True
            context.set("semantic_status", {"status": "ready", "backend": self.backend})
            return

        if self.backend == "opencv_dnn":
            try:
                import cv2  # type: ignore
            except Exception as exc:  # noqa: BLE001
                self.disable(f"OpenCV DNN backend unavailable: {exc}")
                return

            model_path = self._resolve_path(settings.get("model_path", ""))
            config_path = self._resolve_path(settings.get("config_path", ""))
            labels_path = self._resolve_path(settings.get("labels_path", ""))

            if not model_path.exists() or not config_path.exists():
                self.disable(
                    "OpenCV DNN model/config not found; set model_path/config_path"
                )
                return

            try:
                net = cv2.dnn.readNetFromTensorflow(str(model_path), str(config_path))
            except Exception as exc:  # noqa: BLE001
                self.disable(f"Failed to load DNN model: {exc}")
                return

            self._cv2 = cv2
            self._net = net
            if labels_path.exists():
                self._labels = [
                    line.strip()
                    for line in labels_path.read_text(encoding="utf-8").splitlines()
                ]

            self.available = True
            context.set("semantic_status", {"status": "ready", "backend": self.backend})
            return

        self.disable(f"Unknown semantic backend: {self.backend}")

    def tick(self, context) -> None:
        if not self.available or not self.status.enabled:
            return
        settings = (context.get("settings") or {}).get("semantic_labeler", {})
        if not settings.get("enabled", True):
            return

        interval = float(settings.get("interval_s", 0.5))
        now = time.time()
        if now - self._last_ts < interval:
            return

        results: list[dict[str, Any]] = []
        raw = context.get("vision_objects_raw")
        if isinstance(raw, list):
            results = raw
        elif self.backend == "opencv_dnn":
            frame = context.get("vision_frame")
            if frame is not None:
                results = self._detect_opencv_dnn(frame, settings)

        context.set(
            "semantic_labels",
            {
                "timestamp": context.get("tick_ts"),
                "backend": self.backend,
                "labels": results,
            },
        )
        self._last_ts = now

    def _detect_opencv_dnn(self, frame, settings: dict) -> list[dict[str, Any]]:
        if self._cv2 is None or self._net is None:
            return []
        cv2 = self._cv2
        h, w = frame.shape[:2]

        input_w = int(settings.get("input_width", 320))
        input_h = int(settings.get("input_height", 320))
        conf_threshold = float(settings.get("confidence_threshold", 0.5))

        blob = cv2.dnn.blobFromImage(
            frame, size=(input_w, input_h), swapRB=True, crop=False
        )
        self._net.setInput(blob)
        detections = self._net.forward()

        results: list[dict[str, Any]] = []
        for i in range(detections.shape[2]):
            confidence = float(detections[0, 0, i, 2])
            if confidence < conf_threshold:
                continue
            class_id = int(detections[0, 0, i, 1])
            box = detections[0, 0, i, 3:7] * [w, h, w, h]
            x1, y1, x2, y2 = box.astype("int")
            label = (
                self._labels[class_id]
                if class_id < len(self._labels)
                else str(class_id)
            )
            results.append(
                {
                    "label": label,
                    "confidence": confidence,
                    "bbox": [int(x1), int(y1), int(x2 - x1), int(y2 - y1)],
                }
            )
        return results

    def _resolve_path(self, value: str) -> Path:
        if not value:
            return Path("__missing__")
        path = Path(value)
        if not path.is_absolute():
            path = self._repo_root / path
        return path
