from __future__ import annotations

import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class VisionPi4Module(Module):
    """Pi4-focused vision feed.

    Publishes `vision_frame` into context. Supports Picamera2 if available,
    otherwise falls back to OpenCV VideoCapture.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.available = False
        self._camera = None
        self._cv2 = None
        self._capture = None
        self._last_frame_ts = 0.0
        self._last_frame = None

        self._http_server: ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        settings = (context.get("settings") or {}).get("vision_pi4", {})
        backend = settings.get("backend", "picamera2")

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
                    self._maybe_start_http(settings)
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Picamera2 init failed: %s", exc)

        try:
            import cv2  # type: ignore
        except Exception as exc:  # noqa: BLE001
            self.disable(f"Vision backend unavailable: {exc}")
            return

        device_index = int(settings.get("device_index", 0))
        capture = cv2.VideoCapture(device_index)
        if not capture.isOpened():
            self.disable("Failed to open camera device")
            return

        self._cv2 = cv2
        self._capture = capture
        self.available = True
        context.set("vision_status", {"status": "ready", "backend": "opencv"})
        self._maybe_start_http(settings)

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
            self._last_frame = frame

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
        if self._http_server is not None:
            try:
                self._http_server.shutdown()
                self._http_server.server_close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Vision HTTP server shutdown failed: %s", exc)

    def _maybe_start_http(self, settings: dict) -> None:
        http_settings = settings.get("http", {})
        if not http_settings.get("enabled", False):
            return
        host = http_settings.get("host", "0.0.0.0")
        port = int(http_settings.get("port", 8090))

        module = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/stream":
                    self.send_response(404)
                    self.end_headers()
                    return

                self.send_response(200)
                self.send_header(
                    "Content-Type", "multipart/x-mixed-replace; boundary=frame"
                )
                self.end_headers()

                try:
                    while True:
                        frame = module._last_frame
                        if frame is None or module._cv2 is None:
                            time.sleep(0.05)
                            continue

                        ok, buf = module._cv2.imencode(".jpg", frame)
                        if not ok:
                            time.sleep(0.05)
                            continue
                        payload = buf.tobytes()
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(
                            f"Content-Length: {len(payload)}\r\n\r\n".encode()
                        )
                        self.wfile.write(payload)
                        self.wfile.write(b"\r\n")
                        time.sleep(0.1)
                except Exception:
                    return

            def log_message(self, format, *args):
                return

        try:
            server = ThreadingHTTPServer((host, port), Handler)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to start vision HTTP server: %s", exc)
            return
        self._http_server = server
        self._http_thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._http_thread.start()
        logger.info("Vision HTTP stream on http://%s:%s/stream", host, port)
