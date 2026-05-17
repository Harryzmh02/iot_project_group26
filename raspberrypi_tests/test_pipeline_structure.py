"""
Tests that main_pipeline.py is correctly structured and wired.
No camera, Arduino, MQTT broker, or OpenCV required — all hardware is stubbed.
"""

import sys
import os
import types
import numpy as np

# ── stub out hardware before importing main_pipeline ─────────────────────────

picamera2_mod = types.ModuleType("picamera2")
class _FakePicamera2:
    def configure(self, *a, **kw): pass
    def create_preview_configuration(self, *a, **kw): return {}
    def start(self): pass
    def stop(self): pass
    def capture_array(self): return np.zeros((720, 1280, 3), dtype=np.uint8)
picamera2_mod.Picamera2 = _FakePicamera2
sys.modules.setdefault("picamera2", picamera2_mod)

paho_mod        = types.ModuleType("paho")
paho_mqtt_mod   = types.ModuleType("paho.mqtt")
paho_client_mod = types.ModuleType("paho.mqtt.client")
class _FakeMQTTClient:
    def __init__(self, *a, **kw): pass
    def connect(self, *a, **kw): pass
    def loop_start(self): pass
    def loop_stop(self): pass
    def disconnect(self): pass
    def publish(self, topic, payload): pass
class _FakeCallbackAPIVersion:
    VERSION2 = 2
paho_client_mod.Client = _FakeMQTTClient
paho_client_mod.CallbackAPIVersion = _FakeCallbackAPIVersion
paho_mod.mqtt = paho_mqtt_mod
paho_mqtt_mod.client = paho_client_mod
sys.modules.setdefault("paho", paho_mod)
sys.modules.setdefault("paho.mqtt", paho_mqtt_mod)
sys.modules.setdefault("paho.mqtt.client", paho_client_mod)

serial_mod = types.ModuleType("serial")
class _FakeSerialException(Exception): pass
serial_mod.Serial = object
serial_mod.SerialException = _FakeSerialException
sys.modules.setdefault("serial", serial_mod)

cv2_mod = types.ModuleType("cv2")
sys.modules.setdefault("cv2", cv2_mod)

gomoku_cv_mod = types.ModuleType("gomoku_cv")
gomoku_cv_mod.process_frame  = lambda frame, corners: (np.zeros((15, 15), dtype=np.uint8), [], None, None, None)
gomoku_cv_mod.compute_delta  = lambda old, new: []
gomoku_cv_mod.parse_corners  = lambda s: None
sys.modules.setdefault("gomoku_cv", gomoku_cv_mod)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'raspberrypi_capture'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'raspberrypi_integration'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'computer_vision'))


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


def test_pipeline_cv_returns_none_for_empty_board():
    import main_pipeline
    main_pipeline._old_board = np.zeros((15, 15), dtype=np.uint8)
    dummy_frame = np.zeros((800, 800, 3), dtype=np.uint8)
    result = main_pipeline.run_cv_pipeline(dummy_frame, board_corners=None)
    assert result is None, "run_cv_pipeline should return None when no new move detected"
    print("PASS: run_cv_pipeline returns None for empty board (no move detected)")


def test_pipeline_publish_move_runs_without_error():
    import main_pipeline
    dummy_move = {"player": "black", "row": 8, "column": 8}
    try:
        main_pipeline.publish_move(dummy_move)
        print("PASS: publish_move runs without error")
    except Exception as e:
        raise AssertionError(f"publish_move raised an error: {e}")


def test_pipeline_constants_present():
    import main_pipeline
    for name in ("CAPTURE_INTERVAL_SECONDS", "STABLE_FRAMES_REQUIRED",
                 "DIFF_THRESHOLD", "ARDUINO_PORT", "MQTT_BROKER",
                 "MQTT_PORT", "MQTT_TOPIC", "BOARD_CORNERS"):
        assert hasattr(main_pipeline, name), f"Missing constant: {name}"
    print("PASS: all pipeline constants are defined")


if __name__ == "__main__":
    test_frame_stability_importable()
    test_image_preprocessing_importable()
    test_arduino_feedback_client_importable()
    test_pipeline_cv_returns_none_for_empty_board()
    test_pipeline_publish_move_runs_without_error()
    test_pipeline_constants_present()
    print("\nAll pipeline structure tests passed.")
