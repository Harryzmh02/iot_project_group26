import serial
import time

PORT = "/dev/ttyACM0"
BAUD = 9600


def main() -> None:
    try:
        arduino = serial.Serial(PORT, BAUD, timeout=1)
        time.sleep(2)

        startup_message = arduino.readline().decode(errors="ignore").strip()
        if startup_message:
            print("Startup:", startup_message)

        commands = [b"B", b"W", b"E", b"R"]

        for command in commands:
            decoded_command = command.decode()
            print(f"Sending: {decoded_command}")

            arduino.write(command)
            time.sleep(0.5)

            response = arduino.readline().decode(errors="ignore").strip()
            print("Arduino replied:", response)

        arduino.close()
        print("Serial test complete.")

    except serial.SerialException as exc:
        print("Serial connection failed:", exc)


if __name__ == "__main__":
    main()