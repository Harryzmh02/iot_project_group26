"""
Data flow:
  Pi Camera -> frame stability check -> CV processing
      -> Arduino feedback + MQTT publish
"""

import json
import time
from datetime import datetime

import numpy as np
import paho.mqtt.client as mqtt

try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None

from arduino_feedback_client import ArduinoFeedbackClient
from frame_stability import FrameStabilityChecker
from gomoku_cv import compute_delta, parse_corners, process_frame


CAPTURE_INTERVAL_SECONDS = 1.0
STABLE_FRAMES_REQUIRED = 3
DIFF_THRESHOLD = 5.0
ARDUINO_PORT = "/dev/ttyACM0"
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "gomoku/move"

# Set to a corner string after calibration: "tlx,tly,trx,try,brx,bry,blx,bly"
BOARD_CORNERS = None


_old_board = np.zeros((15, 15), dtype=np.uint8)
_mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
_mqtt_success_code = getattr(mqtt, "MQTT_ERR_SUCCESS", 0)
_mqtt_connected = False
_move_number = 0


def run_cv_pipeline(frame: np.ndarray, board_corners):
    global _old_board

    corners = parse_corners(board_corners) if isinstance(board_corners, str) else board_corners
    board, _, _, _, _ = process_frame(frame, corners)
    changes = compute_delta(_old_board, board)
    _old_board = board.copy()

    new_moves = [change for change in changes if change["type"] == "new_move"]
    if len(new_moves) != 1 or len(changes) != len(new_moves):
        return None

    move = new_moves[0]
    return {"player": move["color"], "row": move["row"], "col": move["col"]}


def publish_move(move: dict) -> bool:
    global _move_number

    if not _mqtt_connected:
        print(f"[MQTT] Skipped publish because client is not connected: {move}")
        return False

    next_move_number = _move_number + 1
    payload = json.dumps(
        {
            **move,
            "move_number": next_move_number,
            "timestamp": datetime.now().isoformat(),
        }
    )

    result = _mqtt_client.publish(MQTT_TOPIC, payload)
    rc = getattr(result, "rc", _mqtt_success_code)
    if rc != _mqtt_success_code:
        print(f"[MQTT] Publish failed with rc={rc}: {payload}")
        return False

    _move_number = next_move_number
    print(f"[MQTT] Published: {payload}")
    return True


def main():
    global _mqtt_connected

    if Picamera2 is None:
        raise RuntimeError(
            "Picamera2 is not installed. Run this pipeline on a Raspberry Pi with picamera2 available."
        )

    camera = Picamera2()
    stability = FrameStabilityChecker(
        required_stable_frames=STABLE_FRAMES_REQUIRED,
        diff_threshold=DIFF_THRESHOLD,
    )
    arduino = ArduinoFeedbackClient(port=ARDUINO_PORT)

    arduino_ok = arduino.connect()
    if not arduino_ok:
        print("[Pipeline] Arduino not connected - feedback LEDs disabled.")

    try:
        _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        _mqtt_client.loop_start()
        _mqtt_connected = True
        print(f"[Pipeline] MQTT connected to {MQTT_BROKER}:{MQTT_PORT}")
    except Exception as exc:
        _mqtt_connected = False
        print(f"[Pipeline] MQTT connection failed: {exc} - moves will not be published.")

    camera.start()
    time.sleep(2)
    print("[Pipeline] Started. Waiting for stable board frames...")

    try:
        while True:
            raw_frame: np.ndarray = camera.capture_array()

            if not stability.update(raw_frame):
                time.sleep(CAPTURE_INTERVAL_SECONDS)
                continue

            stability.reset()
            move = run_cv_pipeline(raw_frame, BOARD_CORNERS)
            if move is None:
                time.sleep(CAPTURE_INTERVAL_SECONDS)
                continue

            print(f"[Pipeline] Move detected: {move}")

            if arduino_ok:
                if move["player"] == "black":
                    arduino.black_move()
                elif move["player"] == "white":
                    arduino.white_move()

            # Convert 0-indexed board coordinates to the 1-indexed dashboard contract.
            publish_move(
                {
                    "player": move["player"],
                    "row": move["row"] + 1,
                    "column": move["col"] + 1,
                }
            )

            time.sleep(CAPTURE_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("[Pipeline] Stopped by user.")

    finally:
        camera.stop()
        arduino.close()
        _mqtt_client.loop_stop()
        _mqtt_client.disconnect()
        _mqtt_connected = False


if __name__ == "__main__":
    main()
