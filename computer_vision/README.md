# Computer Vision Pipeline

This folder contains Ashish's OpenCV board-detection module.

It performs:

- HSV colour thresholding
- blob detection
- 15 x 15 grid coordinate mapping
- board-state matrix generation
- old-board vs new-board delta detection
- optional Arduino LED/buzzer feedback integration
- optional MQTT publishing to Jason's Node-RED dashboard

## Install Required Python Packages

```bash
pip install opencv-python numpy pyserial paho-mqtt
```

On the Raspberry Pi, `picamera2` is normally installed through the Raspberry Pi OS packages, not this CV script.

## Test With A Captured Image

First capture images using the existing team script:

```bash
python3 raspberrypi_capture/periodic_board_capture.py
```

Then run CV detection on one image:

```bash
python3 computer_vision/gomoku_cv.py --image captured_frames/board_YYYYMMDD_HHMMSS.jpg
```

The script creates:

- `detected_board.jpg`
- `black_mask.jpg`
- `white_mask.jpg`
- `board_state.json`

## Test With Arduino Feedback

After detecting one new move, the CV module can call Minghao's feedback client:

```bash
python3 computer_vision/gomoku_cv.py --image captured_frames/board_YYYYMMDD_HHMMSS.jpg --feedback
```

If your Arduino is not on `/dev/ttyACM0`, pass the port:

```bash
python3 computer_vision/gomoku_cv.py --image captured_frames/board_YYYYMMDD_HHMMSS.jpg --feedback --arduino-port /dev/ttyUSB0
```

## Calibration

If the image contains table/background around the board, provide the four board corners:

```bash
python3 computer_vision/gomoku_cv.py --image sample_images/06_mixed_sparse.jpg --corners "120,80,820,90,830,790,110,780"
```

Corner format:

```text
top-left-x,top-left-y,top-right-x,top-right-y,bottom-right-x,bottom-right-y,bottom-left-x,bottom-left-y
```

## Publish Detected Moves to MQTT Dashboard

With Mosquitto running and Node-RED loaded with Jason's flow, add `--mqtt`:

```bash
python3 computer_vision/gomoku_cv.py --image captured_frames/board_YYYYMMDD_HHMMSS.jpg --mqtt
```

If Mosquitto is on another device, pass its IP:

```bash
python3 computer_vision/gomoku_cv.py --image captured_frames/board_YYYYMMDD_HHMMSS.jpg --mqtt --mqtt-broker 192.168.1.100
```

Each detected new move is published to `gomoku/move` in the format Jason's dashboard expects:

```json
{
  "player": "black",
  "row": 8,
  "column": 9,
  "move_number": 3,
  "timestamp": "2026-05-18T14:23:01.123456"
}
```

Note: CV uses 0-indexed coordinates internally; the MQTT publisher converts to 1-indexed automatically.

## Output Meaning

Board values:

```text
0 = empty
1 = black stone
2 = white stone
```

Example move output:

```text
New move: black at row 7, col 8
```
