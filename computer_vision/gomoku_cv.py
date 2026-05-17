import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

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
    board, stones, black_mask, white_mask = find_stones(board_image)
    return board, stones, draw_results(board_image, stones), black_mask, white_mask


def load_board_state(path):
    if not path.exists():
        return np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.uint8)
    return np.array(json.loads(path.read_text(encoding="utf-8")), dtype=np.uint8)


def save_board_state(path, board):
    path.write_text(json.dumps(board.astype(int).tolist(), indent=2), encoding="utf-8")


def print_board(board):
    symbols = {EMPTY: ".", BLACK: "B", WHITE: "W"}
    print("\nDetected board:")
    for row in range(BOARD_SIZE):
        print(f"{row:02d}: " + " ".join(symbols[int(board[row, col])] for col in range(BOARD_SIZE)))


def create_feedback_client(port):
    from raspberrypi_integration.arduino_feedback_client import ArduinoFeedbackClient

    return ArduinoFeedbackClient(port=port)


def send_feedback(feedback, changes):
    new_moves = [change for change in changes if change["type"] == "new_move"]
    uncertain_changes = [change for change in changes if change["type"] != "new_move"]

    if len(new_moves) == 1 and not uncertain_changes:
        move = new_moves[0]
        if move["color"] == "black":
            print(f"[Arduino] {feedback.black_move()}")
        else:
            print(f"[Arduino] {feedback.white_move()}")
    elif changes:
        print("[CV] Uncertain board update, sending error feedback")
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

    if args.feedback:
        feedback = create_feedback_client(args.arduino_port)
        if feedback.connect():
            try:
                send_feedback(feedback, changes)
            finally:
                feedback.close()

    save_board_state(args.state, board)
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

    old_board = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.uint8)
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

            if feedback:
                send_feedback(feedback, changes)

            old_board = board.copy()
            cv2.imshow("Gomoku OpenCV Detection", result_image)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        if feedback:
            feedback.close()
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

    old_board = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.uint8)
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

            if feedback:
                send_feedback(feedback, changes)

            old_board = board.copy()
            cv2.imshow("Gomoku OpenCV Detection", result_image)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.stop()
        if feedback:
            feedback.close()
        cv2.destroyAllWindows()


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
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.image and args.camera is not None:
        parser.error("Use either --image or --camera, not both")
    if args.image:
        run_image_mode(args)
    elif args.camera is not None:
        run_camera_mode(args)
    else:
        print("No image or camera provided. Starting camera 0 by default.")
        args.camera = 0
        run_camera_mode(args)


if __name__ == "__main__":
    main()
