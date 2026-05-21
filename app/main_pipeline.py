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
    BLACK,
    BOARD_SIZE,
    WHITE,
    compute_delta,
    detect_marker_corners,
    parse_corners,
    process_frame,
)


CAPTURE_INTERVAL_SECONDS = 1.0
STABLE_FRAMES_REQUIRED = 3
ARDUINO_PORT = "/dev/ttyACM0"
MQTT_BROKER = "192.168.0.235"
MQTT_PORT = 1883
MQTT_TOPIC = "gomoku/move"

# Set to a corner string after calibration: "tlx,tly,trx,try,brx,bry,blx,bly"
BOARD_CORNERS = None


_old_board = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.uint8)
_mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
_mqtt_success_code = getattr(mqtt, "MQTT_ERR_SUCCESS", 0)
_mqtt_connected = False
_move_number = 0
_last_good_corners = None
_current_turn = "black"
_game_over = False
_winner = None


def check_winner(board: np.ndarray):
    """Return 'black' or 'white' if the current board has five in a row."""
    directions = [
        (0, 1),   # horizontal
        (1, 0),   # vertical
        (1, 1),   # diagonal down-right
        (1, -1),  # diagonal down-left
    ]

    for row in range(BOARD_SIZE):
        for col in range(BOARD_SIZE):
            value = int(board[row, col])
            if value == 0:
                continue

            for dr, dc in directions:
                count = 1

                r, c = row + dr, col + dc
                while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and int(board[r, c]) == value:
                    count += 1
                    r += dr
                    c += dc

                r, c = row - dr, col - dc
                while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and int(board[r, c]) == value:
                    count += 1
                    r -= dr
                    c -= dc

                if count >= 5:
                    return "black" if value == BLACK else "white"

    return None


def next_player(player: str) -> str:
    return "white" if player == "black" else "black"


def resolve_corners(frame: np.ndarray, configured_corners):
    """ArUco-first corner resolution. Falls back to the last successful detection
    so transient marker occlusion doesn't blank out the pipeline."""
    global _last_good_corners

    if configured_corners is not None:
        corners = (
            parse_corners(configured_corners)
            if isinstance(configured_corners, str)
            else configured_corners
        )
        _last_good_corners = np.array(corners, dtype=np.float32)
        return _last_good_corners

    detected = detect_marker_corners(frame)
    if detected is not None:
        _last_good_corners = detected
        return _last_good_corners

    return _last_good_corners


def run_cv_pipeline(frame: np.ndarray, board_corners):
    global _old_board

    corners = resolve_corners(frame, board_corners)
    if corners is None:
        return None
    board, _, result_image, _, _ = process_frame(frame, corners)

    cv2.imshow("Gomoku CV Preview", result_image)
    cv2.waitKey(1)

    changes = compute_delta(_old_board, board)

    # Merge: only add stones, never remove confirmed ones (prevents re-detection flicker)
    merged = _old_board.copy()
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            if board[r, c] != 0:
                merged[r, c] = board[r, c]
    _old_board = merged

    new_moves = [change for change in changes if change["type"] == "new_move"]
    if len(new_moves) != 1:
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
            "next_turn": _current_turn,
            "winner": _winner,
            "game_over": _game_over,
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
    global _mqtt_connected, _current_turn, _game_over, _winner

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
        print("[Pipeline] No BOARD_CORNERS set — ArUco markers will be detected per-frame.")

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

            if _game_over:
                print("[Pipeline] Game is already over. Ignoring new moves until reset/restart.")
                continue

            print(f"[Pipeline] Move detected: {move}")

            if move["player"] != _current_turn:
                print(f"[Pipeline] Invalid turn: expected {_current_turn}, got {move['player']}")
                if arduino_ok:
                    arduino.error()
                continue

            _winner = check_winner(_old_board)
            _game_over = _winner is not None
            _current_turn = "Game over" if _game_over else next_player(move["player"])

            if arduino_ok:
                if _game_over:
                    arduino.game_over()
                elif move["player"] == "black":
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

