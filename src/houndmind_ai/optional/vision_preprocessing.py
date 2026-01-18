"""
Frame pre-processing pipeline for vision: resize, normalize, ROI selection.
Configurable and hardware-friendly for Pi4 vision tasks.
"""
import cv2
import numpy as np

class VisionPreprocessor:
    def __init__(self, config=None):
        self.config = config or {}
        self.target_size = tuple(self.config.get("resize", (224, 224)))
        self.normalize = self.config.get("normalize", True)
        self.roi = self.config.get("roi", None)  # (x, y, w, h) or None
        self.mean = np.array(self.config.get("mean", [0.485, 0.456, 0.406]))
        self.std = np.array(self.config.get("std", [0.229, 0.224, 0.225]))

    def process(self, frame):
        # ROI selection
        if self.roi:
            x, y, w, h = self.roi
            frame = frame[y:y+h, x:x+w]
        # Resize
        frame = cv2.resize(frame, self.target_size, interpolation=cv2.INTER_LINEAR)
        # Normalize
        if self.normalize:
            frame = frame.astype(np.float32) / 255.0
            frame = (frame - self.mean) / self.std
        return frame
