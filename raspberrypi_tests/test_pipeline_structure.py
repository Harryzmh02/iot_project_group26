"""
Tests that main_pipeline.py is correctly structured and wired.
No camera or Arduino required — verifies imports and interface contracts only.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'raspberrypi_capture'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'raspberrypi_integration'))

import types
import numpy as np


def test_frame_stability_importable():
    from frame_stability import FrameStabilityChecker
    checker = FrameStabilityChecker()
    assert hasattr(checker, 'update')
    assert hasattr(checker, 'reset')
    print("PASS: FrameStabilityChecker imports and has required methods")


def test_image_preprocessing_importable():
    from image_preprocessing import preprocess_frame, crop_to_board
    assert callable(preprocess_frame)
    assert callable(crop_to_board)
    print("PASS: image_preprocessing imports correctly")


def test_arduino_feedback_client_importable():
    from arduino_feedback_client import ArduinoFeedbackClient
    client = ArduinoFeedbackClient()
    for method in ('connect', 'black_move', 'white_move', 'error', 'reset', 'close'):
        assert hasattr(client, method), f"Missing method: {method}"
    print("PASS: ArduinoFeedbackClient imports and has all required methods")


def test_pipeline_cv_stub_returns_none():
    import main_pipeline
    dummy_frame = np.zeros((800, 800, 3), dtype=np.uint8)
    result = main_pipeline.run_cv_pipeline(dummy_frame, board_corners=None)
    assert result is None, "CV stub should return None until Ashish implements it"
    print("PASS: run_cv_pipeline stub returns None as expected")


def test_pipeline_mqtt_stub_runs_without_error():
    import main_pipeline
    dummy_move = {
        "player": "black",
        "row": 7,
        "col": 7,
        "move_num": 1,
        "board": [[0]*15 for _ in range(15)],
        "timestamp": "2026-05-16T12:00:00"
    }
    try:
        main_pipeline.publish_move(dummy_move)
        print("PASS: publish_move stub runs without error")
    except Exception as e:
        raise AssertionError(f"publish_move stub raised an error: {e}")


def test_pipeline_constants_present():
    import main_pipeline
    assert hasattr(main_pipeline, 'CAPTURE_INTERVAL_SECONDS')
    assert hasattr(main_pipeline, 'STABLE_FRAMES_REQUIRED')
    assert hasattr(main_pipeline, 'DIFF_THRESHOLD')
    assert hasattr(main_pipeline, 'ARDUINO_PORT')
    print("PASS: all pipeline constants are defined")


if __name__ == "__main__":
    test_frame_stability_importable()
    test_image_preprocessing_importable()
    test_arduino_feedback_client_importable()
    test_pipeline_cv_stub_returns_none()
    test_pipeline_mqtt_stub_runs_without_error()
    test_pipeline_constants_present()
    print("\nAll pipeline structure tests passed.")
