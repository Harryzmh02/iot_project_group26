import argparse
import json
import sys
from dataclasses import asdict, dataclass
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

GRID_MARGIN = 34
MIN_GRID_DISTANCE_RATIO = 0.34
MIN_STONE_AREA_RATIO = 0.00055
MAX_STONE_AREA_RATIO = 0.010
MIN_CIRCULARITY = 0.58
MIN_RADIUS_RATIO = 0.012
MAX_RADIUS_RATIO = 0.055
BLACK_VALUE_MAX = 88
WHITE_VALUE_MIN = 145
WHITE_SAT_MAX = 95
DEBUG_WARPED_PATH = Path("warped_board.jpg")


@dataclass
class Stone:
    color: str
    x: int
    y: int
    row: int
    col: int
    area: float
    radius: float
    distance_to_grid: float


def preprocess_frame(frame):
    """Resize, normalize contrast lightly, and blur for stable thresholding."""
    resized = cv2.resize(frame, (IMAGE_SIZE, IMAGE_SIZE), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(resized, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
    normalized = cv2.merge((clahe.apply(l_channel), a_channel, b_channel))
    bgr = cv2.cvtColor(normalized, cv2.COLOR_LAB2BGR)
    return cv2.GaussianBlur(bgr, (5, 5), 0)


def order_corners(points):
    pts = np.array(points, dtype=np.float32)
    if pts.shape != (4, 2):
        raise ValueError("Corners must describe exactly four x,y points")
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
    try:
        values = [float(value.strip()) for value in corner_text.split(",") if value.strip()]
    except Exception as exc:
        raise ValueError("Corners must be comma-separated numbers: tlx,tly,trx,try,brx,bry,blx,bly") from exc
    if len(values) != 8:
        raise ValueError("Corners must contain exactly 8 numbers: tlx,tly,trx,try,brx,bry,blx,bly")
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


def grid_point(row, col, image_size):
    cell_gap = image_size / (BOARD_SIZE - 1)
    return col * cell_gap, row * cell_gap


def is_near_grid_intersection(x, y, row, col, image_size):
    expected_x, expected_y = grid_point(row, col, image_size)
    return np.hypot(x - expected_x, y - expected_y) <= (image_size / (BOARD_SIZE - 1)) * MIN_GRID_DISTANCE_RATIO


def _playable_mask(image_size):
    mask = np.zeros((image_size, image_size), dtype=np.uint8)
    cv2.rectangle(mask, (GRID_MARGIN, GRID_MARGIN), (image_size - GRID_MARGIN, image_size - GRID_MARGIN), 255, -1)
    return mask


def _remove_grid_lines(mask, image_size):
    """Suppress straight board lines while keeping round stones."""
    cell_gap = image_size / (BOARD_SIZE - 1)
    cleaned = mask.copy()
    line_width = max(2, int(cell_gap * 0.055))
    for index in range(BOARD_SIZE):
        pos = int(round(index * cell_gap))
        cv2.line(cleaned, (pos, 0), (pos, image_size - 1), 0, line_width)
        cv2.line(cleaned, (0, pos), (image_size - 1, pos), 0, line_width)
    return cleaned


def _is_marker_or_edge_blob(x, y, row, col, image_size):
    near_outer_image = x < 20 or y < 20 or x > image_size - 20 or y > image_size - 20
    outside_grid_band = row in (0, BOARD_SIZE - 1) and (y < GRID_MARGIN or y > image_size - GRID_MARGIN)
    outside_grid_band = outside_grid_band or (col in (0, BOARD_SIZE - 1) and (x < GRID_MARGIN or x > image_size - GRID_MARGIN))
    return near_outer_image or outside_grid_band


def find_stones_from_mask(mask, color, image_size, rejected=None):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = image_size * image_size * MIN_STONE_AREA_RATIO
    max_area = image_size * image_size * MAX_STONE_AREA_RATIO
    min_radius = image_size * MIN_RADIUS_RATIO
    max_radius = image_size * MAX_RADIUS_RATIO
    stones = []

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area or area > max_area:
            if rejected is not None and area >= min_area * 0.5:
                rejected.append(f"{color}: area {area:.1f} outside range")
            continue

        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0:
            continue
        circularity = 4 * np.pi * area / (perimeter * perimeter)
        if circularity < MIN_CIRCULARITY:
            if rejected is not None:
                rejected.append(f"{color}: circularity {circularity:.2f} too low")
            continue

        (cx, cy), radius = cv2.minEnclosingCircle(contour)
        if radius < min_radius or radius > max_radius:
            if rejected is not None:
                rejected.append(f"{color}: radius {radius:.1f} outside range")
            continue

        moments = cv2.moments(contour)
        if moments["m00"] == 0:
            continue

        x = int(moments["m10"] / moments["m00"])
        y = int(moments["m01"] / moments["m00"])
        row, col = point_to_board_position(x, y, image_size)
        expected_x, expected_y = grid_point(row, col, image_size)
        distance = float(np.hypot(x - expected_x, y - expected_y))

        if _is_marker_or_edge_blob(x, y, row, col, image_size):
            if rejected is not None:
                rejected.append(f"{color}: rejected edge/marker blob at {x},{y}")
            continue
        if not is_near_grid_intersection(x, y, row, col, image_size):
            if rejected is not None:
                rejected.append(f"{color}: blob at {x},{y} too far from grid")
            continue

        stones.append(Stone(color=color, x=x, y=y, row=row, col=col, area=area, radius=radius, distance_to_grid=distance))

    return stones


def find_stones(board_image, return_rejections=False):
    image_size = board_image.shape[0]
    hsv = cv2.cvtColor(board_image, cv2.COLOR_BGR2HSV)

    black_mask = cv2.inRange(hsv, np.array([0, 0, 0]), np.array([180, 255, BLACK_VALUE_MAX]))
    white_mask = cv2.inRange(hsv, np.array([0, 0, WHITE_VALUE_MIN]), np.array([180, WHITE_SAT_MAX, 255]))

    playable = _playable_mask(image_size)
    black_mask = cv2.bitwise_and(black_mask, playable)
    white_mask = cv2.bitwise_and(white_mask, playable)
    black_mask = _remove_grid_lines(black_mask, image_size)

    kernel = np.ones((5, 5), np.uint8)
    black_mask = cv2.morphologyEx(black_mask, cv2.MORPH_OPEN, kernel)
    black_mask = cv2.morphologyEx(black_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_OPEN, kernel)
    white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    rejected = []
    detected = []
    detected.extend(find_stones_from_mask(black_mask, "black", image_size, rejected))
    detected.extend(find_stones_from_mask(white_mask, "white", image_size, rejected))

    board = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.uint8)
    stones = []
    for stone in sorted(detected, key=lambda item: (item.area, -item.distance_to_grid), reverse=True):
        value = BLACK if stone.color == "black" else WHITE
        if board[stone.row, stone.col] == EMPTY:
            board[stone.row, stone.col] = value
            stones.append(stone)
        else:
            rejected.append(f"{stone.color}: duplicate blob in cell {stone.row},{stone.col}")

    if return_rejections:
        return board, stones, black_mask, white_mask, rejected
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
                changes.append({"type": "new_move", "row": row, "col": col, "color": "black" if new_value == BLACK else "white"})
            else:
                changes.append({"type": "changed_or_removed", "row": row, "col": col, "old": old_value, "new": new_value})
    return changes


def validate_single_move(changes, last_published=None):
    if not changes:
        return None, "no board change"
    new_moves = [change for change in changes if change["type"] == "new_move"]
    uncertain = [change for change in changes if change["type"] != "new_move"]
    if uncertain:
        return None, f"uncertain changed/removed cells: {uncertain}"
    if len(new_moves) != 1:
        return None, f"expected exactly one new move, got {len(new_moves)}"
    move = new_moves[0]
    key = (move["row"], move["col"], move["color"])
    if last_published == key:
        return None, f"duplicate move suppressed: {key}"
    return move, "valid move"


class TemporalMoveConfirmor:
    def __init__(self, required_frames=2):
        self.required_frames = required_frames
        self.pending_key = None
        self.pending_count = 0
        self.last_published = None

    def update(self, move):
        if move is None:
            self.pending_key = None
            self.pending_count = 0
            return False
        key = (move["row"], move["col"], move["color"])
        if key == self.last_published:
            return False
        if key == self.pending_key:
            self.pending_count += 1
        else:
            self.pending_key = key
            self.pending_count = 1
        if self.pending_count >= self.required_frames:
            self.last_published = key
            self.pending_key = None
            self.pending_count = 0
            return True
        return False

    def reset(self):
        self.pending_key = None
        self.pending_count = 0
        self.last_published = None


def draw_results(board_image, stones):
    output = board_image.copy()
    image_size = output.shape[0]
    cell_gap = image_size / (BOARD_SIZE - 1)
    for index in range(BOARD_SIZE):
        position = int(round(index * cell_gap))
        cv2.line(output, (position, 0), (position, image_size), (190, 190, 190), 1)
        cv2.line(output, (0, position), (image_size, position), (190, 190, 190), 1)
    for stone in stones:
        color = (0, 0, 255) if stone.color == "black" else (0, 180, 0)
        cv2.circle(output, (stone.x, stone.y), int(max(14, stone.radius)), color, 3)
        cv2.putText(output, f"{stone.row},{stone.col}", (stone.x + 8, stone.y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    return output


def process_frame(frame, corners=None, save_warped=False):
    try:
        if corners is not None:
            board_image = warp_board(frame, corners)
            if save_warped:
                cv2.imwrite(str(DEBUG_WARPED_PATH), board_image)
        else:
            board_image = preprocess_frame(frame)
        board, stones, black_mask, white_mask = find_stones(board_image)
        return board, stones, draw_results(board_image, stones), black_mask, white_mask
    except Exception as exc:
        print(f"[CV] Frame processing failed: {exc}")
        empty = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.uint8)
        blank = np.zeros((IMAGE_SIZE, IMAGE_SIZE), dtype=np.uint8)
        fallback = preprocess_frame(frame) if frame is not None else np.zeros((IMAGE_SIZE, IMAGE_SIZE, 3), dtype=np.uint8)
        return empty, [], fallback, blank, blank


def load_board_state(path):
    if not path.exists():
        return np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.uint8)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        board = data["board"] if isinstance(data, dict) else data
        arr = np.array(board, dtype=np.uint8)
        if arr.shape == (BOARD_SIZE, BOARD_SIZE):
            return arr
    except Exception as exc:
        print(f"[State] Could not read {path}: {exc}")
    return np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.uint8)


def load_move_counter(path):
    if not path.exists():
        return 1
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return int(data.get("move_number", 1))
    except Exception as exc:
        print(f"[State] Could not read move counter from {path}: {exc}")
    return 1


def save_board_state(path, board, move_number=1):
    data = {"board": board.astype(int).tolist(), "move_number": int(move_number)}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def print_board(board):
    symbols = {EMPTY: ".", BLACK: "B", WHITE: "W"}
    print("\nDetected board matrix:")
    for row in range(BOARD_SIZE):
        print(f"{row:02d}: " + " ".join(symbols[int(board[row, col])] for col in range(BOARD_SIZE)))


def create_feedback_client(port):
    from raspberrypi_integration.arduino_feedback_client import ArduinoFeedbackClient
    return ArduinoFeedbackClient(port=port)


def create_mqtt_client(broker, port=1883):
    if mqtt_client is None:
        print("[MQTT] paho-mqtt not installed; skipping MQTT publish")
        return None
    try:
        try:
            client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2)
        except Exception:
            client = mqtt_client.Client()
        client.connect(broker, port, 60)
        client.loop_start()
        print(f"[MQTT] Connected to broker {broker}:{port}")
        return client
    except Exception as exc:
        print(f"[MQTT] Could not connect to broker {broker}:{port}: {exc}")
        return None


def publish_move(client, topic, move_number, color, row, col):
    payload = json.dumps({
        "player": color,
        "row": row + 1,
        "column": col + 1,
        "move_number": move_number,
        "timestamp": datetime.now().isoformat(),
    })
    client.publish(topic, payload)
    print(f"[MQTT] Published: {payload}")


def send_feedback(feedback, changes, mqtt=None, topic="gomoku/move", move_counter=None, last_published=None):
    move, reason = validate_single_move(changes, last_published=last_published)
    if move is None:
        if changes:
            print(f"[CV] Rejected detection: {reason}")
            if feedback:
                try:
                    print(f"[Arduino] {feedback.error()}")
                except Exception as exc:
                    print(f"[Arduino] Error feedback failed: {exc}")
        return None

    if feedback:
        try:
            reply = feedback.black_move() if move["color"] == "black" else feedback.white_move()
            print(f"[Arduino] {reply}")
        except Exception as exc:
            print(f"[Arduino] Feedback failed: {exc}")
    if mqtt:
        move_num = next(move_counter) if move_counter else 1
        publish_move(mqtt, topic, move_num, move["color"], move["row"], move["col"])
    return move


def _parse_corners_or_none(corner_text):
    if not corner_text:
        return None
    try:
        return parse_corners(corner_text)
    except ValueError as exc:
        print(f"[CV] Bad --corners value: {exc}")
        print("[CV] Continuing with safe fallback resize instead of perspective warp.")
        return None


def run_image_mode(args):
    image = cv2.imread(str(args.image))
    if image is None:
        print(f"[CV] Could not open image: {args.image}")
        return 2

    corners = _parse_corners_or_none(args.corners)
    board, stones, result_image, black_mask, white_mask = process_frame(image, corners, save_warped=corners is not None)
    old_board = load_board_state(args.state)
    changes = compute_delta(old_board, board)
    _, _, _, _, rejected = find_stones(warp_board(image, corners) if corners is not None else preprocess_frame(image), return_rejections=True)

    print_board(board)
    print("\nDetected stones list:")
    for stone in stones:
        print(f"- {stone.color} row={stone.row} col={stone.col} pixel=({stone.x},{stone.y}) area={stone.area:.1f}")
    if not stones:
        print("- none")

    print("\nRejected detection reasons:")
    for reason in rejected[:20]:
        print(f"- {reason}")
    if not rejected:
        print("- none")

    print("\nMove validation:")
    last_key = None
    move, reason = validate_single_move(changes, last_published=last_key)
    if move:
        print(f"- valid move: {move['color']} at row {move['row']}, col {move['col']}")
    else:
        print(f"- rejected: {reason}")

    feedback = None
    if args.feedback:
        feedback = create_feedback_client(args.arduino_port)
        if not feedback.connect():
            print("[Arduino] Not connected; continuing without feedback.")
            feedback = None

    mqtt = create_mqtt_client(args.mqtt_broker) if args.mqtt else None
    move_number = load_move_counter(args.state)
    published = None
    try:
        published = send_feedback(feedback, changes, mqtt=mqtt, topic=args.mqtt_topic, move_counter=iter([move_number]))
    finally:
        if feedback:
            feedback.close()
        if mqtt:
            mqtt.loop_stop()
            try:
                mqtt.disconnect()
            except Exception:
                pass

    next_move_number = move_number + (1 if published else 0)
    save_board_state(args.state, board, next_move_number)
    cv2.imwrite(str(args.output), result_image)
    cv2.imwrite(str(args.black_mask), black_mask)
    cv2.imwrite(str(args.white_mask), white_mask)
    print(f"\nSaved debug images: {args.output}, {args.black_mask}, {args.white_mask}")
    if corners is not None:
        print(f"Saved warped board: {DEBUG_WARPED_PATH}")
    print(f"Saved board state: {args.state}")
    return 0


def _open_feedback_and_mqtt(args):
    feedback = None
    if args.feedback:
        feedback = create_feedback_client(args.arduino_port)
        if not feedback.connect():
            print("[Arduino] Not connected; feedback disabled.")
            feedback = None
    mqtt = create_mqtt_client(args.mqtt_broker) if args.mqtt else None
    return feedback, mqtt


def _handle_camera_frame(frame, corners, old_board, confirmor, feedback, mqtt, topic, move_number):
    board, stones, result_image, _, _ = process_frame(frame, corners)
    changes = compute_delta(old_board, board)
    move, reason = validate_single_move(changes, last_published=confirmor.last_published)
    if move is None:
        if changes:
            print(f"[CV] Rejected frame: {reason}")
        return old_board, move_number, result_image
    if not confirmor.update(move):
        print(f"[CV] Candidate move waiting for second stable frame: {move}")
        return old_board, move_number, result_image
    sent = send_feedback(feedback, changes, mqtt=mqtt, topic=topic, move_counter=iter([move_number]), last_published=None)
    if sent:
        print(f"[CV] Valid move committed: {sent}")
        return board.copy(), move_number + 1, result_image
    return old_board, move_number, result_image


def run_camera_mode(args):
    from raspberrypi_capture.frame_stability import FrameStabilityChecker

    corners = _parse_corners_or_none(args.corners)
    feedback, mqtt = _open_feedback_and_mqtt(args)
    old_board = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.uint8)
    move_number = 1
    confirmor = TemporalMoveConfirmor(required_frames=args.confirm_frames)
    stability = FrameStabilityChecker(required_stable_frames=args.stable_frames, diff_threshold=args.diff_threshold)

    if Picamera2 is not None and args.camera is None:
        camera = Picamera2()
        config = camera.create_preview_configuration(main={"format": "RGB888", "size": (1280, 720)})
        camera.configure(config)
        camera.start()
        capture = lambda: cv2.cvtColor(camera.capture_array(), cv2.COLOR_RGB2BGR)
        close_camera = camera.stop
        print("[Camera] Started Picamera2.")
    else:
        camera_index = 0 if args.camera is None else args.camera
        camera = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
        if not camera.isOpened():
            print("[Camera] Could not open camera. Check Pi camera, Picamera2, or --camera index.")
            return 2
        capture = lambda: camera.read()[1]
        close_camera = camera.release
        print(f"[Camera] Started OpenCV camera index {camera_index}.")

    try:
        while True:
            frame = capture()
            if frame is None:
                print("[Camera] Empty frame; skipping.")
                continue
            if not stability.update(frame):
                continue
            old_board, move_number, result_image = _handle_camera_frame(
                frame, corners, old_board, confirmor, feedback, mqtt, args.mqtt_topic, move_number
            )
            stability.reset()
            if args.display:
                cv2.imshow("Gomoku OpenCV Detection", result_image)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        print("[Camera] Stopped by user.")
    finally:
        close_camera()
        if feedback:
            feedback.close()
        if mqtt:
            mqtt.loop_stop()
            try:
                mqtt.disconnect()
            except Exception:
                pass
        if args.display:
            cv2.destroyAllWindows()
    return 0


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
    parser.add_argument("--stable-frames", type=int, default=3, help="Stable camera frames required before CV")
    parser.add_argument("--diff-threshold", type=float, default=5.0, help="Mean frame difference threshold")
    parser.add_argument("--confirm-frames", type=int, default=2, help="Frames that must agree before publishing a move")
    parser.add_argument("--display", action="store_true", help="Show OpenCV preview window")
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.image and args.camera is not None:
        parser.error("Use either --image or --camera, not both")
    if args.image:
        return run_image_mode(args)
    return run_camera_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
