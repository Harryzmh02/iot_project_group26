from picamera2 import Picamera2
from datetime import datetime
from pathlib import Path
import numpy as np
import time

from frame_stability import FrameStabilityChecker


OUTPUT_DIR = Path("captured_frames")
CAPTURE_INTERVAL_SECONDS = 1
TOTAL_CAPTURES = 20


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    camera = Picamera2()
    stability = FrameStabilityChecker(required_stable_frames=3, diff_threshold=5.0)

    try:
        camera.start()
        time.sleep(2)

        saved = 0
        attempts = 0

        while saved < TOTAL_CAPTURES:
            frame: np.ndarray = camera.capture_array()
            attempts += 1

            if stability.update(frame):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = OUTPUT_DIR / f"board_{timestamp}.jpg"

                camera.capture_file(str(output_path))
                print(f"[{saved + 1}/{TOTAL_CAPTURES}] Stable frame saved: {output_path}")

                saved += 1
                stability.reset()

            time.sleep(CAPTURE_INTERVAL_SECONDS)

        print(f"Done. {saved} stable frames saved after {attempts} capture attempts.")

    finally:
        camera.stop()


if __name__ == "__main__":
    main()