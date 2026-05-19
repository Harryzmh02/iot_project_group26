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
        self.last_diff: float | None = None

    def _compact_frame(self, frame: np.ndarray) -> np.ndarray:
        """Small grayscale frame keeps hand-motion checks cheap on Pi 3."""
        if frame.ndim == 3:
            frame = frame.mean(axis=2)
        step_y = max(1, frame.shape[0] // 120)
        step_x = max(1, frame.shape[1] // 160)
        return frame[::step_y, ::step_x].astype(np.float32)

    def update(self, frame: np.ndarray) -> bool:
        """
        Feed a new frame. Returns True when the scene is stable enough
        to trigger board state processing.
        """
        if self._prev_frame is None:
            self._prev_frame = self._compact_frame(frame)
            self._stable_count = 0
            self.last_diff = None
            return False

        compact = self._compact_frame(frame)
        diff = np.mean(np.abs(compact - self._prev_frame))
        self._prev_frame = compact
        self.last_diff = float(diff)

        if diff < self.diff_threshold:
            self._stable_count += 1
        else:
            self._stable_count = 0

        return self._stable_count >= self.required_stable_frames

    def reset(self):
        self._prev_frame = None
        self._stable_count = 0
