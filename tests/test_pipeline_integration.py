"""
Integration tests for the wired-up main_pipeline.
No camera, Arduino, MQTT broker, or OpenCV required — all hardware is stubbed.
"""

import sys
import os
import json
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import main_pipeline

# Save the original module-level functions so reset_state() can restore them.
# Tests that patch main_pipeline.process_frame / compute_delta must call
# reset_state() at the start so the patches from a previous test don't leak
# into later tests (including tests in other test modules that share the same
# already-imported main_pipeline module object).
_orig_process_frame = main_pipeline.process_frame
_orig_compute_delta = main_pipeline.compute_delta


# ── helpers ───────────────────────────────────────────────────────────────────

def reset_state():
    main_pipeline._old_board = np.zeros((15, 15), dtype=np.uint8)
    main_pipeline._mqtt_connected = True
    main_pipeline._move_number = 0
    # Restore any monkey-patches applied by previous tests.
    main_pipeline.process_frame = _orig_process_frame
    main_pipeline.compute_delta = _orig_compute_delta


def board_with_stone(row, col, color=1):
    b = np.zeros((15, 15), dtype=np.uint8)
    b[row, col] = color
    return b


def capture_published():
    captured = []

    class _PublishResult:
        rc = getattr(main_pipeline.mqtt, "MQTT_ERR_SUCCESS", 0)

    def _publish(topic, payload):
        captured.append((topic, json.loads(payload)))
        return _PublishResult()

    main_pipeline._mqtt_client.publish = _publish
    return captured


# ── CV pipeline tests ─────────────────────────────────────────────────────────

def test_cv_returns_none_when_board_unchanged():
    reset_state()
    frame = np.zeros((800, 800, 3), dtype=np.uint8)
    main_pipeline.process_frame = lambda f, c: (np.zeros((15, 15), dtype=np.uint8), [], None, None, None)
    main_pipeline.compute_delta = lambda old, new: []

    assert main_pipeline.run_cv_pipeline(frame, None) is None
    print("PASS: returns None when no change detected")


def test_cv_detects_black_stone():
    reset_state()
    frame = np.zeros((800, 800, 3), dtype=np.uint8)
    main_pipeline.process_frame = lambda f, c: (board_with_stone(7, 7, 1), [], None, None, None)
    main_pipeline.compute_delta = lambda old, new: [
        {"type": "new_move", "row": 7, "col": 7, "color": "black"}
    ]

    result = main_pipeline.run_cv_pipeline(frame, None)
    assert result == {"player": "black", "row": 7, "col": 7}
    print("PASS: detects black stone at correct position")


def test_cv_detects_white_stone():
    reset_state()
    frame = np.zeros((800, 800, 3), dtype=np.uint8)
    main_pipeline.process_frame = lambda f, c: (board_with_stone(3, 11, 2), [], None, None, None)
    main_pipeline.compute_delta = lambda old, new: [
        {"type": "new_move", "row": 3, "col": 11, "color": "white"}
    ]

    result = main_pipeline.run_cv_pipeline(frame, None)
    assert result == {"player": "white", "row": 3, "col": 11}
    print("PASS: detects white stone at correct position")


def test_cv_rejects_multiple_new_stones():
    reset_state()
    frame = np.zeros((800, 800, 3), dtype=np.uint8)
    main_pipeline.process_frame = lambda f, c: (np.zeros((15, 15), dtype=np.uint8), [], None, None, None)
    main_pipeline.compute_delta = lambda old, new: [
        {"type": "new_move", "row": 5, "col": 5, "color": "black"},
        {"type": "new_move", "row": 6, "col": 6, "color": "white"},
    ]

    assert main_pipeline.run_cv_pipeline(frame, None) is None
    print("PASS: rejects ambiguous multi-stone delta")


def test_cv_rejects_uncertain_change():
    reset_state()
    frame = np.zeros((800, 800, 3), dtype=np.uint8)
    main_pipeline.process_frame = lambda f, c: (np.zeros((15, 15), dtype=np.uint8), [], None, None, None)
    main_pipeline.compute_delta = lambda old, new: [
        {"type": "changed_or_removed", "row": 5, "col": 5, "old": 1, "new": 0}
    ]

    assert main_pipeline.run_cv_pipeline(frame, None) is None
    print("PASS: rejects uncertain board change (stone removed or swapped)")


def test_cv_updates_old_board_after_move():
    reset_state()
    new_board = board_with_stone(4, 4, 1)
    frame = np.zeros((800, 800, 3), dtype=np.uint8)
    main_pipeline.process_frame = lambda f, c: (new_board, [], None, None, None)
    main_pipeline.compute_delta = lambda old, new: [
        {"type": "new_move", "row": 4, "col": 4, "color": "black"}
    ]

    main_pipeline.run_cv_pipeline(frame, None)
    assert main_pipeline._old_board[4, 4] == 1
    print("PASS: _old_board updated after move so next delta is correct")


# ── MQTT publish tests ────────────────────────────────────────────────────────

def test_publish_move_payload_format():
    reset_state()
    captured = capture_published()

    main_pipeline.publish_move({"player": "black", "row": 8, "column": 8})

    assert len(captured) == 1
    topic, data = captured[0]
    assert topic == "gomoku/move"
    assert data["player"] == "black"
    assert data["row"] == 8
    assert data["column"] == 8
    assert "move_number" in data
    assert "timestamp" in data
    print("PASS: publish_move sends correctly structured payload to gomoku/move")


def test_publish_move_skips_when_not_connected():
    reset_state()
    main_pipeline._mqtt_connected = False
    main_pipeline._mqtt_client.publish = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("publish should not be called when MQTT is disconnected")
    )

    ok = main_pipeline.publish_move({"player": "black", "row": 8, "column": 8})

    assert ok is False
    assert main_pipeline._move_number == 0
    print("PASS: publish_move skips sending when MQTT is disconnected")


def test_publish_move_failure_does_not_increment_counter():
    reset_state()

    class _FailedPublishResult:
        rc = 99

    main_pipeline._mqtt_client.publish = lambda *args, **kwargs: _FailedPublishResult()

    ok = main_pipeline.publish_move({"player": "black", "row": 8, "column": 8})

    assert ok is False
    assert main_pipeline._move_number == 0
    print("PASS: failed MQTT publish does not increment move_number")


def test_publish_move_increments_move_number():
    reset_state()
    captured = capture_published()

    main_pipeline.publish_move({"player": "black", "row": 1, "column": 1})
    main_pipeline.publish_move({"player": "white", "row": 2, "column": 2})
    main_pipeline.publish_move({"player": "black", "row": 3, "column": 3})

    numbers = [data["move_number"] for _, data in captured]
    assert numbers == [1, 2, 3]
    print("PASS: move_number increments correctly across calls")


def test_index_conversion_zero_to_one():
    reset_state()
    captured = capture_published()

    cv_move = {"player": "black", "row": 0, "col": 0}
    main_pipeline.publish_move({
        "player": cv_move["player"],
        "row":    cv_move["row"] + 1,
        "column": cv_move["col"] + 1,
    })

    _, data = captured[0]
    assert data["row"] == 1
    assert data["column"] == 1
    print("PASS: 0-indexed CV output correctly converted to 1-indexed for MQTT")


def test_index_conversion_boundary():
    reset_state()
    captured = capture_published()

    cv_move = {"player": "white", "row": 14, "col": 14}
    main_pipeline.publish_move({
        "player": cv_move["player"],
        "row":    cv_move["row"] + 1,
        "column": cv_move["col"] + 1,
    })

    _, data = captured[0]
    assert data["row"] == 15
    assert data["column"] == 15
    print("PASS: bottom-right corner (14,14) converts to (15,15) correctly")


# ── constants / config tests ──────────────────────────────────────────────────

def test_required_constants_present():
    for name in ("CAPTURE_INTERVAL_SECONDS", "STABLE_FRAMES_REQUIRED",
                 "DIFF_THRESHOLD", "ARDUINO_PORT", "MQTT_BROKER",
                 "MQTT_PORT", "MQTT_TOPIC", "BOARD_CORNERS"):
        assert hasattr(main_pipeline, name), f"Missing constant: {name}"
    print("PASS: all required pipeline constants are present")


def test_board_corners_defaults_to_none():
    assert main_pipeline.BOARD_CORNERS is None
    print("PASS: BOARD_CORNERS defaults to None (no warp until calibrated)")


if __name__ == "__main__":
    test_cv_returns_none_when_board_unchanged()
    test_cv_detects_black_stone()
    test_cv_detects_white_stone()
    test_cv_rejects_multiple_new_stones()
    test_cv_rejects_uncertain_change()
    test_cv_updates_old_board_after_move()
    test_publish_move_payload_format()
    test_publish_move_skips_when_not_connected()
    test_publish_move_failure_does_not_increment_counter()
    test_publish_move_increments_move_number()
    test_index_conversion_zero_to_one()
    test_index_conversion_boundary()
    test_required_constants_present()
    test_board_corners_defaults_to_none()
    print("\nAll pipeline integration tests passed.")
