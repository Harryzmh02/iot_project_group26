import time
from arduino_feedback_client import ArduinoFeedbackClient


def main():
    feedback = ArduinoFeedbackClient()

    if not feedback.connect():
        return

    try:
        print("Black move:", feedback.black_move())
        time.sleep(1)

        print("White move:", feedback.white_move())
        time.sleep(1)

        print("Error:", feedback.error())
        time.sleep(1)

        print("Reset:", feedback.reset())

    finally:
        feedback.close()


if __name__ == "__main__":
    main()