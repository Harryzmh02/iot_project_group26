from picamera2 import Picamera2
from datetime import datetime
from pathlib import Path
import time


OUTPUT_DIR = Path("captured_frames")
CAPTURE_INTERVAL_SECONDS = 3
TOTAL_CAPTURES = 10


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    camera = Picamera2()

    try:
        camera.start()
        time.sleep(2)

        for i in range(TOTAL_CAPTURES):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = OUTPUT_DIR / f"board_{timestamp}.jpg"

            camera.capture_file(str(output_path))
            print(f"[{i + 1}/{TOTAL_CAPTURES}] Saved {output_path}")

            time.sleep(CAPTURE_INTERVAL_SECONDS)

    finally:
        camera.stop()


if __name__ == "__main__":
    main()