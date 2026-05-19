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
from gomoku_cv import (
    BOARD_SIZE,
    auto_detect_corners,
    compute_delta,
    detect_marker_corners,
    parse_corners,
    process_frame,
)


CAPTURE_INTERVAL_SECONDS = 1.0
STABLE_FRAMES_REQUIRED = 3
ARDUINO_PORT = "/dev/ttyACM0"
MQTT_BROKER = "172.20.10.3"
MQTT_PORT = 1883
MQTT_TOPIC = "gomoku/move"

# Override corners manually if ArUco fails: "tlx,tly,trx,try,brx,bry,blx,bly"
BOARD_CORNERS = None


_old_board = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.uint8)
_mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
_mqtt_success_code = getattr(mqtt, "MQTT_ERR_SUCCESS", 0)
_mqtt_connected = False
_move_number = 0
_last_good_corners = None


def resolve_corners(frame: np.ndarray):
    """Return board corners for this frame.

    Priority:
      1. BOARD_CORNERS string override
      2. ArUco markers (live, cached between frames so brief occlusion is OK)
      3. Last cached corners from a previous successful ArUco detection
    """
    global _last_good_corners

    if BOARD_CORNERS is not None:
        return parse_corners(BOARD_CORNERS) if isinstance(BOARD_CORNERS, str) else BOARD_CORNERS

    detected = detect_marker_corners(frame)
    if detected is not None:
        _last_good_corners = detected

    return _last_good_corners


def run_cv_pipeline(frame: np.ndarray):
    global _old_board

    corners = resolve_corners(frame)
    if corners is None:
        print("[Pipeline] No corners — skipping frame.")
        return None

    board, _, result_image, _, _ = process_frame(frame, corners)

    cv2.imshow("Gomoku CV Preview", result_image)
    cv2.waitKey(1)

    changes = compute_delta(_old_board, board)

    # Merge: only add stones, never remove confirmed ones (prevents flicker)
    merged = _old_board.copy()
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            if board[r, c] != 0:
                merged[r, c] = board[r, c]
    _old_board = merged

    new_moves = [ch for ch in changes if ch["type"] == "new_move"]
    if len(new_moves) != 1:
        return None

    move = new_moves[0]
    return {"player": move["color"], "row": move["row"], "col": move["col"]}


def publish_move(move: dict) -> bool:
    global _move_number

    if not _mqtt_connected:
        print(f"[MQTT] Skipped (not connected): {move}")
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
        print(f"[MQTT] Publish failed rc={rc}: {payload}")
        return False

    _move_number = next_move_number
    print(f"[MQTT] Published: {payload}")
    return True


def main():
    global _mqtt_connected, _last_good_corners

    if Picamera2 is None:
        raise RuntimeError(
            "Picamera2 is not installed. Run this pipeline on a Raspberry Pi with picamera2 available."
        )

    camera = Picamera2()
    config = camera.create_preview_configuration(main={"format": "RGB888", "size": (1280, 720)})
    camera.configure(config)

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
    print("[Pipeline] Started. Looking for ArUco markers...")

    # Try to seed corners before the main loop
    seed_rgb = camera.capture_array()
    seed_frame = cv2.cvtColor(seed_rgb, cv2.COLOR_RGB2BGR)
    seed_corners = detect_marker_corners(seed_frame)
    if seed_corners is not None:
        _last_good_corners = seed_corners
        print(f"[Pipeline] ArUco markers found: {seed_corners.tolist()}")
    else:
        print("[Pipeline] ArUco not found — trying line auto-detection...")
        fallback = auto_detect_corners(seed_frame)
        if fallback is not None:
            _last_good_corners = fallback
            print(f"[Pipeline] Auto-detected corners: {fallback.tolist()}")
        else:
            print("[Pipeline] No corners found — will retry each frame.")

    consecutive_same = 0
    last_board_state = _old_board.copy()
    pending_move = None

    try:
        while True:
            rgb_frame: np.ndarray = camera.capture_array()
            raw_frame = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)
            time.sleep(CAPTURE_INTERVAL_SECONDS)

            move = run_cv_pipeline(raw_frame)
            current_state = _old_board.copy()

            if np.array_equal(current_state, last_board_state):
                consecutive_same += 1
            else:
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
