import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'raspberrypi_capture'))

import numpy as np
from frame_stability import FrameStabilityChecker


def test_first_frame_never_triggers():
    checker = FrameStabilityChecker(required_stable_frames=3, diff_threshold=5.0)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    assert checker.update(frame) == False
    print("PASS: first frame never triggers")


def test_triggers_after_required_stable_frames():
    checker = FrameStabilityChecker(required_stable_frames=3, diff_threshold=5.0)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    checker.update(frame)
    assert checker.update(frame) == False
    assert checker.update(frame) == False
    assert checker.update(frame) == True
    print("PASS: triggers after 3 stable frames")


def test_movement_resets_count():
    checker = FrameStabilityChecker(required_stable_frames=3, diff_threshold=5.0)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    noisy = np.random.randint(50, 255, (480, 640, 3), dtype=np.uint8)

    checker.update(frame)
    checker.update(frame)
    assert checker.update(noisy) == False
    print("PASS: movement resets stable count")


def test_triggers_after_settling_post_movement():
    checker = FrameStabilityChecker(required_stable_frames=3, diff_threshold=5.0)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    noisy = np.random.randint(50, 255, (480, 640, 3), dtype=np.uint8)

    checker.update(noisy)
    checker.update(frame)
    checker.update(frame)
    checker.update(frame)
    assert checker.update(frame) == True
    print("PASS: triggers correctly after movement settles")


def test_reset_clears_state():
    checker = FrameStabilityChecker(required_stable_frames=3, diff_threshold=5.0)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    checker.update(frame)
    checker.update(frame)
    checker.update(frame)
    checker.update(frame)  # triggered

    checker.reset()
    assert checker.update(frame) == False
    print("PASS: reset clears state correctly")


def test_custom_threshold():
    checker = FrameStabilityChecker(required_stable_frames=2, diff_threshold=50.0)
    frame_a = np.full((480, 640, 3), 100, dtype=np.uint8)
    frame_b = np.full((480, 640, 3), 130, dtype=np.uint8)  # diff=30, under threshold

    checker.update(frame_a)
    checker.update(frame_b)
    assert checker.update(frame_b) == True
    print("PASS: custom threshold respected")


if __name__ == "__main__":
    test_first_frame_never_triggers()
    test_triggers_after_required_stable_frames()
    test_movement_resets_count()
    test_triggers_after_settling_post_movement()
    test_reset_clears_state()
    test_custom_threshold()
    print("\nAll frame_stability tests passed.")
