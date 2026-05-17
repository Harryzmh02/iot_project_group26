# Computer Vision Pipeline

This folder contains Ashish's OpenCV board-detection module.

It performs:

- HSV colour thresholding
- blob detection
- 15 x 15 grid coordinate mapping
- board-state matrix generation
- old-board vs new-board delta detection
- optional Arduino LED/buzzer feedback integration

## Install Required Python Packages

```bash
pip install opencv-python numpy pyserial
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

To tune HSV thresholds without editing code:

```bash
python3 computer_vision/gomoku_cv.py --image captured_frames/board_YYYYMMDD_HHMMSS.jpg --black-low 0,0,0 --black-high 180,255,75 --white-low 0,0,155 --white-high 180,80,255
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

On the first run, `board_state.json` does not exist yet, so the script will skip sending feedback and only establish the baseline board state.

## Run With A Live Camera

You can also run the detector directly from a USB or Pi camera. The script defaults to camera `0` if no option is provided:

```bash
python3 computer_vision/gomoku_cv.py --camera 0
```

On Raspberry Pi, the script prefers `picamera2` when available. For standard webcam testing, it falls back to OpenCV's camera capture.

> Note: `--camera` mode still requires the board to fill the frame or to be precisely aligned. If your camera view includes table or background around the board, pass `--corners` so the module can warp the board into a square grid.

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
