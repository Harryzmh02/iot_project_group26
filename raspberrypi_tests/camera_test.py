from picamera2 import Picamera2
import time


def main() -> None:
    camera = Picamera2()

    try:
        camera.start()
        time.sleep(2)
        output_file = "board_test.jpg"
        camera.capture_file(output_file)
        print(f"Saved camera test image: {output_file}")
    finally:
        camera.stop()


if __name__ == "__main__":
    main()