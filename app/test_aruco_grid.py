"""Quick test: detect ArUco corners and overlay a 13x13 grid.

Usage:
    python test_aruco_grid.py path/to/board_image.jpg
"""
import sys
import cv2
import numpy as np
from gomoku_cv import detect_marker_corners, auto_detect_corners, warp_board, BOARD_SIZE, IMAGE_SIZE


def draw_grid(image, board_size=BOARD_SIZE, color=(0, 200, 0), thickness=1):
    size = image.shape[0]
    gap = size / (board_size - 1)
    out = image.copy()
    for i in range(board_size):
        pos = int(round(i * gap))
        cv2.line(out, (pos, 0), (pos, size), color, thickness)
        cv2.line(out, (0, pos), (size, pos), color, thickness)
    # Mark intersections
    for r in range(board_size):
        for c in range(board_size):
            cx = int(round(c * gap))
            cy = int(round(r * gap))
            cv2.circle(out, (cx, cy), 3, (0, 0, 255), -1)
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "board.jpg"
    frame = cv2.imread(path)
    if frame is None:
        print(f"Could not open: {path}")
        sys.exit(1)

    corners = detect_marker_corners(frame)
    if corners is not None:
        method = "ArUco markers"
    else:
        corners = auto_detect_corners(frame)
        method = "Hough lines (ArUco fallback)" if corners is not None else None

    if corners is None:
        print("No corners detected.")
        cv2.imwrite("aruco_no_corners.jpg", frame)
        print("Saved aruco_no_corners.jpg (raw frame for inspection).")
        return

    print(f"Corners detected via: {method}")
    print(f"Corners (TL TR BR BL):\n{corners}")

    warped = warp_board(frame, corners, output_size=IMAGE_SIZE)
    result = draw_grid(warped)

    original_annotated = frame.copy()
    labels = ["TL", "TR", "BR", "BL"]
    for (x, y), label in zip(corners.astype(int), labels):
        cv2.circle(original_annotated, (x, y), 10, (0, 255, 0), -1)
        cv2.putText(original_annotated, label, (x + 12, y - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2, cv2.LINE_AA)

    cv2.imwrite("aruco_corners_on_original.jpg", original_annotated)
    cv2.imwrite("aruco_grid_result.jpg", result)
    print("Saved aruco_corners_on_original.jpg and aruco_grid_result.jpg")


if __name__ == "__main__":
    main()
