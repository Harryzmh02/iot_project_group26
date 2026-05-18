"""
Tests for the CV-to-MQTT integration added to gomoku_cv.py.
No camera, Arduino, or real MQTT broker required — paho is stubbed.
"""

import json
import sys
import os
import types

# ── stub hardware before importing gomoku_cv ──────────────────────────────────

cv2_mod = types.ModuleType("cv2")
sys.modules.setdefault("cv2", cv2_mod)

numpy_available = True
try:
    import numpy as np
except ImportError:
    numpy_available = False

picamera2_mod = types.ModuleType("picamera2")
picamera2_mod.Picamera2 = None
sys.modules.setdefault("picamera2", picamera2_mod)

# Stub paho so gomoku_cv can import it, and we can inspect publish calls
paho_mod        = types.ModuleType("paho")
paho_mqtt_mod   = types.ModuleType("paho.mqtt")
paho_client_mod = types.ModuleType("paho.mqtt.client")

published_messages = []

class _FakeMQTTClient:
    def __init__(self, *a, **kw): pass
    def connect(self, *a, **kw): pass
    def loop_start(self): pass
    def loop_stop(self): pass
    def publish(self, topic, payload):
        published_messages.append((topic, json.loads(payload)))

class _FakeCallbackAPIVersion:
    VERSION2 = 2

paho_client_mod.Client = _FakeMQTTClient
paho_client_mod.CallbackAPIVersion = _FakeCallbackAPIVersion
paho_mod.mqtt = paho_mqtt_mod
paho_mqtt_mod.client = paho_client_mod
sys.modules["paho"]             = paho_mod
sys.modules["paho.mqtt"]        = paho_mqtt_mod
sys.modules["paho.mqtt.client"] = paho_client_mod

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'computer_vision'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'raspberrypi_integration'))

import gomoku_cv


# ── helpers ───────────────────────────────────────────────────────────────────

def reset():
    published_messages.clear()


def fake_mqtt_client():
    client = _FakeMQTTClient()
    client.publish = lambda topic, payload: published_messages.append(
        (topic, json.loads(payload))
    )
    return client


# ── publish_move tests ────────────────────────────────────────────────────────

def test_publish_move_uses_correct_topic():
    reset()
    client = fake_mqtt_client()
    gomoku_cv.publish_move(client, "gomoku/move", 1, "black", 0, 0)
    assert len(published_messages) == 1
    topic, _ = published_messages[0]
    assert topic == "gomoku/move"
    print("PASS: publish_move publishes to gomoku/move")


def test_publish_move_converts_row_col_to_one_indexed():
    reset()
    client = fake_mqtt_client()
    # CV stores 0-indexed; dashboard expects 1-indexed
    gomoku_cv.publish_move(client, "gomoku/move", 1, "black", 0, 0)
    _, data = published_messages[0]
    assert data["row"] == 1,    f"Expected row=1, got {data['row']}"
    assert data["column"] == 1, f"Expected column=1, got {data['column']}"
    print("PASS: (0,0) in CV → row=1, column=1 in MQTT payload")


def test_publish_move_boundary_14_14():
    reset()
    client = fake_mqtt_client()
    gomoku_cv.publish_move(client, "gomoku/move", 1, "white", 14, 14)
    _, data = published_messages[0]
    assert data["row"] == 15,    f"Expected row=15, got {data['row']}"
    assert data["column"] == 15, f"Expected column=15, got {data['column']}"
    print("PASS: (14,14) in CV → row=15, column=15 in MQTT payload (board boundary)")


def test_publish_move_field_name_is_column_not_col():
    reset()
    client = fake_mqtt_client()
    gomoku_cv.publish_move(client, "gomoku/move", 1, "black", 7, 7)
    _, data = published_messages[0]
    assert "column" in data, "Payload must use 'column' (Jason's field name)"
    assert "col" not in data, "Payload must NOT use 'col'"
    print("PASS: payload uses field name 'column', not 'col'")


def test_publish_move_payload_has_all_required_fields():
    reset()
    client = fake_mqtt_client()
    gomoku_cv.publish_move(client, "gomoku/move", 3, "white", 5, 9)
    _, data = published_messages[0]
    for field in ("player", "row", "column", "move_number", "timestamp"):
        assert field in data, f"Missing field: {field}"
    assert data["player"] == "white"
    assert data["move_number"] == 3
    print("PASS: payload contains all required fields (player, row, column, move_number, timestamp)")


def test_publish_move_player_values():
    reset()
    client = fake_mqtt_client()
    gomoku_cv.publish_move(client, "gomoku/move", 1, "black", 3, 3)
    gomoku_cv.publish_move(client, "gomoku/move", 2, "white", 4, 4)
    assert published_messages[0][1]["player"] == "black"
    assert published_messages[1][1]["player"] == "white"
    print("PASS: player field correctly carries 'black' and 'white'")


# ── send_feedback with MQTT tests ─────────────────────────────────────────────

def test_send_feedback_publishes_when_mqtt_provided():
    reset()
    client = fake_mqtt_client()
    changes = [{"type": "new_move", "color": "black", "row": 6, "col": 6}]
    gomoku_cv.send_feedback(None, changes, mqtt=client, topic="gomoku/move",
                            move_counter=iter([1]))
    assert len(published_messages) == 1
    print("PASS: send_feedback publishes when mqtt client is provided")


def test_send_feedback_does_not_publish_on_uncertain_change():
    reset()
    client = fake_mqtt_client()
    changes = [{"type": "changed_or_removed", "row": 5, "col": 5, "old": 1, "new": 0}]
    gomoku_cv.send_feedback(None, changes, mqtt=client, topic="gomoku/move",
                            move_counter=iter([1]))
    assert len(published_messages) == 0
    print("PASS: send_feedback does not publish on uncertain/removed-stone change")


def test_send_feedback_does_not_publish_when_no_mqtt():
    reset()
    changes = [{"type": "new_move", "color": "white", "row": 2, "col": 3}]
    # mqtt=None — should not raise, and nothing published
    gomoku_cv.send_feedback(None, changes, mqtt=None, topic="gomoku/move",
                            move_counter=iter([1]))
    assert len(published_messages) == 0
    print("PASS: send_feedback skips MQTT silently when mqtt=None")


def test_send_feedback_no_publish_on_empty_changes():
    reset()
    client = fake_mqtt_client()
    gomoku_cv.send_feedback(None, [], mqtt=client, topic="gomoku/move",
                            move_counter=iter([1]))
    assert len(published_messages) == 0
    print("PASS: send_feedback publishes nothing when changes list is empty")


# ── create_mqtt_client tests ──────────────────────────────────────────────────

def test_create_mqtt_client_returns_client_on_success():
    client = gomoku_cv.create_mqtt_client("localhost")
    assert client is not None
    print("PASS: create_mqtt_client returns a client when paho is available")


def test_create_mqtt_client_returns_none_on_connection_failure(monkeypatch=None):
    # Temporarily make connect raise to simulate broker-not-running
    original_connect = _FakeMQTTClient.connect
    def _bad_connect(self, *a, **kw):
        raise OSError("Connection refused")
    _FakeMQTTClient.connect = _bad_connect
    try:
        client = gomoku_cv.create_mqtt_client("192.0.2.1")  # non-routable
        assert client is None
        print("PASS: create_mqtt_client returns None when broker is unreachable")
    finally:
        _FakeMQTTClient.connect = original_connect


if __name__ == "__main__":
    test_publish_move_uses_correct_topic()
    test_publish_move_converts_row_col_to_one_indexed()
    test_publish_move_boundary_14_14()
    test_publish_move_field_name_is_column_not_col()
    test_publish_move_payload_has_all_required_fields()
    test_publish_move_player_values()
    test_send_feedback_publishes_when_mqtt_provided()
    test_send_feedback_does_not_publish_on_uncertain_change()
    test_send_feedback_does_not_publish_when_no_mqtt()
    test_send_feedback_no_publish_on_empty_changes()
    test_create_mqtt_client_returns_client_on_success()
    test_create_mqtt_client_returns_none_on_connection_failure()
    print("\nAll CV-MQTT integration tests passed.")
