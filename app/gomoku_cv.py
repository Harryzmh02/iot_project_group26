import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

try:
    from picamera2 import Picamera2
except ModuleNotFoundError:
    Picamera2 = None

# Reuse the shared preprocessing module so both code paths stay in sync.
try:
    from image_preprocessing import preprocess_frame as _preprocess_frame
    _HAS_PREPROCESSING_MODULE = True
except ModuleNotFoundError:
    _HAS_PREPROCESSING_MODULE = False

BOARD_SIZE = 13
IMAGE_SIZE = 800
EMPTY = 0
BLACK = 1
WHITE = 2

# ArUco stickers sit at the four board corners *outside* the playing grid.
# IDs are assigned clockwise from the top-left.
ARUCO_MARKER_IDS = (0, 1, 2, 3)
# For each marker, pick the corner that faces the playable area (inner corner).
# OpenCV returns marker corners in order: TL, TR, BR, BL of the marker itself.
ARUCO_INNER_CORNER_INDEX = {
    0: 2,  # top-left marker      -> its bottom-right corner
    1: 3,  # top-right marker     -> its bottom-left corner
    2: 0,  # bottom-right marker  -> its top-left corner
    3: 1,  # bottom-left marker   -> its top-right corner
}
# Fraction of the playing-grid side that the ArUco quad extends beyond the grid.
# 0.0 = markers sit exactly on the outer grid intersections.
# 0.05 = markers sit ~5% of the board width outside the outer grid lines.
# Tune visually with test_aruco_grid.py until the drawn grid overlays the printed one.
ARUCO_PADDING_RATIO = 0.05


@dataclass
class Stone:
    color: str
    x: int
    y: int
    row: int
    col: int
    area: float


def preprocess_frame(frame):
    if _HAS_PREPROCESSING_MODULE:
        return _preprocess_frame(frame)
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


def _cluster_lines(positions, gap):
    """Merge line positions that are within gap pixels of each other."""
    if not positions:
        return []
    sorted_pos = sorted(positions)
    clusters = [[sorted_pos[0]]]
    for p in sorted_pos[1:]:
        if p - clusters[-1][-1] < gap:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [int(np.mean(c)) for c in clusters]


def _detect_aruco_markers(gray_frame):
    """Run ArUco detection, handling both new (>=4.7) and legacy OpenCV APIs."""
    aruco = getattr(cv2, "aruco", None)
    if aruco is None:
        return [], None

    dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    if hasattr(aruco, "DetectorParameters"):
        parameters = aruco.DetectorParameters()
    else:
        parameters = aruco.DetectorParameters_create()

    if hasattr(aruco, "ArucoDetector"):
        detector = aruco.ArucoDetector(dictionary, parameters)
        corners, ids, _ = detector.detectMarkers(gray_frame)
    else:
        corners, ids, _ = aruco.detectMarkers(gray_frame, dictionary, parameters=parameters)

    return corners, ids


def detect_marker_corners(frame):
    """Detect four ArUco markers (IDs 0..3) and return board corners as
    [TL, TR, BR, BL] of the marker quad (i.e. the inner corners of each marker).

    Returns None if ArUco is unavailable or not all four markers are visible.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    marker_corners_list, ids = _detect_aruco_markers(gray)
    if ids is None:
        return None

    found = {}
    for marker_corners, marker_id in zip(marker_corners_list, np.array(ids).reshape(-1)):
        marker_id = int(marker_id)
        if marker_id not in ARUCO_INNER_CORNER_INDEX:
            continue
        points = np.array(marker_corners[0], dtype=np.float32)
        found[marker_id] = points[ARUCO_INNER_CORNER_INDEX[marker_id]]

    if not all(marker_id in found for marker_id in ARUCO_MARKER_IDS):
        return None

    return np.array([found[0], found[1], found[2], found[3]], dtype=np.float32)


def auto_detect_corners(image):
    """Detect board corners automatically using Hough line transform.

    Returns a (4, 2) float32 array [TL, TR, BR, BL], or None if detection fails.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 100)

    h, w = image.shape[:2]
    min_line_len = int(min(h, w) * 0.15)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=60,
        minLineLength=min_line_len,
        maxLineGap=20,
    )
    if lines is None:
        return None

    h_positions, v_positions = [], []
    for x1, y1, x2, y2 in lines[:, 0]:
        angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        if angle < 20 or angle > 160:
            h_positions.append((y1 + y2) / 2)
        elif 70 < angle < 110:
            v_positions.append((x1 + x2) / 2)

    cluster_gap = min(h, w) * 0.04
    h_clusters = _cluster_lines(h_positions, cluster_gap)
    v_clusters = _cluster_lines(v_positions, cluster_gap)

    if len(h_clusters) < 2 or len(v_clusters) < 2:
        return None

    top, bottom = h_clusters[0], h_clusters[-1]
    left, right = v_clusters[0], v_clusters[-1]

    if bottom - top < min(h, w) * 0.3 or right - left < min(h, w) * 0.3:
        return None

    # The outermost detected lines are often one cell inside the real board edge.
    # Expand outward by one estimated cell gap so the warp covers the full grid.
    h_gap = (bottom - top) / (BOARD_SIZE - 1)
    v_gap = (right - left) / (BOARD_SIZE - 1)
    n_h_missing = (BOARD_SIZE - len(h_clusters)) / 2
    n_v_missing = (BOARD_SIZE - len(v_clusters)) / 2
    top = int(top - h_gap * max(n_h_missing, 0.5))
    bottom = int(bottom + h_gap * max(n_h_missing, 0.5))
    left = int(left - v_gap * max(n_v_missing, 0.5))
    right = int(right + v_gap * max(n_v_missing, 0.5))

    return np.array(
        [[left, top], [right, top], [right, bottom], [left, bottom]],
        dtype=np.float32,
    )


def warp_board(image, corners, output_size=IMAGE_SIZE, padding_ratio=ARUCO_PADDING_RATIO):
    """Warp the source quad onto an `output_size` square so the *playing grid*
    fills the output. When `padding_ratio` > 0, the input corners are treated
    as sitting that fraction *outside* the playing grid, so we map them to a
    target rectangle that extends off-canvas — pulling the playing grid back
    to fill 0..output_size."""
    source = order_corners(corners)
    pad = padding_ratio * output_size
    target = np.array(
        [
            [-pad, -pad],
            [output_size - 1 + pad, -pad],
            [output_size - 1 + pad, output_size - 1 + pad],
            [-pad, output_size - 1 + pad],
        ],
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
    return np.hypot(x - expected_x, y - expected_y) <= cell_gap * 0.50


def _classify_stone_color(board_image, x, y, radius):
    """Sample pixels inside the circle to determine black or white stone."""
    hsv = cv2.cvtColor(board_image, cv2.COLOR_BGR2HSV)
    mask = np.zeros(board_image.shape[:2], dtype=np.uint8)
    cv2.circle(mask, (x, y), max(1, radius // 2), 255, -1)
    mean_v = cv2.mean(hsv, mask=mask)[2]
    mean_s = cv2.mean(hsv, mask=mask)[1]
    if mean_v < 90:
        return "black"
    if mean_v > 140 and mean_s < 70:
        return "white"
    return None


def find_stones(board_image):
    image_size = board_image.shape[0]
    cell_gap = image_size / (BOARD_SIZE - 1)
    min_radius = int(cell_gap * 0.22)
    max_radius = int(cell_gap * 0.46)

    gray = cv2.cvtColor(board_image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (9, 9), 2)

    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1,
        minDist=int(cell_gap * 0.7),
        param1=50,
        param2=20,
        minRadius=min_radius,
        maxRadius=max_radius,
    )

    board = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.uint8)
    stones = []
    dummy_mask = np.zeros((image_size, image_size), dtype=np.uint8)

    if circles is None:
        return board, stones, dummy_mask, dummy_mask

    for cx, cy, r in np.round(circles[0]).astype(int):
        row, col = point_to_board_position(cx, cy, image_size)
        if not is_near_grid_intersection(cx, cy, row, col, image_size):
            continue
        color = _classify_stone_color(board_image, cx, cy, r)
        if color is None:
            continue
        value = BLACK if color == "black" else WHITE
        if board[row, col] == EMPTY:
            board[row, col] = value
            stones.append(Stone(color=color, x=cx, y=cy, row=row, col=col, area=np.pi * r * r))

    return board, stones, dummy_mask, dummy_mask


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
    from arduino_feedback_client import ArduinoFeedbackClient

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
