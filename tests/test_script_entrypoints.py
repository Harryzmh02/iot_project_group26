import importlib.util
import json
import os
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
DASHBOARD_MQTT_PATH = PROJECT_ROOT / "dashboard" / "mqtt.py"

sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))


def test_periodic_board_capture_imports_cleanly():
    import periodic_board_capture

    assert hasattr(periodic_board_capture, "main")

    # Force Picamera2 to None so the RuntimeError branch is always exercised,
    # regardless of whether a picamera2 stub is already in sys.modules from
    # another test module.  We save and restore the original value so other
    # tests are unaffected.
    saved = periodic_board_capture.Picamera2
    try:
        periodic_board_capture.Picamera2 = None
        try:
            periodic_board_capture.main()
        except RuntimeError as exc:
            assert "Picamera2 is not installed" in str(exc)
        else:
            raise AssertionError("Expected a RuntimeError when Picamera2 is unavailable")
    finally:
        periodic_board_capture.Picamera2 = saved

    print("PASS: periodic_board_capture imports cleanly and fails gracefully without Picamera2")


def test_dashboard_mqtt_import_has_no_side_effects():
    counters = {
        "connect": 0,
        "publish": 0,
        "disconnect": 0,
        "payloads": [],
    }

    paho_mod = types.ModuleType("paho")
    paho_mqtt_mod = types.ModuleType("paho.mqtt")
    paho_client_mod = types.ModuleType("paho.mqtt.client")

    class _FakePublishResult:
        rc = 0

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self, *args, **kwargs):
            counters["connect"] += 1

        def publish(self, topic, payload):
            counters["publish"] += 1
            counters["payloads"].append((topic, json.loads(payload)))
            return _FakePublishResult()

        def disconnect(self):
            counters["disconnect"] += 1

    class _FakeCallbackAPIVersion:
        VERSION2 = 2

    paho_client_mod.Client = _FakeClient
    paho_client_mod.CallbackAPIVersion = _FakeCallbackAPIVersion
    paho_client_mod.MQTT_ERR_SUCCESS = 0
    paho_mod.mqtt = paho_mqtt_mod
    paho_mqtt_mod.client = paho_client_mod

    saved_modules = {
        name: sys.modules.get(name)
        for name in ("paho", "paho.mqtt", "paho.mqtt.client")
    }

    try:
        sys.modules["paho"] = paho_mod
        sys.modules["paho.mqtt"] = paho_mqtt_mod
        sys.modules["paho.mqtt.client"] = paho_client_mod

        spec = importlib.util.spec_from_file_location("dashboard_mqtt_entrypoint_test", DASHBOARD_MQTT_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        assert counters["connect"] == 0
        assert counters["publish"] == 0
        assert counters["disconnect"] == 0

        exit_code = module.main(moves=[("black", 8, 8)], interval_seconds=0)

        assert exit_code == 0
        assert counters["connect"] == 1
        assert counters["publish"] == 1
        assert counters["disconnect"] == 1
        topic, payload = counters["payloads"][0]
        assert topic == "gomoku/move"
        assert payload["player"] == "black"
        assert payload["row"] == 8
        assert payload["column"] == 8
        assert payload["move_number"] == 1

    finally:
        for name, module in saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    print("PASS: dashboard mqtt module has no import-time side effects and publishes only from main()")


if __name__ == "__main__":
    test_periodic_board_capture_imports_cleanly()
    test_dashboard_mqtt_import_has_no_side_effects()
    print("\nAll script entrypoint tests passed.")
