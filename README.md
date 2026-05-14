# Smart Gomoku Board State Monitoring System

## Current Hardware and Interface Progress

This document summarises the current hardware setup, Arduino feedback module, Raspberry Pi test scripts, and the serial communication interface prepared for later integration with the computer vision and game-state subsystems.

---

## 1. Current Prototype Hardware

The current physical prototype uses:

- Raspberry Pi 3 Model B
- Raspberry Pi Camera Module
- Arduino Uno
- Breadboards
- Jumper wires
- LEDs
- Resistors
- Passive buzzer, if available
- Gomoku board and black/white pieces

> Note: The project proposal previously referred to a Raspberry Pi 4. The actual board currently used in the prototype is a **Raspberry Pi 3 Model B**.

---

## 2. Current Repository Structure

```text
hardware/
  wiring_notes.md

arduino_feedback/
  gomoku_feedback.ino

raspberrypi_tests/
  camera_test.py
  pi_to_arduino_test.py

sample_images/
  empty_board.jpg
  black_center.jpg
  white_center.jpg
  mixed_board.jpg
```

---

## 3. Completed Work So Far

### Hardware Preparation

- Raspberry Pi 3 and Pi Camera Module have been prepared for overhead board image capture.
- Arduino Uno has been prepared as a dedicated physical feedback controller.
- Basic breadboard wiring for LEDs and buzzer has been planned and documented.
- Common ground wiring has been confirmed:
  - Arduino `GND` is connected to the breadboard ground rail.
  - All LED and buzzer ground returns connect to the same shared ground rail.

### Arduino Feedback Module

The Arduino feedback module has been implemented and tested.

It listens for single-byte commands over USB serial and responds with:

- LED feedback
- Buzzer feedback
- Serial acknowledgment messages

### Raspberry Pi to Arduino Serial Communication

USB serial communication between the Raspberry Pi 3 and Arduino Uno has been successfully tested.

Example test output:

```text
Startup: Arduino feedback module ready
Sending: B
Arduino replied: ACK:B
Sending: W
Arduino replied: ACK:W
Sending: E
Arduino replied: ACK:E
Sending: R
Arduino replied: ACK:R
Serial test complete.
```

---

## 4. Serial Command Protocol

The Raspberry Pi sends a single-byte command to the Arduino.

| Command | Meaning | Arduino Behaviour | Serial Reply |
|---|---|---|---|
| `B` | Black move detected | Black-side LED feedback and short beep | `ACK:B` |
| `W` | White move detected | White-side LED feedback and short beep | `ACK:W` |
| `E` | Error or invalid detection state | Error flash pattern and error beep | `ACK:E` |
| `R` | Reset feedback state | Turns off feedback LEDs | `ACK:R` |

This protocol is intended to be called by the Raspberry Pi vision or game-state subsystem after a board-state update has been identified.

---

## 5. Arduino Feedback Module

### File

```text
arduino_feedback/gomoku_feedback.ino
```

### Current Behaviour

#### `B` — Black Move Detected
- Turns on black feedback LED
- Turns off white feedback LED
- Plays a short beep

#### `W` — White Move Detected
- Turns on white feedback LED
- Turns off black feedback LED
- Plays a short beep

#### `E` — Error / Invalid State
- Flashes both LEDs
- Plays an error beep pattern
- Resets the LED state afterward

#### `R` — Reset
- Turns off all feedback LEDs

---

## 6. Arduino Wiring Summary

### Common Ground

```text
Arduino GND -> Breadboard negative rail
```

All component ground connections return to this breadboard ground rail.

### Black Move LED

```text
Arduino D8 -> 220Ω resistor -> LED anode
LED cathode -> GND rail
```

### White Move LED

```text
Arduino D9 -> 220Ω resistor -> LED anode
LED cathode -> GND rail
```

### Buzzer

```text
Arduino D6 -> buzzer positive terminal
Buzzer negative terminal -> GND rail
```

More detailed notes are stored in:

```text
hardware/wiring_notes.md
```

---

## 7. Raspberry Pi Camera Test

### File

```text
raspberrypi_tests/camera_test.py
```

### Purpose

This script verifies that:

- The Raspberry Pi Camera Module is detected
- The camera can capture an image successfully
- A board image can be generated for future computer vision testing

### Run

```bash
python3 raspberrypi_tests/camera_test.py
```

### Expected Output

```text
Saved camera test image: board_test.jpg
```

---

## 8. Raspberry Pi to Arduino Serial Test

### File

```text
raspberrypi_tests/pi_to_arduino_test.py
```

### Purpose

This script verifies that:

- Raspberry Pi can detect the Arduino serial port
- Raspberry Pi can send serial commands
- Arduino can receive commands and send acknowledgment responses

### Typical Arduino Port

```text
/dev/ttyACM0
```

### Run

```bash
python3 raspberrypi_tests/pi_to_arduino_test.py
```

### Expected Output

```text
Startup: Arduino feedback module ready
Sending: B
Arduino replied: ACK:B
Sending: W
Arduino replied: ACK:W
Sending: E
Arduino replied: ACK:E
Sending: R
Arduino replied: ACK:R
Serial test complete.
```

---

## 9. Sample Board Images

The `sample_images/` folder is intended to store representative images for computer vision development and calibration.

Current target image set:

```text
sample_images/
  empty_board.jpg
  black_center.jpg
  white_center.jpg
  mixed_board.jpg
```

These images should support:

- Grid detection
- Stone detection
- Colour thresholding
- Calibration of the board capture setup
- Early OpenCV testing

---

## 10. Integration Notes for Vision / Game-State Subsystem

The Raspberry Pi vision subsystem can trigger Arduino feedback by sending one serial byte after determining the relevant board event.

### Suggested Mapping

| Vision / Game-State Event | Serial Command |
|---|---|
| New black piece detected | `B` |
| New white piece detected | `W` |
| Detection ambiguity or invalid board state | `E` |
| New game or reset state | `R` |

### Example Python Integration

```python
arduino.write(b'B')
```

or

```python
arduino.write(b'W')
```

The Arduino will then return an acknowledgment such as:

```text
ACK:B
```

---

## 11. Current Status

### Completed

- Arduino serial feedback firmware written
- Raspberry Pi to Arduino serial test successful
- Serial command protocol defined
- Initial hardware wiring plan documented
- Raspberry Pi 3 confirmed as the actual processor platform
- Camera capture test script prepared

### In Progress

- Stable overhead camera mount
- Collection of sample Gomoku board images
- Physical LED / buzzer hardware refinement
- Integration with board-state recognition output

---

## 12. Recommended Next Steps

1. Finalise the overhead camera mount so the board can be captured from a repeatable top-down angle.
2. Collect and commit the initial sample image dataset.
3. Integrate the computer vision subsystem with the Arduino serial command protocol.
4. Decide whether serial commands should represent:
   - detected player move, or
   - broader board-state status / event type
5. Validate the end-to-end flow:

```text
Camera capture
-> Board-state detection
-> Game-state decision
-> Serial command to Arduino
-> LED / buzzer feedback
```

---

## 13. Current End-to-End Target Architecture

```text
Raspberry Pi Camera Module
        |
        v
Raspberry Pi 3
- image capture
- board-state processing
- game-state handling
- serial communication
        |
        v
Arduino Uno
- LED feedback
- buzzer feedback
```

Future system integration may also include:

```text
Raspberry Pi 3
        |
        v
IoT dashboard / MQTT / backend services
```

depending on the final implementation scope.
