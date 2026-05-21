import time
import serial


class ArduinoFeedbackClient:
    """
    Simple Raspberry Pi -> Arduino serial client for the
    Smart Gomoku feedback module.
    """

    def __init__(self, port="/dev/ttyACM0", baudrate=9600, timeout=1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_conn = None

    def connect(self):
        """Open serial connection and clear Arduino startup message."""
        try:
            self.serial_conn = serial.Serial(
                self.port,
                self.baudrate,
                timeout=self.timeout
            )

            # Arduino Uno often resets when serial is opened
            time.sleep(2)

            startup_message = self.serial_conn.readline().decode(
                errors="ignore"
            ).strip()

            if startup_message:
                print(f"[Arduino] {startup_message}")

            return True

        except serial.SerialException as exc:
            print(f"[Arduino] Serial connection failed: {exc}")
            self.serial_conn = None
            return False

    def _send_command(self, command: str):
        """
        Send one-byte command and return Arduino reply.
        """
        if self.serial_conn is None:
            raise RuntimeError("Arduino serial connection is not open.")

        if len(command) != 1:
            raise ValueError("Command must be a single character.")

        self.serial_conn.write(command.encode())
        time.sleep(0.3)

        reply = self.serial_conn.readline().decode(
            errors="ignore"
        ).strip()

        return reply

    def black_move(self):
        return self._send_command("B")

    def white_move(self):
        return self._send_command("W")

    def error(self):
        return self._send_command("E")

    def reset(self):
        return self._send_command("R")

    def game_over(self):
        return self._send_command("G")

    def close(self):
        if self.serial_conn is not None:
            self.serial_conn.close()
            self.serial_conn = None

