from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from pathlib import Path
from typing import Any

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class FaceRecognitionModule(Module):
    """Pi4-focused face recognition module (backend-pluggable).

    Lite backend: OpenCV Haar detector with optional LBPH recognition.
    Heavy backend: face_recognition (dlib-based) with embeddings.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.backend: str = "stub"
        self.available = False
        self.repo_root = Path(__file__).resolve().parents[3]

        self._cv2 = None
        self._cascade = None
        self._recognizer = None
        self._label_map: dict[int, str] = {}

        self._embeddings_path: Path | None = None
        self._known_embeddings: list[list[float]] = []
        self._known_names: list[str] = []

        self._http_server: ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._pending_commands: list[dict[str, Any]] = []
        self._latest_faces: list[dict[str, Any]] = []

    def start(self, context) -> None:
        if not self.status.enabled:
            return

        settings = (context.get("settings") or {}).get("face_recognition", {})
        backend = settings.get("backend", "stub")
        self.backend = backend

        if backend == "stub":
            self.available = True
            context.set(
                "face_recognition_status", {"status": "ready", "backend": backend}
            )
            return

        if backend == "opencv":
            try:
                import cv2  # type: ignore
            except Exception as exc:  # noqa: BLE001
                self.disable(f"OpenCV backend unavailable: {exc}")
                return

            self._cv2 = cv2
            haar_path = settings.get("opencv_haar_path")
            if not haar_path:
                haar_path = str(
                    Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
                )
            haar_path = self._resolve_path(haar_path)
            if not haar_path.exists():
                self.disable(f"Haar cascade not found: {haar_path}")
                return
            self._cascade = cv2.CascadeClassifier(str(haar_path))

            lbph_settings = settings.get("lbph", {})
            if lbph_settings.get("enabled", True) and hasattr(cv2, "face"):
                try:
                    self._recognizer = cv2.face.LBPHFaceRecognizer_create()  # type: ignore[attr-defined]
                except Exception as exc:  # noqa: BLE001
                    logger.warning("LBPH unavailable: %s", exc)
                    self._recognizer = None

            if self._recognizer is not None:
                model_path = self._resolve_path(
                    lbph_settings.get("model_path", "data/face_model.yml")
                )
                dataset_dir = self._resolve_path(
                    lbph_settings.get("dataset_dir", "data/face_dataset")
                )
                label_map_path = self._resolve_path(
                    lbph_settings.get("label_map_path", "data/face_labels.json")
                )
                self._label_map = self._load_label_map(label_map_path)
                if model_path.exists():
                    try:
                        self._recognizer.read(str(model_path))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to read LBPH model: %s", exc)
                elif dataset_dir.exists():
                    self._train_lbph(dataset_dir, model_path, label_map_path)

            self.available = True
            context.set(
                "face_recognition_status", {"status": "ready", "backend": backend}
            )
            self._maybe_start_http(settings)
            return

        if backend == "face_recognition":
            try:
                import face_recognition  # type: ignore  # noqa: F401
            except Exception as exc:  # noqa: BLE001
                self.disable(f"face_recognition backend unavailable: {exc}")
                return

            self._embeddings_path = self._resolve_path(
                settings.get("embeddings_path", "data/face_embeddings.json")
            )
            self._load_embeddings()
            self.available = True
            context.set(
                "face_recognition_status", {"status": "ready", "backend": backend}
            )
            self._maybe_start_http(settings)
            return

        self.disable(f"Unknown face recognition backend: {backend}")

    def tick(self, context) -> None:
        if not self.available or not self.status.enabled:
            return

        settings = (context.get("settings") or {}).get("face_recognition", {})
        if not settings.get("enabled", True):
            return

        command = context.get("face_recognition_command")
        if isinstance(command, dict):
            self._handle_command(command, context, settings)
            context.set("face_recognition_command", None)

        if self._pending_commands:
            for pending in list(self._pending_commands):
                self._handle_command(pending, context, settings)
                self._pending_commands.remove(pending)

        detections: list[dict[str, Any]] = []
        raw = context.get("vision_faces_raw")
        if isinstance(raw, list):
            detections = raw

        frame = context.get("vision_frame")
        if detections:
            context.set("faces", self._wrap_faces(context, detections))
            return

        if frame is None:
            return

        if self.backend == "opencv":
            detections = self._detect_opencv(frame, settings)
        elif self.backend == "face_recognition":
            detections = self._detect_face_recognition(frame, settings)
        else:
            detections = []

        context.set("faces", self._wrap_faces(context, detections))
        self._latest_faces = detections

    def _wrap_faces(self, context, detections: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "timestamp": context.get("tick_ts"),
            "backend": self.backend,
            "detected": detections,
        }

    def _maybe_start_http(self, settings: dict) -> None:
        http_settings = settings.get("http", {})
        if not http_settings.get("enabled", False):
            return
        host = http_settings.get("host", "0.0.0.0")
        port = int(http_settings.get("port", 8088))

        module = self

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, payload, status=200):
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/status":
                    self._send_json({"status": "ok", "backend": module.backend})
                    return
                if parsed.path == "/faces":
                    self._send_json({"faces": module._latest_faces})
                    return
                if parsed.path == "/enroll":
                    qs = parse_qs(parsed.query)
                    name = (qs.get("name") or [None])[0]
                    if not name:
                        self._send_json({"error": "Missing name"}, status=400)
                        return
                    module._pending_commands.append({"action": "enroll", "name": name})
                    self._send_json({"status": "queued", "name": name})
                    return
                self._send_json({"error": "Not found"}, status=404)

            def do_POST(self):
                parsed = urlparse(self.path)
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
                if parsed.path == "/enroll":
                    try:
                        payload = json.loads(body) if body else {}
                    except Exception:
                        payload = {}
                    name = payload.get("name")
                    if not name:
                        self._send_json({"error": "Missing name"}, status=400)
                        return
                    module._pending_commands.append({"action": "enroll", "name": name})
                    self._send_json({"status": "queued", "name": name})
                    return
                self._send_json({"error": "Not found"}, status=404)

            def log_message(self, format, *args):
                return

        try:
            server = ThreadingHTTPServer((host, port), Handler)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to start face recognition HTTP server: %s", exc)
            return
        self._http_server = server
        self._http_thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._http_thread.start()
        logger.info("Face recognition HTTP server listening on %s:%s", host, port)

    def _detect_opencv(self, frame, settings: dict) -> list[dict[str, Any]]:
        if self._cv2 is None or self._cascade is None:
            return []
        cv2 = self._cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        scale_factor = float(settings.get("scale_factor", 1.1))
        min_neighbors = int(settings.get("min_neighbors", 5))
        min_face_px = int(settings.get("min_face_px", 60))

        faces = self._cascade.detectMultiScale(
            gray,
            scaleFactor=scale_factor,
            minNeighbors=min_neighbors,
            minSize=(min_face_px, min_face_px),
        )

        results: list[dict[str, Any]] = []
        lbph_settings = settings.get("lbph", {})
        threshold = float(lbph_settings.get("confidence_threshold", 70.0))
        for x, y, w, h in faces:
            entry: dict[str, Any] = {"bbox": [int(x), int(y), int(w), int(h)]}
            if self._recognizer is not None:
                face_roi = gray[y : y + h, x : x + w]
                try:
                    label_id, confidence = self._recognizer.predict(face_roi)
                    name = self._label_map.get(int(label_id), "unknown")
                    entry.update({"label": name, "confidence": float(confidence)})
                    if confidence > threshold:
                        entry["label"] = "unknown"
                except Exception as exc:  # noqa: BLE001
                    logger.debug("LBPH prediction failed: %s", exc)
            results.append(entry)
        return results

    def _detect_face_recognition(self, frame, settings: dict) -> list[dict[str, Any]]:
        try:
            import face_recognition  # type: ignore
        except Exception:
            return []

        rgb = frame[:, :, ::-1]
        locations = face_recognition.face_locations(rgb)
        encodings = face_recognition.face_encodings(rgb, locations)
        threshold = float(settings.get("match_threshold", 0.6))
        results: list[dict[str, Any]] = []

        for (top, right, bottom, left), encoding in zip(locations, encodings):
            label = "unknown"
            confidence = None
            if self._known_embeddings:
                distances = face_recognition.face_distance(
                    self._known_embeddings, encoding
                )
                if len(distances) > 0:
                    best_idx = int(distances.argmin())  # type: ignore[attr-defined]
                    best_dist = float(distances[best_idx])
                    if best_dist <= threshold:
                        label = self._known_names[best_idx]
                        confidence = 1.0 - best_dist
            results.append(
                {
                    "bbox": [int(left), int(top), int(right - left), int(bottom - top)],
                    "label": label,
                    "confidence": confidence,
                }
            )
        return results

    def _handle_command(self, command: dict, context, settings: dict) -> None:
        action = command.get("action")
        name = command.get("name")
        frame = context.get("vision_frame")
        if action != "enroll" or not name or frame is None:
            return

        if self.backend == "opencv":
            self._enroll_opencv(name, frame, settings)
        elif self.backend == "face_recognition":
            self._enroll_face_recognition(name, frame, settings)

    def _enroll_opencv(self, name: str, frame, settings: dict) -> None:
        if self._cv2 is None or self._cascade is None:
            return
        cv2 = self._cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
        )
        if len(faces) != 1:
            logger.warning("Enroll requires exactly one face; got %d", len(faces))
            return

        x, y, w, h = faces[0]
        face_roi = gray[y : y + h, x : x + w]

        lbph_settings = settings.get("lbph", {})
        dataset_dir = self._resolve_path(
            lbph_settings.get("dataset_dir", "data/face_dataset")
        )
        dataset_dir.mkdir(parents=True, exist_ok=True)
        person_dir = dataset_dir / name
        person_dir.mkdir(parents=True, exist_ok=True)
        filename = person_dir / f"{int(time.time())}.png"
        cv2.imwrite(str(filename), face_roi)

        model_path = self._resolve_path(
            lbph_settings.get("model_path", "data/face_model.yml")
        )
        label_map_path = self._resolve_path(
            lbph_settings.get("label_map_path", "data/face_labels.json")
        )
        self._train_lbph(dataset_dir, model_path, label_map_path)

    def _train_lbph(
        self, dataset_dir: Path, model_path: Path, label_map_path: Path
    ) -> None:
        if self._cv2 is None or self._recognizer is None:
            return
        cv2 = self._cv2
        faces: list[Any] = []
        labels: list[int] = []
        label_map: dict[int, str] = {}
        label_id = 0

        for person_dir in sorted(dataset_dir.iterdir()):
            if not person_dir.is_dir():
                continue
            label_map[label_id] = person_dir.name
            for img_path in person_dir.glob("*.png"):
                img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                faces.append(img)
                labels.append(label_id)
            label_id += 1

        if not faces:
            return

        try:
            import numpy as np  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.warning("NumPy required for LBPH training: %s", exc)
            return
        self._recognizer.train(faces, np.array(labels))
        model_path.parent.mkdir(parents=True, exist_ok=True)
        self._recognizer.save(str(model_path))
        label_map_path.parent.mkdir(parents=True, exist_ok=True)
        label_map_path.write_text(json.dumps(label_map, indent=2), encoding="utf-8")
        self._label_map = label_map

    def _enroll_face_recognition(self, name: str, frame, settings: dict) -> None:
        try:
            import face_recognition  # type: ignore
        except Exception:
            return

        rgb = frame[:, :, ::-1]
        locations = face_recognition.face_locations(rgb)
        encodings = face_recognition.face_encodings(rgb, locations)
        if len(encodings) != 1:
            logger.warning("Enroll requires exactly one face; got %d", len(encodings))
            return

        self._known_embeddings.append(encodings[0].tolist())
        self._known_names.append(name)
        self._save_embeddings()

    def _load_embeddings(self) -> None:
        if self._embeddings_path is None or not self._embeddings_path.exists():
            return
        try:
            payload = json.loads(self._embeddings_path.read_text(encoding="utf-8"))
            self._known_embeddings = payload.get("embeddings", [])
            self._known_names = payload.get("names", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load embeddings: %s", exc)

    def _save_embeddings(self) -> None:
        if self._embeddings_path is None:
            return
        self._embeddings_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"names": self._known_names, "embeddings": self._known_embeddings}
        self._embeddings_path.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def _load_label_map(self, label_map_path: Path) -> dict[int, str]:
        if not label_map_path.exists():
            return {}
        try:
            payload = json.loads(label_map_path.read_text(encoding="utf-8"))
            return {int(k): v for k, v in payload.items()}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load label map: %s", exc)
            return {}

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.repo_root / path
        return path

    def stop(self, context) -> None:
        if self._http_server is not None:
            try:
                self._http_server.shutdown()
                self._http_server.server_close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to stop face recognition HTTP server: %s", exc)
