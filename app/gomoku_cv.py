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


# Known hoshi (star point) grid positions on a 15x15 board, (row, col) 0-indexed.
# Standard layout: 3x3 arrangement at rows/cols 3, 7, 11.
_HOSHI_GRID = np.array(
    [[3, 3], [3, 7], [3, 11],
     [7, 3], [7, 7], [7, 11],
     [11, 3], [11, 7], [11, 11]],
    dtype=np.float32,
)


def _detect_hoshi_candidates(gray, h, w):
    """Find all hoshi-like dark dots in the inner 80% of the image.

    Uses an adaptive darkness threshold relative to the local background median,
    so it works on boards of any color (wood, blue, etc.).
    Returns a list of (x, y) pixel coordinates.
    """
    mh, mw = int(h * 0.10), int(w * 0.10)
    roi = gray[mh : h - mh, mw : w - mw]
    blurred = cv2.GaussianBlur(roi, (7, 7), 2)

    min_r = max(3, int(min(h, w) / 90))
    max_r = max(12, int(min(h, w) / 25))

    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1,
        minDist=int(min(h, w) * 0.04),
        param1=50,
        param2=10,
        minRadius=min_r,
        maxRadius=max_r,
    )
    if circles is None:
        return []

    bg_median = float(np.median(roi))
    dark_threshold = bg_median * 0.75  # hoshi must be ≥25% darker than background

    candidates = []
    for cx, cy, r in np.round(circles[0]).astype(int):
        fx, fy = cx + mw, cy + mh
        if not (0 < fx < w and 0 < fy < h):
            continue
        mask = np.zeros_like(gray)
        cv2.circle(mask, (fx, fy), max(1, r // 2), 255, -1)
        mean_v = cv2.mean(gray, mask=mask)[0]
        if mean_v < dark_threshold:
            candidates.append((fx, fy))

    return candidates


def _hoshi_homography(candidates):
    """Compute a perspective homography from hoshi pixel coords to grid coords.

    Assigns detected candidates to the 3x3 hoshi grid positions and computes
    H such that H * pixel_coord ≈ warped_image_coord for each hoshi.
    Returns the 3x3 homography matrix, or None if assignment fails.
    """
    pts = np.array(candidates, dtype=np.float32)
    n = len(pts)

    if n < 4:
        return None

    if n == 9:
        # Sort into 3 rows (by y) then 3 cols (by x within each row)
        order = np.lexsort((pts[:, 0], pts[:, 1]))
        pts_sorted = pts[order]
        rows = []
        for i in range(3):
            row = pts_sorted[i * 3 : (i + 1) * 3]
            rows.append(row[np.argsort(row[:, 0])])
        src_pts = np.vstack(rows)
        grid = _HOSHI_GRID
    else:
        # Pick the 4 extremal points — they map to the 4 corner hoshi
        sums = pts.sum(axis=1)
        diffs = pts[:, 0] - pts[:, 1]
        tl = pts[np.argmin(sums)]
        br = pts[np.argmax(sums)]
        tr = pts[np.argmax(diffs)]
        bl = pts[np.argmin(diffs)]
        src_pts = np.array([tl, tr, br, bl], dtype=np.float32)
        # Corner hoshi: (3,3) TL, (3,11) TR, (11,11) BR, (11,3) BL
        grid = np.array([[3, 3], [3, 11], [11, 11], [11, 3]], dtype=np.float32)

    # Target: hoshi pixel positions in the 800×800 warped output
    cell = IMAGE_SIZE / (BOARD_SIZE - 1)
    dst_pts = np.array([[col * cell, row * cell] for row, col in grid], dtype=np.float32)

    if len(src_pts) == 4:
        M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    else:
        M, _ = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)

    return M


def auto_detect_corners(image):
    """Detect board corners via hoshi-based perspective homography.

    Finds the 9 star points, builds a homography from their raw-image pixel
    positions to their known warped-grid positions, then inverse-maps the 4
    board corner grid intersections back into raw-image space.

    This correctly handles tilted cameras and perspective distortion because
    the homography encodes the full projective transform — not just a uniform
    cell gap.

    Returns a (4, 2) float32 array [TL, TR, BR, BL] in raw-image pixel coords,
    or None if detection fails.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = image.shape[:2]

    candidates = _detect_hoshi_candidates(gray, h, w)

    if len(candidates) >= 4:
        M = _hoshi_homography(candidates)
        if M is not None:
            sz = float(IMAGE_SIZE - 1)
            board_corners_warped = np.array(
                [[0, 0], [sz, 0], [sz, sz], [0, sz]], dtype=np.float32
            ).reshape(1, -1, 2)
            M_inv = np.linalg.inv(M)
            corners_raw = cv2.perspectiveTransform(board_corners_warped, M_inv).reshape(-1, 2)
            print(f"[CV] Hoshi anchor: {len(candidates)} dots → corners {corners_raw.tolist()}")
            return corners_raw.astype(np.float32)

    # Fallback: expand outermost detected grid lines
    return _corners_from_lines(gray, h, w)


def _corners_from_lines(gray, h, w):
    """Line-based corner detection fallback (used when hoshi detection fails)."""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 100)
    min_line_len = int(min(h, w) * 0.15)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=60,
        minLineLength=min_line_len,
        maxLineGap=20,
    )

    h_positions, v_positions = [], []
    if lines is not None:
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

    h_gap = (bottom - top) / (len(h_clusters) - 1)
    v_gap = (right - left) / (len(v_clusters) - 1)
    n_h = (BOARD_SIZE - len(h_clusters)) / 2
    n_v = (BOARD_SIZE - len(v_clusters)) / 2
    top = int(top - h_gap * max(n_h, 0.5))
    bottom = int(bottom + h_gap * max(n_h, 0.5))
    left = int(left - v_gap * max(n_v, 0.5))
    right = int(right + v_gap * max(n_v, 0.5))

    print("[CV] Corner fallback: line expansion (no hoshi pattern found)")
    return np.array(
        [[left, top], [right, top], [right, bottom], [left, bottom]],
        dtype=np.float32,
    )


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
    return row, col


def is_within_board(row, col):
    return 0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE


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
        if not is_within_board(row, col):
            continue
        if not is_near_grid_intersection(cx, cy, row, col, image_size):
            continue
        # Exclude the 4 corner 2x2 zones — magnetic board clips live there
        if (row <= 1 or row >= BOARD_SIZE - 2) and (col <= 1 or col >= BOARD_SIZE - 2):
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
