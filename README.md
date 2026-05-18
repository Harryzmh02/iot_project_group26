# Smart Gomoku Board State Monitoring System

## Integration Status

This repository contains the hardware, computer vision, and IoT integration work for the Smart Gomoku Board State Monitoring System.

Completed components:

- Arduino LED/buzzer feedback
- Raspberry Pi to Arduino serial communication
- Reusable Python integration utilities
- Raspberry Pi camera capture and image preprocessing
- OpenCV board detection (HSV thresholding, blob detection, grid mapping)
- MQTT publishing to Node-RED dashboard
- Hardware wiring and camera setup documentation

---

## Current Hardware

- Raspberry Pi 3 Model B
- Raspberry Pi Camera Module
- Arduino Uno
- Breadboard
- Jumper wires
- LEDs
- Resistors
- Passive buzzer
- Gomoku board and pieces

> The project proposal previously mentioned Raspberry Pi 4, but the actual prototype uses a **Raspberry Pi 3 Model B**.

---

## Repository Structure

```text
arduino_feedback/
  gomoku_feedback.ino

hardware/
  camera_mount_notes.md
  wiring_notes.md

raspberrypi_capture/
  periodic_board_capture.py

computer_vision/
  gomoku_cv.py
  README.md

raspberrypi_integration/
  arduino_feedback_client.py
  demo_feedback_sequence.py

raspberrypi_tests/
  camera_test.py
  pi_to_arduino_test.py

sample_images/
  img_sample.md
```

---

## Work Completed by Minghao

### 1. Arduino Feedback Module

The Arduino firmware has been implemented in:

```text
arduino_feedback/gomoku_feedback.ino
```

It listens for single-byte serial commands from the Raspberry Pi and controls LEDs and buzzer feedback.

| Command | Meaning | Arduino Action | Reply |
|---|---|---|---|
| `B` | Black move detected | Black LED + short beep | `ACK:B` |
| `W` | White move detected | White LED + short beep | `ACK:W` |
| `E` | Error / invalid state | Flash LEDs + error beep | `ACK:E` |
| `R` | Reset | Turn off feedback LEDs | `ACK:R` |

---

### 2. Raspberry Pi to Arduino Serial Communication

Serial communication between the Raspberry Pi 3 and Arduino Uno has been tested successfully.

Test script:

```text
raspberrypi_tests/pi_to_arduino_test.py
```

Expected output:

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

### 3. Reusable Arduino Feedback Client

A reusable Python client has been added for future integration:

```text
raspberrypi_integration/
  arduino_feedback_client.py
  demo_feedback_sequence.py
```

Other modules can trigger hardware feedback without handling low-level serial logic.

Example:

```python
from raspberrypi_integration.arduino_feedback_client import ArduinoFeedbackClient

feedback = ArduinoFeedbackClient()

if feedback.connect():
    feedback.black_move()
    feedback.white_move()
    feedback.error()
    feedback.reset()
    feedback.close()
```

Available methods:

| Method | Purpose |
|---|---|
| `black_move()` | Trigger black move feedback |
| `white_move()` | Trigger white move feedback |
| `error()` | Trigger error feedback |
| `reset()` | Reset LEDs |
| `connect()` | Open serial connection |
| `close()` | Close serial connection |

---

### 4. Camera Capture Utilities

Camera test script:

```text
raspberrypi_tests/camera_test.py
```

Purpose:

- Confirm Pi Camera Module is detected
- Capture a test board image

Run:

```bash
python3 raspberrypi_tests/camera_test.py
```

Periodic capture script:

```text
raspberrypi_capture/periodic_board_capture.py
```

Purpose:

- Capture board images at fixed intervals
- Save timestamped frames for CV testing and later integration

Run:

```bash
python3 raspberrypi_capture/periodic_board_capture.py
```

---

## Hardware Documentation

### Wiring Notes

Detailed wiring information is stored in:

```text
hardware/wiring_notes.md
```

Current wiring summary:

```text
Arduino GND -> Breadboard GND rail

D8 -> resistor -> black LED -> GND
D9 -> resistor -> white LED -> GND
D6 -> buzzer positive
buzzer negative -> GND
```

---

### Camera Mount Notes

Camera setup and calibration considerations are documented in:

```text
hardware/camera_mount_notes.md
```

The camera should remain:

- Stable
- Top-down
- Able to capture the full 15×15 board
- Fixed after calibration where possible

---

## Sample Image Dataset Plan

A planned image dataset specification has been prepared in:

```text
sample_images/img_sample.md
```

This dataset is intended to support:

- Grid calibration
- Stone detection
- Colour thresholding
- Edge/corner position testing
- Robustness testing under different lighting conditions

Actual images can be added once the overhead camera setup is finalised.

---

## How Other Team Members Can Continue

### Computer Vision / Board Detection

The initial OpenCV board-detection module has been added in:

```text
computer_vision/gomoku_cv.py
```

It detects black/white stones, maps them to 15×15 board coordinates, compares the new board with the previous board state, and can trigger Arduino feedback and publish moves to Jason's MQTT dashboard.

Run on a captured image (detection only):

```bash
python3 computer_vision/gomoku_cv.py --image captured_frames/board_YYYYMMDD_HHMMSS.jpg
```

Run with Arduino feedback:

```bash
python3 computer_vision/gomoku_cv.py --image captured_frames/board_YYYYMMDD_HHMMSS.jpg --feedback
```

Run with MQTT publishing (requires Mosquitto running and Node-RED loaded with `src/flows.json`):

```bash
python3 computer_vision/gomoku_cv.py --image captured_frames/board_YYYYMMDD_HHMMSS.jpg --mqtt
```

Run the full pipeline — Arduino feedback + MQTT dashboard + live camera:

```bash
python3 computer_vision/gomoku_cv.py --feedback --mqtt
```

If Mosquitto is on a different device, pass its IP:

```bash
python3 computer_vision/gomoku_cv.py --feedback --mqtt --mqtt-broker 192.168.1.100
```

---

### Game-State Logic

Suggested event mapping:

| Game-State Event | Feedback Call |
|---|---|
| Valid black move | `black_move()` |
| Valid white move | `white_move()` |
| Invalid / uncertain update | `error()` |
| New game / reset | `reset()` |

---

### IoT Dashboard / MQTT Integration

Jason's Node-RED dashboard subscribes to `gomoku/move` and displays the board live.
The CV module now publishes directly to that topic using `--mqtt`.

End-to-end system flow (fully wired):

```text
Pi Camera
   |
   v
Board Detection  (computer_vision/gomoku_cv.py)
   |
   v
Move Delta
   |
   +--> Arduino LED/Buzzer  (--feedback)
   |
   +--> MQTT broker → Node-RED dashboard  (--mqtt)
```

Jason's Node-RED flow is in `src/flows.json`. Import it at `http://localhost:1880`.

---

## Recommended Next Steps

1. Calibrate board corners on the actual overhead camera mount and save the `--corners` values.
2. Capture a real board image dataset for CV testing under lab lighting.
3. Run end-to-end system test: camera → CV → Arduino + MQTT simultaneously.

---

## Current Contribution Summary

The following components have been completed and are ready for team use:

- Arduino LED/buzzer feedback firmware
- Raspberry Pi–Arduino serial protocol and test script
- Reusable Arduino feedback client
- Camera capture and image preprocessing scripts
- OpenCV board detection module (`computer_vision/gomoku_cv.py`)
- MQTT integration — CV publishes moves directly to Node-RED dashboard
- Node-RED dashboard flow (`src/flows.json`) with board visualisation and winner detection
- Wiring documentation and camera setup notes
- Test suite covering frame stability, preprocessing, pipeline structure, and CV-MQTT integration
