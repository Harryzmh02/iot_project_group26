# Smart Gomoku Board

An IoT system that watches a printable Gomoku board with a Raspberry Pi camera,
detects each move using computer vision, lights up an Arduino feedback module,
and publishes live moves to a Node-RED dashboard over MQTT.

## How it works

```
+--------------------+      +----------------------+      +-----------------+
| Pi Camera          | ---> | Raspberry Pi         | ---> | Arduino Uno     |
| (printed board     |      |  - ArUco corners     |      |  - Black LED    |
|  with 4 ArUco      |      |  - perspective warp  |      |  - White LED    |
|  markers)          |      |  - stone detection   |      |  - Buzzer       |
+--------------------+      |  - move diff         |      +-----------------+
                            +----------+-----------+
                                       |
                                       | MQTT  (gomoku/move)
                                       v
                            +----------------------+
                            | Node-RED dashboard   |
                            |  (web view)          |
                            +----------------------+
```

The "board" is a single A3 print: a 15 x 15 grid with a yellow background and
four ArUco markers at the corners. No physical Go board required — stones are
placed directly on the printed paper.

## File tree

```text
iot_project_group26/
├── README.md                          - this file
├── requirements.txt                   - Python deps (paho-mqtt, pyserial; opencv/numpy from apt on Pi)
├── setup_pi.sh                         - one-command Pi setup: apt deps + venv + pip deps
├── gomoku_aruco_print.pdf             - ready-to-print A3 board (15x15 grid, 4 ArUco markers, yellow fill)
├── .gitignore
│
├── app/                               - all runtime Python code
│   ├── gomoku_cv.py                   - CV core: ArUco detection, perspective warp, stone detection
│   ├── main_pipeline.py               - end-to-end loop: camera -> CV -> Arduino + MQTT
│   ├── test_aruco_grid.py             - one-shot calibration tool: image in, ArUco grid overlay out
│   ├── periodic_board_capture.py      - capture N stable frames from Picamera2 to ./captured_frames/
│   ├── frame_stability.py             - "wait for the scene to stop moving" helper
│   ├── image_preprocessing.py         - resize + blur shared by CV paths
│   ├── arduino_feedback_client.py     - serial wrapper that sends B/W/E/R commands
│   └── demo_feedback_sequence.py      - run the four feedback commands once, in order (smoke test)
│
├── dashboard/                         - Node-RED + MQTT side
│   ├── flows.json                     - import into Node-RED to get the live board UI
│   ├── standard.json                  - reference payload shape the dashboard expects
│   └── mqtt.py                        - canned move-publisher to demo the dashboard without the Pi
│
├── firmware/
│   └── gomoku_feedback.ino            - Arduino sketch: reads B/W/E/R on serial, drives LEDs + buzzer
│
└── tests/
    ├── run_all_tests.sh               - run every no-hardware test, report pass/fail
    ├── test_frame_stability.py        - unit tests for FrameStabilityChecker
    ├── test_image_preprocessing.py    - unit tests for preprocess_frame / crop_to_board
    ├── test_pipeline_structure.py     - sanity: modules import, expected functions exist
    ├── test_pipeline_integration.py   - synthetic frames -> verify CV detects + delta is correct
    ├── test_dashboard_flow_contract.py- guards the MQTT payload shape the dashboard expects
    ├── test_script_entrypoints.py     - each script has a main() and is callable as __main__
    └── pi_to_arduino_test.py          - hardware smoke test: serial round-trip with the Arduino
```

## File descriptions

### `app/gomoku_cv.py`
Computer-vision core. Detects the four ArUco markers (DICT_4X4_50, IDs 0/1/2/3
at TL/TR/BR/BL), maps them onto an 800x800 canvas using a perspective warp,
finds stones with HoughCircles + HSV classification, and snaps each detection
to the nearest of the 15 x 15 grid intersections. Key constants at the top:

- `BOARD_SIZE = 15` — grid lines per side
- `ARUCO_PADDING_RATIO = 1/20 = 0.05` — matches the printed PDF (20 cm grid + 1 cm quiet zone)

Also runnable standalone for single-image testing: `python3 app/gomoku_cv.py --image board.jpg`.

### `app/main_pipeline.py`
The Pi's main loop. Captures frames from Picamera2, gates them through
`FrameStabilityChecker`, runs `gomoku_cv.process_frame`, computes the delta
against the previous board state, and on a confirmed single-stone change:
sends `B` / `W` to the Arduino and publishes a JSON payload to MQTT topic
`gomoku/move`. ArUco corners are resolved every frame with a last-good
fallback so a momentary marker occlusion doesn't blank the pipeline.

Config block at the top: `ARDUINO_PORT`, `MQTT_BROKER`, `MQTT_PORT`, `MQTT_TOPIC`.

### `app/test_aruco_grid.py`
Calibration helper. Reads one image file, runs ArUco detection (falls back to
Hough lines if needed), warps the board, draws the green 15 x 15 overlay, and
saves two JPGs to the current directory:

- `aruco_corners_on_original.jpg` — the input photo with TL/TR/BR/BL dots
- `aruco_grid_result.jpg` — the warped board with the overlay grid

The terminal prints `Corners detected via: ArUco markers` on success. Use this
to verify the print is good before going live.

### `app/periodic_board_capture.py`
Captures 20 stable frames into `captured_frames/board_<timestamp>.jpg`. Only
saves a frame after `FrameStabilityChecker` reports three consecutive
low-motion reads, so the saved JPGs are sharp.

### `app/frame_stability.py`
Stateful helper: feed it frames, it tells you `True` once the mean absolute
pixel diff has stayed under `diff_threshold` for `required_stable_frames` in a
row. Used by both the live pipeline and the capture script.

### `app/image_preprocessing.py`
`preprocess_frame()` (resize + blur) and `crop_to_board()` (4-point perspective
warp), shared so the live pipeline and offline tests stay byte-for-byte
consistent.

### `app/arduino_feedback_client.py`
Thin pyserial wrapper. Opens `/dev/ttyACM0` at 9600 baud, exposes
`black_move()`, `white_move()`, `error()`, `reset()`. Each call writes one
character and reads back the Arduino's ACK line.

### `app/demo_feedback_sequence.py`
Runs `black_move() -> white_move() -> error() -> reset()` once. Useful for
proving the Arduino is wired correctly before plugging in the rest of the
pipeline.

### `dashboard/flows.json`
Node-RED export. Drop into Node-RED's import dialog and it'll set up an
MQTT-in node subscribed to `gomoku/move` plus the UI widgets that render the
live 15 x 15 board.

### `dashboard/mqtt.py`
Stand-in publisher that fires a canned sequence of 15 moves to the broker on
2-second intervals. Use this to demo the dashboard without the Pi or camera.

### `dashboard/standard.json`
Reference data documenting the MQTT payload shape the dashboard expects.
`tests/test_dashboard_flow_contract.py` validates against it.

### `firmware/gomoku_feedback.ino`
Arduino Uno sketch. Listens on serial; commands:

| char | meaning              | feedback                              |
|------|----------------------|---------------------------------------|
| `B`  | black move detected  | black LED on, short beep              |
| `W`  | white move detected  | white LED on, short beep              |
| `E`  | error / ambiguous    | both LEDs flash 3x, two low beeps     |
| `R`  | reset                | both LEDs off                         |

Pins: black LED = D8, white LED = D9, buzzer = D6.

### `tests/`
Six pure-Python tests (no hardware) and one serial smoke test. `run_all_tests.sh`
runs the no-hardware set and reports pass/fail.

---

## Hardware bill of materials

- Raspberry Pi 4 / Pi 3 Model B (tested on Pi 3B + Raspberry Pi OS Bookworm)
- Raspberry Pi Camera Module v2 or HQ (any Picamera2-compatible)
- Arduino Uno + USB-A-to-USB-B cable
- Breadboard, jumper wires
- 2 LEDs (one for black, one for white) + 2 x ~220 Ω resistors
- Passive piezo buzzer
- A3 printer (or print shop access) for the board PDF
- A3 sheet of plain white paper

## Deployment from zero

### 1. Print the board

The repo ships with the printable file ready to go:

```
gomoku_aruco_print.pdf
```

Open it (Preview / Adobe Reader / browser) and send to an A3 printer.
**Print at 100% scale — do not use "Fit to page" / "Scale to fit"**, or the
geometry will drift and ArUco detection will fail.

Layout, for reference:

- 20 x 20 cm playing grid (15 x 15 lines, cell ≈ 1.43 cm)
- 9 hoshi at the (3, 7, 11) lattice
- Yellow fill (RGB 250, 230, 130) inside the grid for stone contrast
- 1 cm white quiet zone between grid and each marker
- 3 cm ArUco markers (IDs 0/1/2/3, DICT_4X4_50) at TL/TR/BR/BL

After printing, verify with a ruler: any marker side = 3.0 cm, full grid =
20.0 cm. Tape the print flat so the paper doesn't curl.

> If you ever need to regenerate the PDF (e.g. to change grid size or paper
> stock), the geometry constants in `app/gomoku_cv.py` (`BOARD_SIZE`,
> `ARUCO_PADDING_RATIO`) and the PDF must agree. Easiest path: keep the
> bundled PDF and the constants together — don't touch one without the other.

### 2. Flash the Arduino

Open `firmware/gomoku_feedback.ino` in the Arduino IDE, select board
"Arduino Uno", port `/dev/ttyACM0` (Linux/macOS) or `COMx` (Windows), and
upload. Open the serial monitor at 9600 baud — you should see
`Arduino feedback module ready`.

Wiring:
- Black LED: anode -> 220 Ω -> D8, cathode -> GND
- White LED: anode -> 220 Ω -> D9, cathode -> GND
- Buzzer: + -> D6, - -> GND

### 3. Set up the Raspberry Pi

Fresh Raspberry Pi OS (Bookworm or later). Clone (or unzip) the project, then
run `setup_pi.sh` — it does the whole setup in one command:

```bash
cd ~
git clone <this-repo-url> iot_project_group26   # or unzip the download
cd iot_project_group26
bash setup_pi.sh
```

The script is safe to re-run and does four things:

1. `apt install`s the heavy native deps (numpy, OpenCV, Picamera2, git,
   mosquitto). Building numpy/opencv from pip source on a Pi is painfully
   slow, so they come from apt.
2. Creates `.venv` with `--system-site-packages` so the venv inherits those
   apt packages.
3. `pip install`s the pure-Python deps (`paho-mqtt`, `pyserial`) into the venv.
4. Verifies `cv2.aruco` works, falling back to `opencv-contrib-python` only if
   the apt OpenCV build lacks it.

Run it **once per Pi** — the apt packages and the venv persist across reboots,
so this is not a per-session step. There is no precreated/committed venv: a
venv is not portable across machines or architectures, and the apt packages it
relies on live outside it. Every session after setup, just activate the venv
before running anything:

```bash
source .venv/bin/activate
```

If you would rather run the steps by hand, the manual equivalent is:

```bash
sudo apt update
sudo apt install -y python3-numpy python3-opencv python3-picamera2 git mosquitto
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -c "import cv2; print(cv2.__version__, hasattr(cv2, 'aruco'))"  # expect a version + True
# if that prints False, install contrib in the venv only:
pip install opencv-contrib-python
```

### 4. Set up the MQTT broker + Node-RED

The broker and dashboard can run on the Pi or on a Mac/PC on the same network
(typical demo setup: Pi + Mac both joined to a phone's hotspot, broker on the
Mac).

**4a. Install both:**

On the Pi (or any Linux host):
```bash
sudo apt install -y mosquitto nodered
sudo systemctl enable --now nodered
```

On macOS:
```bash
brew install mosquitto node-red
```

**4b. Configure mosquitto to accept remote connections.**
By default mosquitto 2.x starts in *local-only mode* — it logs
`Starting in local only mode. Connections will only be possible from clients
running on this machine.` That blocks the Pi from reaching a Mac-hosted
broker. Fix with a minimal config:

```bash
cat > ~/mosquitto.conf <<'EOF'
listener 1883 0.0.0.0
allow_anonymous true
EOF

mosquitto -v -c ~/mosquitto.conf
```

You should now see `Opening ipv4 listen socket on port 1883` **without** the
local-only line. From the Pi, confirm reachability:

```bash
nc -zv <broker-ip> 1883
# expected: Connection to <broker-ip> 1883 port [tcp/*] succeeded!
```

If `nc` times out and the broker is on a Mac, allow inbound 1883 in System
Settings → Network → Firewall (or disable the firewall for the demo).

**4c. Point the pipeline at the broker.**
`app/main_pipeline.py` hard-codes `MQTT_BROKER = "172.20.10.3"` (an iPhone
hotspot IP). Replace it with whatever `ipconfig getifaddr en0` (Mac) or
`hostname -I` (Pi) reports on the host running mosquitto. The IP changes
when the network changes — re-check it before each session.

**4d. Import the Node-RED flow.**
Browse to `http://<host-ip>:1880`, hamburger menu → Import → paste the
contents of `dashboard/flows.json` → Deploy. Dashboard UI:
`http://<host-ip>:1880/ui`. If the broker and Node-RED are on different
machines, edit the MQTT broker node inside the flow to point at the broker
IP instead of `localhost`.

### 5. Calibrate the camera + verify ArUco

Mount the Pi camera so it looks straight down at the printed board. Capture
20 stable frames:

```bash
source .venv/bin/activate
python3 app/periodic_board_capture.py
```

Then run the calibration check on one of the captures:

```bash
python3 app/test_aruco_grid.py captured_frames/board_<latest>.jpg
```

Terminal must print:

```
Corners detected via: ArUco markers
```

Open `aruco_grid_result.jpg` — the green 15 x 15 overlay should land cleanly
on the printed black grid lines. If detection still falls back to Hough
lines, check (in this order): print scale (must be 100%), focus, glare on
the markers, quiet-zone violation (something dark touching a marker), and
that the markers were generated from `DICT_4X4_50` with IDs 0..3.

### 6. Run the live pipeline

```bash
mosquitto -d                            # if not running as a service
python3 dashboard/mqtt.py               # optional: demo data into the dashboard
python3 app/main_pipeline.py            # the real thing
```

Place a black stone → black LED + short beep, dashboard updates within ~2 s.
Place a white stone → same with the white LED. Place two stones in the same
frame or move a stone → Arduino flashes both LEDs + double beep (error).

## Troubleshooting

| Symptom                                              | Likely cause                                                                  |
|------------------------------------------------------|-------------------------------------------------------------------------------|
| `Corners detected via: Hough lines (ArUco fallback)` | Print was scaled, marker dictionary mismatch, or quiet zone violated          |
| Pipeline runs but nothing publishes                  | MQTT broker not reachable — check `MQTT_BROKER` in `app/main_pipeline.py`     |
| Mosquitto logs "Starting in local only mode"         | Bind to all interfaces with a config file (`listener 1883 0.0.0.0`) — see 4b |
| `nc -zv <broker-ip> 1883` from Pi times out          | macOS firewall blocking 1883, or broker still on localhost-only              |
| Arduino "Serial connection failed"                   | Wrong port — check `ls /dev/ttyACM*` or `ls /dev/ttyUSB*`                     |
| Stones detected at wrong intersections               | Camera not perpendicular to board, or board curled — re-tape and re-capture   |
| White stones flagged as empty                        | Background not yellow (poor white contrast) — re-print the supplied PDF       |
| `import cv2` works but no `cv2.aruco`                | apt `python3-opencv` < 4.7 — `pip install opencv-contrib-python` in the venv  |
| `pip install numpy` takes hours on Pi                | Use `sudo apt install python3-numpy` + venv with `--system-site-packages`     |
| `test_aruco_grid.py` won't exit                      | Already fixed — it now writes JPGs and exits without opening a GUI window     |

## Running the tests

```bash
cd tests
./run_all_tests.sh
```

Hardware-only test (Arduino plugged in):

```bash
python3 tests/pi_to_arduino_test.py
```

## MQTT payload contract

Published to `gomoku/move`:

```json
{
  "player": "black",
  "row": 7,
  "column": 7,
  "move_number": 1,
  "timestamp": "2026-05-20T14:30:55.123456"
}
```

`row` and `column` are 1-indexed (1..15). The dashboard expects exactly this
shape — `tests/test_dashboard_flow_contract.py` is the source of truth.
