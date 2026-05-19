# Final Physical Demo Checklist

## 1. Hardware
- Connect Raspberry Pi Camera Module to the Raspberry Pi 3.
- Connect Arduino Uno over USB.
- Wire LEDs and passive buzzer according to `hardware/wiring_notes.md`.
- Place the 15x15 Gomoku board under the camera.
- Keep the four calibration markers visible and keep the camera fixed after calibration.

## 2. Arduino
- Open `arduino_feedback/gomoku_feedback.ino` in the Arduino IDE.
- Select Arduino Uno and the correct serial port.
- Upload the sketch.
- Expected serial commands:
  - `B` = black move detected
  - `W` = white move detected
  - `E` = invalid or uncertain detection
  - `R` = reset

## 3. MQTT And Dashboard
- Start Mosquitto:
  ```bash
  mosquitto -v
  ```
- Start Node-RED:
  ```bash
  node-red
  ```
- Open:
  ```text
  http://<raspberry-pi-ip>:1880/ui
  ```
- Import and deploy:
  ```text
  src/flows.json
  ```

## 4. Offline Image Check
- Capture or copy one board image.
- Run without hardware feedback:
  ```bash
  python computer_vision/gomoku_cv.py --image captured_frames/board.jpg
  ```
- Run with perspective calibration:
  ```bash
  python computer_vision/gomoku_cv.py --image captured_frames/board.jpg --corners "120,80,1120,85,1135,690,110,685"
  ```
- Confirm these debug files are created:
  - `detected_board.jpg`
  - `black_mask.jpg`
  - `white_mask.jpg`
  - `warped_board.jpg` when `--corners` is used
  - `board_state.json`

## 5. Full Physical Pipeline
- Run the final Pi pipeline:
  ```bash
  python raspberrypi_integration/run_gomoku_pi.py
  ```
- Run with calibrated corners:
  ```bash
  python raspberrypi_integration/run_gomoku_pi.py --corners "120,80,1120,85,1135,690,110,685"
  ```
- Run with explicit Arduino and MQTT broker:
  ```bash
  python raspberrypi_integration/run_gomoku_pi.py --arduino-port /dev/ttyUSB0 --mqtt-broker 192.168.1.100
  ```

## 6. Demo Procedure
- Start with an empty board and wait for stable-frame messages.
- Place exactly one stone at a time.
- Remove hands from the camera view and wait for confirmation.
- Confirm:
  - OpenCV prints one valid move.
  - Arduino LED/buzzer responds.
  - MQTT publishes JSON on `gomoku/move`.
  - Node-RED dashboard updates.
- If an invalid move, shadow, hand, or multi-stone change is detected, the pipeline should reject it and continue running.

## 7. Test Command
```bash
bash raspberrypi_tests/run_all_tests.sh
```

Expected result:
```text
Results: 5 passed, 0 failed
```
