"""`tools.camera_check` tries the backend the runtime uses first (#395).

On Bookworm the sensor is served by libcamera/unicam: picamera2 captures, and the V4L2 node OpenCV
opens does not produce frames. The tool asked only OpenCV, so on a healthy Pi 4 it reported a broken
camera. These cases pin the order, and that a failure names what was tried.
"""

from __future__ import annotations

import pytest

from tools import camera_check


class FakePicamera2:
    """Only what the tool touches: a still configuration, start/stop, and one array."""

    instances: list[FakePicamera2] = []
    infos: list[dict] = []
    raises = False

    def __init__(self) -> None:
        FakePicamera2.instances.append(self)
        self.started = False
        self.closed = False

    @classmethod
    def global_camera_info(cls) -> list[dict]:
        return cls.infos

    def create_still_configuration(self) -> dict:
        return {"still": True}

    def configure(self, config) -> None:
        self.config = config

    def start(self) -> None:
        if FakePicamera2.raises:
            raise RuntimeError("camera busy")
        self.started = True

    def capture_array(self):
        return "frame"

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(camera_check, "PICAMERA2_SETTLE_S", 0.0)
    FakePicamera2.instances = []
    FakePicamera2.infos = [{"Model": "ov5647"}]
    FakePicamera2.raises = False


def test_a_still_comes_from_picamera2_when_it_is_available(monkeypatch) -> None:
    monkeypatch.setattr(camera_check, "_picamera2", lambda: FakePicamera2)
    monkeypatch.setattr(camera_check, "_encode_jpeg", lambda frame: b"jpeg")

    data, backend = camera_check.capture_frame_with_backend(0)

    assert data == b"jpeg"
    assert backend == "picamera2"
    assert FakePicamera2.instances[0].closed is True, "the camera is released even on success"


def test_a_failure_names_both_backends(monkeypatch) -> None:
    """`Failed to capture frame` read like a lens problem; the message has to say what failed."""
    FakePicamera2.raises = True
    monkeypatch.setattr(camera_check, "_picamera2", lambda: FakePicamera2)
    monkeypatch.setattr(camera_check, "_capture_cv2", lambda index: None)

    data, backend = camera_check.capture_frame_with_backend(2)

    assert data is None
    assert backend == "picamera2 and cv2 index 2"
    assert FakePicamera2.instances[0].closed is True, "a camera that failed to start is released"


def test_open_cv_still_answers_when_picamera2_is_absent(monkeypatch) -> None:
    monkeypatch.setattr(camera_check, "_picamera2", lambda: None)
    monkeypatch.setattr(camera_check, "_capture_cv2", lambda index: b"cv2")

    data, backend = camera_check.capture_frame_with_backend(1)

    assert data == b"cv2"
    assert backend == "cv2 index 1"


def test_devices_come_from_libcamera_when_it_reports_one(monkeypatch) -> None:
    monkeypatch.setattr(camera_check, "_picamera2", lambda: FakePicamera2)
    monkeypatch.setattr(camera_check, "_cv2_indexes", lambda max_index: [0, 1])

    assert camera_check.list_devices(5) == [0]


def test_without_picamera2_devices_fall_back_to_open_cv(monkeypatch) -> None:
    monkeypatch.setattr(camera_check, "_picamera2", lambda: None)
    monkeypatch.setattr(camera_check, "_cv2_indexes", lambda max_index: [0, 1])

    assert camera_check.list_devices(5) == [0, 1]
