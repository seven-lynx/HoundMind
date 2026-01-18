"""
Vision Inference Scheduler

Runs vision model inference in a separate thread or process for Pi4 hardware.
Handles frame input, inference scheduling, and result output.

Configurable via config/settings.jsonc (Pi4 only).
"""

import threading
import queue
import time
from typing import Callable, Any, Optional

class VisionInferenceScheduler:
    """
    Schedules vision inference jobs in a background thread or process.
    Accepts frames, runs inference, and returns results via callback or queue.
    """
    def __init__(self, inference_fn: Callable[[Any], Any], result_callback: Optional[Callable[[Any], None]] = None, max_queue_size: int = 4):
        self.inference_fn = inference_fn
        self.result_callback = result_callback
        self.frame_queue = queue.Queue(maxsize=max_queue_size)
        self.result_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._stop_event.clear()
        if not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._thread.join(timeout=2)

    def submit_frame(self, frame: Any):
        try:
            self.frame_queue.put_nowait(frame)
        except queue.Full:
            # Drop frame if queue is full (backpressure)
            pass

    def get_result(self, timeout: float = 0.1) -> Optional[Any]:
        try:
            return self.result_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _run(self):
        while not self._stop_event.is_set():
            try:
                frame = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            result = self.inference_fn(frame)
            if self.result_callback:
                self.result_callback(result)
            else:
                self.result_queue.put(result)

# Example usage (to be replaced with actual vision model):
def dummy_inference(frame):
    time.sleep(0.05)  # Simulate inference latency
    return {'frame_id': id(frame), 'result': 'ok'}

if __name__ == "__main__":
    scheduler = VisionInferenceScheduler(dummy_inference)
    scheduler.start()
    for i in range(5):
        scheduler.submit_frame(f"frame_{i}")
    time.sleep(0.5)
    while True:
        result = scheduler.get_result()
        if result is None:
            break
        print(result)
    scheduler.stop()
