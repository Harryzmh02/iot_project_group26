import cv2
import numpy as np


STANDARD_SIZE = (800, 800)
BLUR_KERNEL = (5, 5)


def preprocess_frame(frame: np.ndarray) -> np.ndarray:
    """
    Prepare a raw camera frame for the CV pipeline.

    Steps:
      1. Resize to a fixed square resolution so grid calibration
         coordinates stay consistent across captures.
      2. GaussianBlur to suppress sensor noise without smearing
         stone edges (kernel kept small for that reason).

    Returns a BGR numpy array ready to pass to the CV subsystem.
    """
    resized = cv2.resize(frame, STANDARD_SIZE, interpolation=cv2.INTER_AREA)
    blurred = cv2.GaussianBlur(resized, BLUR_KERNEL, sigmaX=0)
    return blurred


def crop_to_board(frame: np.ndarray, corners: list[tuple[int, int]]) -> np.ndarray:
    """
    Apply a perspective transform so the board fills the full frame.

    `corners` must be the four board corners in pixel coordinates
    (top-left, top-right, bottom-right, bottom-left), obtained from
    Ashish's grid calibration step.
    """
    src = np.array(corners, dtype=np.float32)
    w, h = STANDARD_SIZE
    dst = np.array(
        [[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(frame, matrix, STANDARD_SIZE)
