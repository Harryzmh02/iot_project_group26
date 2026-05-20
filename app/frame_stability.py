import numpy as np


class FrameStabilityChecker:
    """
    Confirms a stable board scene before triggering CV processing.

    A frame is considered stable when the mean absolute pixel difference
    between consecutive frames stays below `diff_threshold` for
    `required_stable_frames` frames in a row.
    """

    def __init__(self, required_stable_frames: int = 3, diff_threshold: float = 5.0):
        self.required_stable_frames = required_stable_frames
        self.diff_threshold = diff_threshold
        self._prev_frame: np.ndarray | None = None
        self._stable_count: int = 0

    def update(self, frame: np.ndarray) -> bool:
        """
        Feed a new frame. Returns True when the scene is stable enough
        to trigger board state processing.
        """
        if self._prev_frame is None:
            self._prev_frame = frame.astype(np.float32)
            self._stable_count = 0
            return False

        diff = np.mean(np.abs(frame.astype(np.float32) - self._prev_frame))
        self._prev_frame = frame.astype(np.float32)

        if diff < self.diff_threshold:
            self._stable_count += 1
        else:
            self._stable_count = 0

        return self._stable_count >= self.required_stable_frames

    def reset(self):
        self._prev_frame = None
        self._stable_count = 0
