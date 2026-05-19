"""
Data flow:
  Pi Camera -> frame stability check -> CV processing
      -> Arduino feedback + MQTT publish
"""

import json
import time
from datetime import datetime

import cv2
import numpy as np
import paho.mqtt.client as mqtt

try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None

from arduino_feedback_client import ArduinoFeedbackClient
from gomoku_cv import auto_detect_corners, compute_delta, parse_corners, process_frame


CAPTURE_INTERVAL_SECONDS = 1.0
STABLE_FRAMES_REQUIRED = 3
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
    board, _, result_image, _, _ = process_frame(frame, corners)

    cv2.imshow("Gomoku CV Preview", result_image)
    cv2.waitKey(1)

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

    active_corners = parse_corners(BOARD_CORNERS) if BOARD_CORNERS else None
    if active_corners is None:
        print("[Pipeline] No BOARD_CORNERS set — attempting auto-detection from first frame...")
        _seed_frame = camera.capture_array()
        active_corners = auto_detect_corners(_seed_frame)
        if active_corners is not None:
            print(f"[Pipeline] Board corners auto-detected: {active_corners.tolist()}")
        else:
            print("[Pipeline] Auto-detection failed — running without perspective warp.")

    consecutive_same = 0
    last_board_state = _old_board.copy()
    pending_move = None

    try:
        while True:
            raw_frame: np.ndarray = camera.capture_array()
            time.sleep(CAPTURE_INTERVAL_SECONDS)

            move = run_cv_pipeline(raw_frame, active_corners)
            current_state = _old_board.copy()

            if np.array_equal(current_state, last_board_state):
                consecutive_same += 1
            else:
                # Board state changed — save the triggering move and start counting
                consecutive_same = 1
                last_board_state = current_state
                if move is not None:
                    pending_move = move

            if consecutive_same < STABLE_FRAMES_REQUIRED or pending_move is None:
                continue

            move = pending_move
            pending_move = None
            consecutive_same = 0

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
