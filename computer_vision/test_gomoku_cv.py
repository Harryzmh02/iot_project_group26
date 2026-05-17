import cv2
import numpy as np

from gomoku_cv import process_frame


def test_process_frame_detects_black_and_white_stones():
    # Create a synthetic board image with one black and one white stone at known grid positions.
    image = np.full((800, 800, 3), (80, 150, 100), dtype=np.uint8)
    black_center = (int(7 * 800 / 14), int(7 * 800 / 14))
    white_center = (int(5 * 800 / 14), int(5 * 800 / 14))
    cv2.circle(image, black_center, 22, (0, 0, 0), -1)
    cv2.circle(image, white_center, 22, (255, 255, 255), -1)

    thresholds = {
        "black_low": np.array([0, 0, 0], dtype=np.uint8),
        "black_high": np.array([180, 255, 75], dtype=np.uint8),
        "white_low": np.array([0, 0, 155], dtype=np.uint8),
        "white_high": np.array([180, 80, 255], dtype=np.uint8),
    }

    board, stones, result_image, black_mask, white_mask = process_frame(
        image, corners=None, thresholds=thresholds
    )

    assert board.shape == (15, 15)
    assert board[7, 7] == 1
    assert board[5, 5] == 2
    assert len(stones) >= 2


if __name__ == "__main__":
    test_process_frame_detects_black_and_white_stones()
    print("Smoke test passed")
