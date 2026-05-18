# Smart Gomoku Board

This project reads a Gomoku board from a camera, detects moves, sends feedback to Arduino, and publishes moves to a web dashboard through MQTT.

## Folder Layout

```text
app/
  All Python runtime code:
  - board capture
  - image preprocessing
  - computer vision
  - Arduino feedback client
  - end-to-end pipeline

dashboard/
  Node-RED flow files and MQTT demo publisher

firmware/
  Arduino sketch

tests/
  Software tests and hardware smoke tests
```

## Quick Map

- Start here for the full pipeline: `app/main_pipeline.py`
- Run CV on one image: `app/gomoku_cv.py`
- Capture board images: `app/periodic_board_capture.py`
- Test Arduino feedback: `app/demo_feedback_sequence.py`
- Demo MQTT publisher for dashboard: `dashboard/mqtt.py`
- Import into Node-RED: `dashboard/flows.json`
- Arduino code: `firmware/gomoku_feedback.ino`

## Common Commands

Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run the full Raspberry Pi pipeline:

```powershell
python app\main_pipeline.py
```

Run CV on a saved image:

```powershell
python app\gomoku_cv.py --image captured_frames\board_YYYYMMDD_HHMMSS.jpg
```

Capture stable board images:

```powershell
python app\periodic_board_capture.py
```

Run software tests:

```powershell
python tests\test_frame_stability.py
python tests\test_image_preprocessing.py
python tests\test_pipeline_structure.py
python tests\test_pipeline_integration.py
python tests\test_dashboard_flow_contract.py
```

## Hardware Used

- Raspberry Pi 3 Model B
- Raspberry Pi Camera Module
- Arduino Uno
- Breadboard
- LEDs and resistors
- Passive buzzer
- Gomoku board and pieces

## Documentation

- Dashboard guide: `docs/dashboard_demo.md`
- CV guide: `docs/cv_pipeline.md`
- Wiring notes: `docs/wiring_notes.md`
- Camera mount notes: `docs/camera_mount_notes.md`
- Sample image plan: `docs/sample_image_plan.md`

## Recommended Workflow

1. Set up the camera and Arduino using the notes in `docs/`.
2. Verify hardware with `tests/camera_test.py` and `tests/pi_to_arduino_test.py`.
3. Capture stable images with `app/periodic_board_capture.py`.
4. Validate detection with `app/gomoku_cv.py`.
5. Run `app/main_pipeline.py` for the end-to-end flow.
6. Start Mosquitto and Node-RED, then use `dashboard/flows.json` and `dashboard/mqtt.py` for web demo validation.
