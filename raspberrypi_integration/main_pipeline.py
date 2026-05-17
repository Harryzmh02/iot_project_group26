"""
Data flow:
  Pi Camera → frame stability check → image preprocessing
      → CV subsystem (Ashish) → Arduino feedback (Harry) + MQTT publish (Jason)
"""

import sys
import os
import json
import time
import numpy as np
import paho.mqtt.client as mqtt
from datetime import datetime
from picamera2 import Picamera2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'raspberrypi_capture'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'computer_vision'))

from frame_stability import FrameStabilityChecker
from image_preprocessing import preprocess_frame
from arduino_feedback_client import ArduinoFeedbackClient
from gomoku_cv import process_frame, compute_delta, parse_corners


# ── tuneable constants ────────────────────────────────────────────────────────
CAPTURE_INTERVAL_SECONDS = 1.0
STABLE_FRAMES_REQUIRED = 3
DIFF_THRESHOLD = 5.0
ARDUINO_PORT = "/dev/ttyACM0"
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "gomoku/move"

# Set to a corner string after calibration: "tlx,tly,trx,try,brx,bry,blx,bly"
BOARD_CORNERS = None


# ── CV state ──────────────────────────────────────────────────────────────────
_old_board = np.zeros((15, 15), dtype=np.uint8)


def run_cv_pipeline(frame: np.ndarray, board_corners):
    global _old_board
    corners = parse_corners(board_corners) if isinstance(board_corners, str) else board_corners
    board, _, _, _, _ = process_frame(frame, corners)
    changes = compute_delta(_old_board, board)
    _old_board = board.copy()

    new_moves = [c for c in changes if c["type"] == "new_move"]
    if len(new_moves) != 1 or len(changes) != len(new_moves):
        return None

    m = new_moves[0]
    return {"player": m["color"], "row": m["row"], "col": m["col"]}


# ── MQTT state ────────────────────────────────────────────────────────────────
_mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
_move_number = 0


def publish_move(move: dict) -> None:
    global _move_number
    _move_number += 1
    payload = json.dumps({
        **move,
        "move_number": _move_number,
        "timestamp": datetime.now().isoformat(),
    })
    _mqtt_client.publish(MQTT_TOPIC, payload)
    print(f"[MQTT] Published: {payload}")


# ── pipeline loop ─────────────────────────────────────────────────────────────
def main():
    camera = Picamera2()
    stability = FrameStabilityChecker(
        required_stable_frames=STABLE_FRAMES_REQUIRED,
        diff_threshold=DIFF_THRESHOLD,
    )
    arduino = ArduinoFeedbackClient(port=ARDUINO_PORT)

    arduino_ok = arduino.connect()
    if not arduino_ok:
        print("[Pipeline] Arduino not connected — feedback LEDs disabled.")

    try:
        _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        _mqtt_client.loop_start()
        print(f"[Pipeline] MQTT connected to {MQTT_BROKER}:{MQTT_PORT}")
    except Exception as exc:
        print(f"[Pipeline] MQTT connection failed: {exc} — moves will not be published.")

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
            frame = preprocess_frame(raw_frame)

            move = run_cv_pipeline(frame, BOARD_CORNERS)
            if move is None:
                time.sleep(CAPTURE_INTERVAL_SECONDS)
                continue

            print(f"[Pipeline] Move detected: {move}")

            if arduino_ok:
                if move["player"] == "black":
                    arduino.black_move()
                elif move["player"] == "white":
                    arduino.white_move()

            # Convert 0-indexed → 1-indexed and col → column for Jason's format
            publish_move({
                "player": move["player"],
                "row":    move["row"] + 1,
                "column": move["col"] + 1,
            })

            time.sleep(CAPTURE_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("[Pipeline] Stopped by user.")

    finally:
        camera.stop()
        arduino.close()
        _mqtt_client.loop_stop()
        _mqtt_client.disconnect()


if __name__ == "__main__":
    main()
