#!/usr/bin/env python3
"""
Face Recognition (Lite) Service for PackMind

Lightweight alternative for low-power devices (e.g., Raspberry Pi 3B):
- Face detection via OpenCV Haar cascades (CPU-friendly)
- Optional identity via OpenCV LBPH (requires cv2.face from opencv-contrib)
- Grayscale, low-res processing; conservative frame cadence

This service is API-compatible (subset) with FaceRecognitionService:
- start(), stop(), detect_and_recognize() returning {"faces": [...], ...}
- Training via train_from_dir() expects images under data/faces_lite/<name>/*.jpg

If LBPH is not available (cv2.face missing), the service runs in detection-only mode.
"""
from __future__ import annotations

import cv2
import numpy as np
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime
import json

@dataclass
class LiteFace:
    person_id: str
    name: str
    confidence: float
    location: Tuple[int, int, int, int]  # x, y, w, h
    known: bool
    interaction_count: int = 0

class FaceRecognitionLiteService:
    def __init__(self, config: Optional[object] = None) -> None:
        self.config = config or {}
        self.logger = logging.getLogger("packmind.face_recognition_lite")
        self.running = False
        self.enabled = True
        # Camera and cadence
        self.camera = None
        self.detection_interval = float(getattr(self.config, "FACE_DETECTION_INTERVAL", 2.0))
        self.last_detection_time = 0.0
        # Data dir
        self.data_dir = Path(getattr(self.config, "FACE_LITE_DATA_DIR", "data/faces_lite"))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Cascade
        try:
            cascade_path = str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
            self._detector = cv2.CascadeClassifier(cascade_path)
            if self._detector.empty():
                raise RuntimeError("Failed to load Haar cascade")
        except Exception as e:
            self.logger.warning(f"Haar cascade unavailable: {e}")
            self.enabled = False
            self._detector = None
        # Recognizer (optional)
        self._recognizer = None
        self._labels: Dict[int, str] = {}
        self._labels_file = self.data_dir / "labels.json"
        self._model_file = self.data_dir / "lbph_model.xml"
        self._maybe_init_lbph()

    # --- Lifecycle ---
    def start(self) -> bool:
        if not self.enabled:
            self.logger.warning("Lite face recognition disabled (detector unavailable)")
            return False
        try:
            self.camera = cv2.VideoCapture(0)
            if not self.camera.isOpened():
                raise RuntimeError("Could not open camera")
            # Modest camera settings for low-power devices
            width = int(getattr(self.config, "FACE_CAMERA_WIDTH", 320))
            height = int(getattr(self.config, "FACE_CAMERA_HEIGHT", 240))
            fps = int(getattr(self.config, "FACE_CAMERA_FPS", 10))
            try:
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                self.camera.set(cv2.CAP_PROP_FPS, fps)
            except Exception:
                pass
            self.running = True
            self.logger.info("FaceRecognitionLiteService started")
            return True
        except Exception as e:
            self.logger.error(f"Failed to start lite face service: {e}")
            self.running = False
            return False

    def stop(self) -> None:
        self.running = False
        if self.camera:
            self.camera.release()
            self.camera = None
        self.logger.info("FaceRecognitionLiteService stopped")

    # --- Detection/Recognition ---
    def detect_and_recognize(self) -> Dict[str, Any]:
        if not (self.enabled and self.running and self.camera and self._detector is not None):
            return {"faces": [], "error": "Service not available"}
        now = time.time()
        if now - self.last_detection_time < self.detection_interval:
            # Skip to reduce CPU usage
            return {"faces": [], "cached": True}
        t0 = time.time()
        try:
            ok, frame = self.camera.read()
            if not ok:
                return {"faces": [], "error": "Failed to capture frame"}
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # conservative min size
            faces = self._detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(50, 50))
            results: List[Dict[str, Any]] = []
            for (x, y, w, h) in faces[: int(getattr(self.config, "FACE_MAX_FACES_PER_FRAME", 3))]:
                roi = gray[y : y + h, x : x + w]
                person_id = ""
                name = "Unknown"
                confidence = 0.0
                known = False
                if self._recognizer is not None and roi.size > 0:
                    try:
                        face_resized = cv2.resize(roi, (80, 80))
                        label, dist = self._recognizer.predict(face_resized)
                        # LBPH returns distance: lower is better. Map to 0..1 confidence heuristic.
                        confidence = float(max(0.0, min(1.0, 1.0 - dist / 100.0)))
                        if label in self._labels:
                            known = True
                            name = self._labels[label]
                            person_id = f"lbph_{label}"
                    except Exception:
                        pass
                if not person_id:
                    # anonymous ID per detection
                    person_id = f"det_{x}_{y}_{w}_{h}"
                results.append(
                    {
                        "person_id": person_id,
                        "name": name,
                        "confidence": confidence,
                        "location": (int(x), int(y), int(w), int(h)),
                        "known": known,
                        "interaction_count": 0,
                    }
                )
            self.last_detection_time = now
            return {
                "faces": results,
                "frame_time": time.time() - t0,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            self.logger.error(f"Lite face detect error: {e}")
            return {"faces": [], "error": str(e)}

    # --- Training ---
    def train_from_dir(self, base_dir: Optional[Path] = None) -> bool:
        """Train LBPH from directory structure: base_dir/<name>/*.jpg
        If cv2.face is unavailable, returns False (detection-only mode).
        """
        if self._recognizer is None:
            self.logger.warning("LBPH not available (opencv-contrib missing?) — detection-only mode")
            return False
        base = Path(base_dir or self.data_dir)
        if not base.exists():
            self.logger.warning(f"Training directory not found: {base}")
            return False
        images: List[np.ndarray] = []
        labels: List[int] = []
        label_map: Dict[int, str] = {}
        current_label = 0
        for person_dir in sorted([p for p in base.iterdir() if p.is_dir()]):
            name = person_dir.name
            label_map[current_label] = name
            for img_path in person_dir.glob("*.jpg"):
                try:
                    img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
                    if img is None:
                        continue
                    # Optional: detect face in image; if found, crop; else use whole image
                    rects = self._detector.detectMultiScale(img, scaleFactor=1.1, minNeighbors=3)
                    if len(rects) > 0:
                        (x, y, w, h) = rects[0]
                        roi = img[y : y + h, x : x + w]
                    else:
                        roi = img
                    roi = cv2.resize(roi, (80, 80))
                    images.append(roi)
                    labels.append(current_label)
                except Exception:
                    continue
            current_label += 1
        if not images:
            self.logger.warning("No training images found")
            return False
        try:
            self._recognizer.train(images, np.array(labels))
            self._recognizer.save(str(self._model_file))
            with open(self._labels_file, "w") as f:
                json.dump(label_map, f)
            self._labels = label_map
            self.logger.info(f"LBPH trained with {len(images)} images across {len(label_map)} people")
            return True
        except Exception as e:
            self.logger.error(f"Failed to train LBPH: {e}")
            return False

    # --- Helpers ---
    def _maybe_init_lbph(self) -> None:
        try:
            # Requires opencv-contrib-python
            if not hasattr(cv2, "face"):
                return
            self._recognizer = cv2.face.LBPHFaceRecognizer_create(radius=1, neighbors=8, grid_x=8, grid_y=8)
            # Load model/labels if present
            if self._model_file.exists():
                try:
                    self._recognizer.read(str(self._model_file))
                except Exception:
                    pass
            if self._labels_file.exists():
                try:
                    with open(self._labels_file, "r") as f:
                        self._labels = {int(k): v for k, v in json.load(f).items()}
                except Exception:
                    self._labels = {}
        except Exception:
            # LBPH not available; detection-only mode
            self._recognizer = None
            self._labels = {}
