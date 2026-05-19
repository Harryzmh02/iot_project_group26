"""
Production Raspberry Pi pipeline for the Smart Gomoku board.

Data flow:
  Pi Camera -> frame stability -> preprocessing/warp -> 15x15 CV state
  -> one-move validation -> Arduino feedback -> MQTT dashboard publish.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

import numpy as np

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "raspberrypi_capture"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "computer_vision"))

from arduino_feedback_client import ArduinoFeedbackClient
from frame_stability import FrameStabilityChecker
from gomoku_cv import compute_delta, parse_corners, process_frame
from image_preprocessing import preprocess_frame

try:
    from gomoku_cv import TemporalMoveConfirmor, validate_single_move
except ImportError:
    def validate_single_move(changes, last_published=None):
        if not changes:
            return None, "no board change"
        new_moves = [change for change in changes if change["type"] == "new_move"]
        uncertain = [change for change in changes if change["type"] != "new_move"]
        if uncertain or len(new_moves) != 1:
            return None, "ambiguous board change"
        move = new_moves[0]
        key = (move["row"], move["col"], move["color"])
        if last_published == key:
            return None, "duplicate move"
        return move, "valid move"

    class TemporalMoveConfirmor:
        def __init__(self, required_frames=2):
            self.required_frames = required_frames
            self.pending_key = None
            self.pending_count = 0
            self.last_published = None

        def update(self, move):
            key = (move["row"], move["col"], move["color"])
            if key == self.pending_key:
                self.pending_count += 1
            else:
                self.pending_key = key
                self.pending_count = 1
            if self.pending_count >= self.required_frames:
                self.last_published = key
                self.pending_key = None
                self.pending_count = 0
                return True
            return False


CAPTURE_INTERVAL_SECONDS = 1.0
STABLE_FRAMES_REQUIRED = 3
DIFF_THRESHOLD = 5.0
ARDUINO_PORT = "/dev/ttyACM0"
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "gomoku/move"
BOARD_CORNERS = None


_old_board = np.zeros((15, 15), dtype=np.uint8)
_move_number = 0
_last_published_key = None


class _NullMQTTClient:
    def publish(self, topic, payload):
        print(f"[MQTT] Offline, not published to {topic}: {payload}")

    def loop_stop(self):
        pass

    def disconnect(self):
        pass


if mqtt is not None:
    try:
        _mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except Exception:
        _mqtt_client = mqtt.Client()
else:
    _mqtt_client = _NullMQTTClient()


def _coerce_corners(board_corners):
    if isinstance(board_corners, str):
        try:
            return parse_corners(board_corners)
        except ValueError as exc:
            print(f"[Pipeline] Bad board corners: {exc}; using fallback resize.")
            return None
    return board_corners


def run_cv_pipeline(frame: np.ndarray, board_corners):
    """Test-friendly one-frame CV adapter. Production loop adds temporal confirmation."""
    global _old_board
    corners = _coerce_corners(board_corners)
    board, _, _, _, _ = process_frame(frame, corners)
    changes = compute_delta(_old_board, board)
    _old_board = board.copy()

    move, reason = validate_single_move(changes)
    if move is None:
        if changes:
            print(f"[Pipeline] Rejected CV delta: {reason}")
        return None
    return {"player": move["color"], "row": move["row"], "col": move["col"]}


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


def connect_mqtt(enabled: bool, broker: str, port: int):
    if not enabled:
        print("[Pipeline] MQTT disabled.")
        return False
    if mqtt is None:
        print("[Pipeline] paho-mqtt not installed; MQTT disabled.")
        return False
    try:
        _mqtt_client.connect(broker, port, 60)
        _mqtt_client.loop_start()
        print(f"[Pipeline] MQTT connected to {broker}:{port}")
        return True
    except Exception as exc:
        print(f"[Pipeline] MQTT connection failed: {exc}; continuing without dashboard publish.")
        return False


def open_camera():
    if Picamera2 is None:
        raise RuntimeError("Picamera2 is not available. Install picamera2 or run gomoku_cv.py --image for offline testing.")
    camera = Picamera2()
    config = camera.create_preview_configuration(main={"format": "RGB888", "size": (1280, 720)})
    camera.configure(config)
    camera.start()
    time.sleep(2)
    return camera


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run Smart Gomoku Raspberry Pi production pipeline")
    parser.add_argument("--corners", default=BOARD_CORNERS, help="tlx,tly,trx,try,brx,bry,blx,bly calibration corners")
    parser.add_argument("--arduino-port", default=ARDUINO_PORT)
    parser.add_argument("--feedback", action="store_true", default=True, help="Enable Arduino feedback")
    parser.add_argument("--no-feedback", action="store_false", dest="feedback", help="Disable Arduino feedback")
    parser.add_argument("--mqtt", action="store_true", default=True, help="Enable MQTT publish")
    parser.add_argument("--no-mqtt", action="store_false", dest="mqtt", help="Disable MQTT publish")
    parser.add_argument("--mqtt-broker", default=MQTT_BROKER)
    parser.add_argument("--mqtt-port", type=int, default=MQTT_PORT)
    parser.add_argument("--stable-frames", type=int, default=STABLE_FRAMES_REQUIRED)
    parser.add_argument("--diff-threshold", type=float, default=DIFF_THRESHOLD)
    parser.add_argument("--capture-interval", type=float, default=CAPTURE_INTERVAL_SECONDS)
    parser.add_argument("--confirm-frames", type=int, default=2)
    args = parser.parse_args(argv)

    global _old_board, _last_published_key
    corners = _coerce_corners(args.corners)
    stability = FrameStabilityChecker(args.stable_frames, args.diff_threshold)
    confirmor = TemporalMoveConfirmor(required_frames=args.confirm_frames)
    arduino = ArduinoFeedbackClient(port=args.arduino_port)

    arduino_ok = args.feedback and arduino.connect()
    if args.feedback and not arduino_ok:
        print("[Pipeline] Arduino not connected; feedback LEDs disabled.")
    mqtt_ok = connect_mqtt(args.mqtt, args.mqtt_broker, args.mqtt_port)

    try:
        camera = open_camera()
    except Exception as exc:
        print(f"[Pipeline] Camera startup failed: {exc}")
        if arduino_ok:
            arduino.close()
        return 2

    print("[Pipeline] Started. Place one stone at a time after the frame is stable.")
    try:
        while True:
            rgb_frame = camera.capture_array()
            raw_frame = rgb_frame[:, :, ::-1].copy()

            if not stability.update(raw_frame):
                time.sleep(args.capture_interval)
                continue

            frame = preprocess_frame(raw_frame)
            board, _, _, _, _ = process_frame(frame, corners)
            changes = compute_delta(_old_board, board)
            move, reason = validate_single_move(changes, last_published=_last_published_key)

            if move is None:
                if changes:
                    print(f"[Pipeline] Rejected detection: {reason}")
                    if arduino_ok:
                        print(f"[Arduino] {arduino.error()}")
                stability.reset()
                time.sleep(args.capture_interval)
                continue

            if not confirmor.update(move):
                print(f"[Pipeline] Candidate needs confirmation: {move}")
                stability.reset()
                time.sleep(args.capture_interval)
                continue

            print(f"[Pipeline] Move detected: {move}")
            if arduino_ok:
                reply = arduino.black_move() if move["color"] == "black" else arduino.white_move()
                print(f"[Arduino] {reply}")

            if mqtt_ok:
                publish_move({"player": move["color"], "row": move["row"] + 1, "column": move["col"] + 1})

            _old_board = board.copy()
            _last_published_key = (move["row"], move["col"], move["color"])
            stability.reset()
            time.sleep(args.capture_interval)

    except KeyboardInterrupt:
        print("[Pipeline] Stopped by user.")
    finally:
        try:
            camera.stop()
        except Exception:
            pass
        arduino.close()
        _mqtt_client.loop_stop()
        try:
            _mqtt_client.disconnect()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
