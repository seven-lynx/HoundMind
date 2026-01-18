import numpy as np
import cv2
from houndmind_ai.optional.vision_preprocessing import VisionPreprocessor

def test_resize():
    frame = np.ones((480, 640, 3), dtype=np.uint8) * 127
    pre = VisionPreprocessor({"resize": (224, 224), "normalize": False})
    out = pre.process(frame)
    assert out.shape == (224, 224, 3)

def test_normalize():
    frame = np.ones((224, 224, 3), dtype=np.uint8) * 255
    pre = VisionPreprocessor({"resize": (224, 224), "normalize": True})
    out = pre.process(frame)
    assert np.allclose(out.mean(), (1.0 - pre.mean).mean() / pre.std.mean(), atol=0.1)

def test_roi():
    frame = np.ones((480, 640, 3), dtype=np.uint8) * 100
    pre = VisionPreprocessor({"resize": (224, 224), "normalize": False, "roi": (100, 100, 200, 200)})
    out = pre.process(frame)
    assert out.shape == (224, 224, 3)
