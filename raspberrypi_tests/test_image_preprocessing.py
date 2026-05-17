import sys
import os
import types
import numpy as np

# Stub cv2 if not installed (e.g. running on macOS without OpenCV).
# On the Pi where cv2 is installed the real library is used instead.
if "cv2" not in sys.modules:
    try:
        import cv2
    except ImportError:
        cv2_mod = types.ModuleType("cv2")
        cv2_mod.INTER_AREA = 3

        def _resize(src, dsize, **kw):
            h, w = dsize[1], dsize[0]
            return np.zeros((h, w, src.shape[2]) if src.ndim == 3 else (h, w), dtype=src.dtype)

        def _gaussian_blur(src, ksize, **kw):
            return src.copy()

        def _get_perspective_transform(src, dst):
            return np.eye(3, dtype=np.float32)

        def _warp_perspective(src, M, dsize):
            h, w = dsize[1], dsize[0]
            return np.zeros((h, w, src.shape[2]) if src.ndim == 3 else (h, w), dtype=src.dtype)

        cv2_mod.resize = _resize
        cv2_mod.GaussianBlur = _gaussian_blur
        cv2_mod.getPerspectiveTransform = _get_perspective_transform
        cv2_mod.warpPerspective = _warp_perspective
        sys.modules["cv2"] = cv2_mod

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'raspberrypi_capture'))

from image_preprocessing import preprocess_frame, crop_to_board


def test_output_shape_standard():
    raw = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
    result = preprocess_frame(raw)
    assert result.shape == (800, 800, 3), f"Expected (800, 800, 3), got {result.shape}"
    print("PASS: output resized to 800x800 from 1080p")


def test_output_shape_small_input():
    raw = np.random.randint(0, 255, (240, 320, 3), dtype=np.uint8)
    result = preprocess_frame(raw)
    assert result.shape == (800, 800, 3), f"Expected (800, 800, 3), got {result.shape}"
    print("PASS: output resized to 800x800 from small input")


def test_output_dtype():
    raw = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    result = preprocess_frame(raw)
    assert result.dtype == np.uint8, f"Expected uint8, got {result.dtype}"
    print("PASS: output dtype is uint8")


def test_output_is_not_same_object():
    raw = np.zeros((480, 640, 3), dtype=np.uint8)
    result = preprocess_frame(raw)
    assert result is not raw
    print("PASS: preprocess returns a new array, not the original")


def test_crop_to_board_shape():
    raw = np.random.randint(0, 255, (800, 800, 3), dtype=np.uint8)
    corners = [(50, 50), (750, 50), (750, 750), (50, 750)]
    result = crop_to_board(raw, corners)
    assert result.shape == (800, 800, 3), f"Expected (800, 800, 3), got {result.shape}"
    print("PASS: crop_to_board output is 800x800")


def test_crop_to_board_dtype():
    raw = np.random.randint(0, 255, (800, 800, 3), dtype=np.uint8)
    corners = [(50, 50), (750, 50), (750, 750), (50, 750)]
    result = crop_to_board(raw, corners)
    assert result.dtype == np.uint8
    print("PASS: crop_to_board output dtype is uint8")


if __name__ == "__main__":
    test_output_shape_standard()
    test_output_shape_small_input()
    test_output_dtype()
    test_output_is_not_same_object()
    test_crop_to_board_shape()
    test_crop_to_board_dtype()
    print("\nAll image_preprocessing tests passed.")
