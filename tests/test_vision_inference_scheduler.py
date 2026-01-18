"""
Test for VisionInferenceScheduler
"""
import time
import pytest
from src.houndmind_ai.optional.vision_inference_scheduler import VisionInferenceScheduler

def dummy_inference(frame):
    time.sleep(0.01)
    return {'frame': frame, 'result': 'ok'}

def test_scheduler_basic():
    results = []
    def cb(res):
        results.append(res)
    scheduler = VisionInferenceScheduler(dummy_inference, result_callback=cb)
    scheduler.start()
    for i in range(3):
        scheduler.submit_frame(f"frame_{i}")
    time.sleep(0.1)
    scheduler.stop()
    assert len(results) == 3
    for i, res in enumerate(results):
        assert res['frame'] == f"frame_{i}"
        assert res['result'] == 'ok'
