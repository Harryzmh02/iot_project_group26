"""

Data flow:
  Pi Camera → frame stability check → image preprocessing
      → CV subsystem (Ashish) → Arduino feedback (Harry) + MQTT publish (Jason)

CV and MQTT calls go through thin interface functions defined at the bottom
of this file. Ashish and Jason fill those in on their branches; the
signatures here must not change without coordinating with them.
"""

import time
import numpy as np
from picamera2 import Picamera2

from frame_stability import FrameStabilityChecker
from image_preprocessing import preprocess_frame
from arduino_feedback_client import ArduinoFeedbackClient


# ── tuneable constants ────────────────────────────────────────────────────────
CAPTURE_INTERVAL_SECONDS = 1.0
STABLE_FRAMES_REQUIRED = 3
DIFF_THRESHOLD = 5.0
ARDUINO_PORT = "/dev/ttyACM0"


# ── CV subsystem interface (Ashish fills this in) ─────────────────────────────
def run_cv_pipeline(frame: np.ndarray, board_corners: list | None) -> dict | None:
    """
    Pass a preprocessed frame to the CV subsystem.

    Expected return value:
        {
            "player":   "black" | "white",
            "row":      int,          # 0-indexed
            "col":      int,          # 0-indexed
            "move_num": int,
            "board":    list[list[int]]  # 15x15 matrix
        }
    Returns None when no new move is detected.

    TODO (Ashish): replace the stub body with the real OpenCV call.
    """
    return None  # stub


# ── MQTT subsystem interface (Jason fills this in) ────────────────────────────
def publish_move(move: dict) -> None:
    """
    Publish a detected move to the MQTT broker.

    `move` has the same shape as the dict returned by run_cv_pipeline,
    plus a "timestamp" key added by this pipeline before calling.

    TODO (Jason): replace the stub body with paho-mqtt publish.
    """
    pass  # stub


# ── pipeline loop ─────────────────────────────────────────────────────────────
def main():
    camera = Picamera2()
    stability = FrameStabilityChecker(
        required_stable_frames=STABLE_FRAMES_REQUIRED,
        diff_threshold=DIFF_THRESHOLD,
    )
    arduino = ArduinoFeedbackClient(port=ARDUINO_PORT)

    board_corners = None  # set after Ashish's calibration step runs

    arduino_ok = arduino.connect()
    if not arduino_ok:
        print("[Pipeline] Arduino not connected — feedback LEDs disabled.")

    camera.start()
    time.sleep(2)
    print("[Pipeline] Started. Waiting for stable board frames...")

    try:
        while True:
            raw_frame: np.ndarray = camera.capture_array()

            if not stability.update(raw_frame):
                time.sleep(CAPTURE_INTERVAL_SECONDS)
                continue

            # Stable scene confirmed — process it
            stability.reset()
            frame = preprocess_frame(raw_frame)

            move = run_cv_pipeline(frame, board_corners)
            if move is None:
                time.sleep(CAPTURE_INTERVAL_SECONDS)
                continue

            move["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            print(f"[Pipeline] Move detected: {move}")

            # Arduino LED + buzzer feedback
            if arduino_ok:
                if move["player"] == "black":
                    arduino.black_move()
                elif move["player"] == "white":
                    arduino.white_move()

            # MQTT publish
            publish_move(move)

            time.sleep(CAPTURE_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("[Pipeline] Stopped by user.")

    finally:
        camera.stop()
        arduino.close()


if __name__ == "__main__":
    main()
