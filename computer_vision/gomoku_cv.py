import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

try:
    import paho.mqtt.client as mqtt_client
except ImportError:
    mqtt_client = None

try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


BOARD_SIZE = 15
IMAGE_SIZE = 800
EMPTY = 0
BLACK = 1
WHITE = 2
ZOOM_RADIUS = 40
ZOOM_SIZE = 120
CORNER_LABELS = ["Top-Left", "Top-Right", "Bottom-Right", "Bottom-Left"]


@dataclass
class Stone:
    color: str
    x: int
    y: int
    row: int
    col: int
    area: float


def preprocess_frame(frame):
    resized = cv2.resize(frame, (IMAGE_SIZE, IMAGE_SIZE), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(resized, (5, 5), 0)


def apply_clahe(image):
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)


def order_corners(points):
    pts = np.array(points, dtype=np.float32)
    sums = pts.sum(axis=1)
    diffs = np.diff(pts, axis=1).reshape(-1)
    return np.array(
        [
            pts[np.argmin(sums)],
            pts[np.argmin(diffs)],
            pts[np.argmax(sums)],
            pts[np.argmax(diffs)],
        ],
        dtype=np.float32,
    )


def parse_corners(corner_text):
    values = [float(value.strip()) for value in corner_text.split(",")]
    if len(values) != 8:
        raise ValueError("Corners must contain 8 numbers: x1,y1,x2,y2,x3,y3,x4,y4")
    points = [(values[i], values[i + 1]) for i in range(0, 8, 2)]
    return order_corners(points)


def warp_board(image, corners, output_size=IMAGE_SIZE):
    source = order_corners(corners)
    target = np.array(
        [[0, 0], [output_size - 1, 0], [output_size - 1, output_size - 1], [0, output_size - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(source, target)
    return cv2.warpPerspective(image, matrix, (output_size, output_size))


def point_to_board_position(x, y, image_size):
    cell_gap = image_size / (BOARD_SIZE - 1)
    row = int(round(y / cell_gap))
    col = int(round(x / cell_gap))
    return max(0, min(BOARD_SIZE - 1, row)), max(0, min(BOARD_SIZE - 1, col))


def is_near_grid_intersection(x, y, row, col, image_size):
    cell_gap = image_size / (BOARD_SIZE - 1)
    expected_x = col * cell_gap
    expected_y = row * cell_gap
    return np.hypot(x - expected_x, y - expected_y) <= cell_gap * 0.38


def find_stones_from_mask(mask, color, image_size):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = (image_size * 0.015) ** 2
    max_area = (image_size * 0.09) ** 2
    stones = []

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area or area > max_area:
            continue

        perimeter = cv2.arcLength(contour, True)
        if perimeter == 0:
            continue

        circularity = 4 * np.pi * area / (perimeter * perimeter)
        if circularity < 0.45:
            continue

        moments = cv2.moments(contour)
        if moments["m00"] == 0:
            continue

        x = int(moments["m10"] / moments["m00"])
        y = int(moments["m01"] / moments["m00"])
        row, col = point_to_board_position(x, y, image_size)
        stones.append(Stone(color=color, x=x, y=y, row=row, col=col, area=area))

    return stones


def find_stones(board_image):
    hsv = cv2.cvtColor(board_image, cv2.COLOR_BGR2HSV)
    image_size = board_image.shape[0]

    black_mask = cv2.inRange(hsv, np.array([0, 0, 0]), np.array([180, 255, 75]))
    white_mask = cv2.inRange(hsv, np.array([0, 0, 155]), np.array([180, 80, 255]))

    kernel = np.ones((5, 5), np.uint8)
    black_mask = cv2.morphologyEx(black_mask, cv2.MORPH_OPEN, kernel)
    black_mask = cv2.morphologyEx(black_mask, cv2.MORPH_CLOSE, kernel)
    white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_OPEN, kernel)
    white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_CLOSE, kernel)

    detected = []
    detected.extend(find_stones_from_mask(black_mask, "black", image_size))
    detected.extend(find_stones_from_mask(white_mask, "white", image_size))

    board = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.uint8)
    stones = []

    for stone in sorted(detected, key=lambda item: item.area, reverse=True):
        if not is_near_grid_intersection(stone.x, stone.y, stone.row, stone.col, image_size):
            continue

        value = BLACK if stone.color == "black" else WHITE
        if board[stone.row, stone.col] == EMPTY:
            board[stone.row, stone.col] = value
            stones.append(stone)

    return board, stones, black_mask, white_mask


def compute_delta(old_board, new_board):
    changes = []
    for row in range(BOARD_SIZE):
        for col in range(BOARD_SIZE):
            old_value = int(old_board[row, col])
            new_value = int(new_board[row, col])
            if old_value == new_value:
                continue

            if old_value == EMPTY and new_value in (BLACK, WHITE):
                changes.append(
                    {
                        "type": "new_move",
                        "row": row,
                        "col": col,
                        "color": "black" if new_value == BLACK else "white",
                    }
                )
            else:
                changes.append(
                    {
                        "type": "changed_or_removed",
                        "row": row,
                        "col": col,
                        "old": old_value,
                        "new": new_value,
                    }
                )
    return changes


def draw_results(board_image, stones):
    output = board_image.copy()
    image_size = output.shape[0]
    cell_gap = image_size / (BOARD_SIZE - 1)

    for index in range(BOARD_SIZE):
        position = int(round(index * cell_gap))
        cv2.line(output, (position, 0), (position, image_size), (210, 210, 210), 1)
        cv2.line(output, (0, position), (image_size, position), (210, 210, 210), 1)

    for stone in stones:
        color = (0, 0, 255) if stone.color == "black" else (0, 180, 0)
        cv2.circle(output, (stone.x, stone.y), 18, color, 3)
        cv2.putText(
            output,
            f"{stone.row},{stone.col}",
            (stone.x + 8, stone.y - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )
    return output


def process_frame(frame, corners):
    board_image = warp_board(frame, corners) if corners is not None else preprocess_frame(frame)
    board_image = apply_clahe(board_image)
    board, stones, black_mask, white_mask = find_stones(board_image)
    return board, stones, draw_results(board_image, stones), black_mask, white_mask


def load_board_state(path):
    if not path.exists():
        return np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.uint8)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return np.array(data["board"], dtype=np.uint8)
    return np.array(data, dtype=np.uint8)


def load_move_counter(path):
    if not path.exists():
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("move_number", 1)
    return 1


def save_board_state(path, board, move_number=1):
    data = {"board": board.astype(int).tolist(), "move_number": move_number}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def print_board(board):
    symbols = {EMPTY: ".", BLACK: "B", WHITE: "W"}
    print("\nDetected board:")
    for row in range(BOARD_SIZE):
        print(f"{row:02d}: " + " ".join(symbols[int(board[row, col])] for col in range(BOARD_SIZE)))


def create_feedback_client(port):
    from raspberrypi_integration.arduino_feedback_client import ArduinoFeedbackClient

    return ArduinoFeedbackClient(port=port)


def create_mqtt_client(broker, port=1883):
    if mqtt_client is None:
        print("[MQTT] paho-mqtt not installed — skipping MQTT publish")
        return None
    client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2)
    try:
        client.connect(broker, port, 60)
        client.loop_start()
        print(f"[MQTT] Connected to broker {broker}:{port}")
        return client
    except Exception as exc:
        print(f"[MQTT] Could not connect to broker {broker}:{port} — {exc}")
        return None


def publish_move(client, topic, move_number, color, row, col):
    # CV uses 0-indexed; dashboard expects 1-indexed with field name "column"
    payload = json.dumps({
        "player": color,
        "row": row + 1,
        "column": col + 1,
        "move_number": move_number,
        "timestamp": datetime.now().isoformat(),
    })
    client.publish(topic, payload)
    print(f"[MQTT] Published: {payload}")


def send_feedback(feedback, changes, mqtt=None, topic="gomoku/move", move_counter=None):
    new_moves = [change for change in changes if change["type"] == "new_move"]
    uncertain_changes = [change for change in changes if change["type"] != "new_move"]

    if len(new_moves) == 1 and not uncertain_changes:
        move = new_moves[0]
        if feedback:
            if move["color"] == "black":
                print(f"[Arduino] {feedback.black_move()}")
            else:
                print(f"[Arduino] {feedback.white_move()}")
        if mqtt:
            move_num = next(move_counter) if move_counter else 1
            publish_move(mqtt, topic, move_num, move["color"], move["row"], move["col"])
    elif changes:
        print("[CV] Uncertain board update, sending error feedback")
        if feedback:
            print(f"[Arduino] {feedback.error()}")


def run_image_mode(args):
    image = cv2.imread(str(args.image))
    if image is None:
        raise FileNotFoundError(f"Could not open image: {args.image}")

    corners = parse_corners(args.corners) if args.corners else None
    board, stones, result_image, black_mask, white_mask = process_frame(image, corners)
    old_board = load_board_state(args.state)
    changes = compute_delta(old_board, board)

    print_board(board)
    print("\nDetected stones:")
    for stone in stones:
        print(f"- {stone.color} stone at row {stone.row}, col {stone.col}")

    print("\nChanges:")
    if changes:
        for change in changes:
            print(f"- {change}")
    else:
        print("- No new move found")

    feedback = None
    if args.feedback:
        feedback = create_feedback_client(args.arduino_port)
        if not feedback.connect():
            feedback = None

    mqtt = create_mqtt_client(args.mqtt_broker) if args.mqtt else None

    move_number = load_move_counter(args.state)
    new_moves = [c for c in changes if c["type"] == "new_move"]
    try:
        send_feedback(feedback, changes, mqtt=mqtt, topic=args.mqtt_topic,
                      move_counter=iter(range(move_number, move_number + 1)))
    finally:
        if feedback:
            feedback.close()
        if mqtt:
            mqtt.loop_stop()

    next_move_number = move_number + len(new_moves)
    save_board_state(args.state, board, next_move_number)
    cv2.imwrite(str(args.output), result_image)
    cv2.imwrite(str(args.black_mask), black_mask)
    cv2.imwrite(str(args.white_mask), white_mask)
    print(f"\nSaved result image: {args.output}")


def run_camera_mode(args):
    corners = parse_corners(args.corners) if args.corners else None

    if Picamera2 is not None:
        run_picamera2_mode(args, corners)
        return

    camera = cv2.VideoCapture(args.camera, cv2.CAP_V4L2)
    if not camera.isOpened():
        raise RuntimeError(
            "Could not open camera. On Raspberry Pi, install picamera2 or check the camera is enabled."
        )

    feedback = None
    if args.feedback:
        feedback = create_feedback_client(args.arduino_port)
        if not feedback.connect():
            feedback = None

    mqtt = create_mqtt_client(args.mqtt_broker) if args.mqtt else None

    old_board = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.uint8)
    move_number = 1
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                break

            board, stones, result_image, _, _ = process_frame(frame, corners)
            changes = compute_delta(old_board, board)

            for change in changes:
                if change["type"] == "new_move":
                    print(f"New move: {change['color']} at row {change['row']}, col {change['col']}")

            new_moves = [c for c in changes if c["type"] == "new_move"]
            send_feedback(feedback, changes, mqtt=mqtt, topic=args.mqtt_topic,
                          move_counter=iter(range(move_number, move_number + len(new_moves) + 1)))
            move_number += len(new_moves)

            old_board = board.copy()
            cv2.imshow("Gomoku OpenCV Detection", result_image)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        if feedback:
            feedback.close()
        if mqtt:
            mqtt.loop_stop()
        cv2.destroyAllWindows()


def run_picamera2_mode(args, corners):
    camera = Picamera2()
    config = camera.create_preview_configuration(main={"format": "RGB888", "size": (1280, 720)})
    camera.configure(config)

    feedback = None
    if args.feedback:
        feedback = create_feedback_client(args.arduino_port)
        if not feedback.connect():
            feedback = None

    mqtt = create_mqtt_client(args.mqtt_broker) if args.mqtt else None

    old_board = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.uint8)
    move_number = 1
    try:
        camera.start()
        print("Started Raspberry Pi camera with Picamera2. Press q to quit.")

        while True:
            rgb_frame = camera.capture_array()
            frame = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)

            board, stones, result_image, _, _ = process_frame(frame, corners)
            changes = compute_delta(old_board, board)

            for change in changes:
                if change["type"] == "new_move":
                    print(f"New move: {change['color']} at row {change['row']}, col {change['col']}")

            new_moves = [c for c in changes if c["type"] == "new_move"]
            send_feedback(feedback, changes, mqtt=mqtt, topic=args.mqtt_topic,
                          move_counter=iter(range(move_number, move_number + len(new_moves) + 1)))
            move_number += len(new_moves)

            old_board = board.copy()
            cv2.imshow("Gomoku OpenCV Detection", result_image)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.stop()
        if feedback:
            feedback.close()
        if mqtt:
            mqtt.loop_stop()
        cv2.destroyAllWindows()


DEMO_MOVES = [
    ("black", 7, 7), ("white", 7, 8), ("black", 8, 8), ("white", 8, 7),
    ("black", 9, 9), ("white", 9, 8), ("black", 6, 6), ("white", 6, 7),
    ("black", 10, 10), ("white", 10, 8), ("black", 5, 5), ("white", 5, 8),
    ("black", 11, 11), ("white", 11, 8), ("black", 4, 4), ("white", 4, 8),
    ("black", 3, 3),
]


DEMO_IMG_SIZE = 540
DEMO_MARGIN = 30
_STAR_POINTS = {(3, 3), (3, 7), (3, 11), (7, 3), (7, 7), (7, 11), (11, 3), (11, 7), (11, 11)}


def _draw_demo_board(placed, current_move=None):
    img = np.full((DEMO_IMG_SIZE, DEMO_IMG_SIZE, 3), (45, 130, 200), dtype=np.uint8)
    cell = (DEMO_IMG_SIZE - 2 * DEMO_MARGIN) // (BOARD_SIZE - 1)

    for i in range(BOARD_SIZE):
        p = DEMO_MARGIN + i * cell
        cv2.line(img, (DEMO_MARGIN, p), (DEMO_MARGIN + (BOARD_SIZE - 1) * cell, p), (20, 80, 140), 1)
        cv2.line(img, (p, DEMO_MARGIN), (p, DEMO_MARGIN + (BOARD_SIZE - 1) * cell), (20, 80, 140), 1)

    for r, c in _STAR_POINTS:
        cx = DEMO_MARGIN + c * cell
        cy = DEMO_MARGIN + r * cell
        cv2.circle(img, (cx, cy), 3, (20, 80, 140), -1)

    for color, row, col in placed:
        cx = DEMO_MARGIN + (col - 1) * cell
        cy = DEMO_MARGIN + (row - 1) * cell
        stone_color = (20, 20, 20) if color == "black" else (235, 235, 235)
        radius = cell // 2 - 1
        cv2.circle(img, (cx, cy), radius, stone_color, -1)
        cv2.circle(img, (cx, cy), radius, (80, 80, 80), 1)

    if current_move and placed:
        color, row, col = placed[-1]
        cx = DEMO_MARGIN + (col - 1) * cell
        cy = DEMO_MARGIN + (row - 1) * cell
        mark = (200, 200, 200) if color == "black" else (50, 50, 50)
        cv2.circle(img, (cx, cy), 4, mark, -1)

    if current_move:
        move_num, color, row, col = current_move
        label = f"Move {move_num}: {color.upper()} at ({row},{col})"
        cv2.putText(img, label, (10, DEMO_IMG_SIZE - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)

    return img


def run_demo_mode(args):
    mqtt = create_mqtt_client(args.mqtt_broker) if args.mqtt else None

    feedback = None
    if args.feedback:
        feedback = create_feedback_client(args.arduino_port)
        if not feedback.connect():
            feedback = None

    print("=== DEMO MODE — replaying scripted game ===")
    print(f"  {len(DEMO_MOVES)} moves  |  MQTT: {'on' if mqtt else 'off'}  |  Arduino: {'on' if feedback else 'off'}")
    print("  Press q or Ctrl-C to stop\n")

    placed = []
    cv2.namedWindow("Gomoku Demo")
    cv2.imshow("Gomoku Demo", _draw_demo_board([]))
    cv2.waitKey(1)

    try:
        for move_number, (color, row, col) in enumerate(DEMO_MOVES, start=1):
            print(f"Move {move_number:2d}: {color:5s} at row {row}, col {col}")
            placed.append((color, row, col))

            if mqtt:
                publish_move(mqtt, args.mqtt_topic, move_number, color, row - 1, col - 1)
            if feedback:
                if color == "black":
                    feedback.black_move()
                else:
                    feedback.white_move()

            cv2.imshow("Gomoku Demo", _draw_demo_board(placed, (move_number, color, row, col)))
            if cv2.waitKey(int(args.demo_interval * 1000)) & 0xFF == ord('q'):
                break
    except KeyboardInterrupt:
        print("\nDemo stopped.")
    finally:
        cv2.destroyAllWindows()
        if feedback:
            feedback.close()
        if mqtt:
            mqtt.loop_stop()

    print("\nDemo complete.")


def run_calibrate_mode(args):
    if args.image:
        frame = cv2.imread(str(args.image))
        if frame is None:
            raise FileNotFoundError(f"Could not open image: {args.image}")
        frame = cv2.resize(frame, (IMAGE_SIZE, IMAGE_SIZE))
    else:
        cam_idx = args.camera if args.camera is not None else 0
        if Picamera2 is not None:
            camera = Picamera2()
            config = camera.create_preview_configuration(main={"format": "RGB888", "size": (1280, 720)})
            camera.configure(config)
            camera.start()
            rgb = camera.capture_array()
            camera.stop()
            frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        else:
            cap = cv2.VideoCapture(cam_idx, cv2.CAP_V4L2)
            ok, frame = cap.read()
            cap.release()
            if not ok:
                raise RuntimeError("Could not capture frame for calibration")
        frame = cv2.resize(frame, (IMAGE_SIZE, IMAGE_SIZE))

    clicks = []
    mouse_pos = [0, 0]

    def on_mouse(event, x, y, flags, param):
        mouse_pos[0], mouse_pos[1] = x, y
        if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < 4:
            clicks.append((x, y))
            print(f"  {CORNER_LABELS[len(clicks) - 1]}: x={x}, y={y}")

    cv2.namedWindow("Calibrate: click 4 corners (u=undo, Enter=done, q=quit)")
    cv2.setMouseCallback("Calibrate: click 4 corners (u=undo, Enter=done, q=quit)", on_mouse)
    print("Click the 4 board corners in order: Top-Left, Top-Right, Bottom-Right, Bottom-Left")
    print("Press u to undo the last click. Press Enter when done.")

    dot_colors = [(0, 255, 0), (0, 200, 255), (0, 0, 255), (255, 0, 200)]
    h, w = frame.shape[:2]

    while True:
        display = frame.copy()

        prompt = CORNER_LABELS[len(clicks)] if len(clicks) < 4 else "Done — press Enter"
        cv2.putText(display, f"Click: {prompt}  (u=undo)", (10, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2, cv2.LINE_AA)

        for i, (cx, cy) in enumerate(clicks):
            cv2.circle(display, (cx, cy), 7, dot_colors[i], -1)
            cv2.putText(display, CORNER_LABELS[i], (cx + 9, cy - 9),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, dot_colors[i], 1, cv2.LINE_AA)

        # Zoom inset — show magnified area around cursor in bottom-right
        mx, my = mouse_pos
        cx1 = max(ZOOM_RADIUS, min(w - ZOOM_RADIUS, mx)) - ZOOM_RADIUS
        cy1 = max(ZOOM_RADIUS, min(h - ZOOM_RADIUS, my)) - ZOOM_RADIUS
        patch = frame[cy1:cy1 + 2 * ZOOM_RADIUS, cx1:cx1 + 2 * ZOOM_RADIUS]
        zoom = cv2.resize(patch, (ZOOM_SIZE, ZOOM_SIZE), interpolation=cv2.INTER_LINEAR)
        zx = int((mx - cx1) / (2 * ZOOM_RADIUS) * ZOOM_SIZE)
        zy = int((my - cy1) / (2 * ZOOM_RADIUS) * ZOOM_SIZE)
        cv2.line(zoom, (zx, 0), (zx, ZOOM_SIZE), (0, 255, 255), 1)
        cv2.line(zoom, (0, zy), (ZOOM_SIZE, zy), (0, 255, 255), 1)
        display[h - ZOOM_SIZE - 5:h - 5, w - ZOOM_SIZE - 5:w - 5] = zoom
        cv2.rectangle(display, (w - ZOOM_SIZE - 6, h - ZOOM_SIZE - 6), (w - 4, h - 4), (0, 255, 255), 1)

        cv2.imshow("Calibrate: click 4 corners (u=undo, Enter=done, q=quit)", display)
        key = cv2.waitKey(30) & 0xFF

        if key == ord('u') and clicks:
            clicks.pop()
            print("  Undid last click")
        elif key in (13, ord('\r')) and len(clicks) == 4:
            break
        elif key == ord('q'):
            break

    cv2.destroyAllWindows()

    if len(clicks) == 4:
        corners_str = ",".join(f"{x},{y}" for x, y in clicks)
        corners_path = Path("board_corners.txt")
        corners_path.write_text(corners_str)
        print(f"\nCorners: {corners_str}")
        print(f"Saved to {corners_path}")
        print(f"\nRun detection with:")
        print(f"  python3 computer_vision/gomoku_cv.py --corners {corners_str} --mqtt")
    else:
        print("Calibration cancelled — need all 4 corners.")


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Smart Gomoku OpenCV board detector")
    parser.add_argument("--image", type=Path, help="Path to a captured board image")
    parser.add_argument("--camera", type=int, help="Camera number for webcam testing, usually 0")
    parser.add_argument("--corners", help="Board corners: tlx,tly,trx,try,brx,bry,blx,bly")
    parser.add_argument("--state", type=Path, default=Path("board_state.json"))
    parser.add_argument("--output", type=Path, default=Path("detected_board.jpg"))
    parser.add_argument("--black-mask", type=Path, default=Path("black_mask.jpg"))
    parser.add_argument("--white-mask", type=Path, default=Path("white_mask.jpg"))
    parser.add_argument("--feedback", action="store_true", help="Send B/W/E command to Arduino feedback client")
    parser.add_argument("--arduino-port", default="/dev/ttyACM0", help="Arduino serial port")
    parser.add_argument("--mqtt", action="store_true", help="Publish detected moves to MQTT broker")
    parser.add_argument("--mqtt-broker", default="localhost", help="MQTT broker address")
    parser.add_argument("--mqtt-topic", default="gomoku/move", help="MQTT topic to publish moves on")
    parser.add_argument("--calibrate", action="store_true", help="Click-to-calibrate board corners")
    parser.add_argument("--demo", action="store_true", help="Replay scripted game through MQTT/Arduino without camera")
    parser.add_argument("--demo-interval", type=float, default=2.0, help="Seconds between demo moves (default 2)")
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.image and args.camera is not None:
        parser.error("Use either --image or --camera, not both")
    if args.demo:
        run_demo_mode(args)
    elif args.calibrate:
        run_calibrate_mode(args)
    elif args.image:
        run_image_mode(args)
    elif args.camera is not None:
        run_camera_mode(args)
    else:
        print("No image or camera provided. Starting camera 0 by default.")
        args.camera = 0
        run_camera_mode(args)


if __name__ == "__main__":
    main()
