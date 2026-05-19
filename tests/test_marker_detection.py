import os
import sys

import numpy as np


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import gomoku_cv


_orig_detect_aruco_markers = gomoku_cv._detect_aruco_markers


def reset_state():
    gomoku_cv._detect_aruco_markers = _orig_detect_aruco_markers


def marker(points):
    return np.array([points], dtype=np.float32)


def test_detect_marker_corners_orders_points_correctly():
    reset_state()

    gomoku_cv._detect_aruco_markers = lambda gray: (
        [
            marker([(80, 80), (90, 80), (90, 90), (80, 90)]),  # id 2
            marker([(10, 10), (20, 10), (20, 20), (10, 20)]),  # id 0
            marker([(10, 80), (20, 80), (20, 90), (10, 90)]),  # id 3
            marker([(80, 10), (90, 10), (90, 20), (80, 20)]),  # id 1
        ],
        np.array([[2], [0], [3], [1]], dtype=np.int32),
    )

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    corners = gomoku_cv.detect_marker_corners(frame)

    expected = np.array([(20, 20), (80, 20), (80, 80), (20, 80)], dtype=np.float32)
    assert corners is not None
    assert np.array_equal(corners, expected)
    print("PASS: detect_marker_corners returns tl/tr/br/bl order from marker IDs")


def test_detect_marker_corners_returns_none_when_any_marker_is_missing():
    reset_state()

    gomoku_cv._detect_aruco_markers = lambda gray: (
        [
            marker([(10, 10), (20, 10), (20, 20), (10, 20)]),
            marker([(80, 10), (90, 10), (90, 20), (80, 20)]),
            marker([(80, 80), (90, 80), (90, 90), (80, 90)]),
        ],
        np.array([[0], [1], [2]], dtype=np.int32),
    )

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    corners = gomoku_cv.detect_marker_corners(frame)

    assert corners is None
    print("PASS: detect_marker_corners returns None when not all four markers are present")


def test_detect_marker_corners_returns_none_when_aruco_detection_fails():
    reset_state()

    gomoku_cv._detect_aruco_markers = lambda gray: ([], None)

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    corners = gomoku_cv.detect_marker_corners(frame)

    assert corners is None
    print("PASS: detect_marker_corners returns None when marker detection finds nothing")


if __name__ == "__main__":
    test_detect_marker_corners_orders_points_correctly()
    test_detect_marker_corners_returns_none_when_any_marker_is_missing()
    test_detect_marker_corners_returns_none_when_aruco_detection_fails()
    print("\nAll marker detection tests passed.")
