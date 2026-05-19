import time

try:
    import serial
except ImportError:
    serial = None


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
        if serial is None:
            print("[Arduino] pyserial not installed; feedback disabled.")
            self.serial_conn = None
            return False
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

        except Exception as exc:
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

        try:
            self.serial_conn.write(command.encode())
            time.sleep(0.3)
            reply = self.serial_conn.readline().decode(errors="ignore").strip()
            return reply or f"ACK timeout for {command}"
        except Exception as exc:
            print(f"[Arduino] Failed to send {command}: {exc}")
            return f"ERROR:{command}"

    def black_move(self):
        return self._send_command("B")

    def white_move(self):
        return self._send_command("W")

    def error(self):
        return self._send_command("E")

    def reset(self):
        return self._send_command("R")

    def close(self):
        if self.serial_conn is not None:
            try:
                self.serial_conn.close()
            except Exception as exc:
                print(f"[Arduino] Close failed: {exc}")
            self.serial_conn = None
