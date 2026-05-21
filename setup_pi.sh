#!/usr/bin/env bash
#
# setup_pi.sh - one-command setup for the Smart Gomoku Board on a Raspberry Pi.
#
# Run once per Pi (re-running is safe):
#     bash setup_pi.sh
#
# Targets a fresh Raspberry Pi OS (Bookworm or later). The heavy native deps
# (numpy, OpenCV, Picamera2) are installed via apt - building them from PyPI
# on a Pi is painfully slow - and the venv is created with
# --system-site-packages so it inherits them.
#
set -euo pipefail

# Run from the repo root regardless of where the script is called from.
cd "$(dirname "$0")"

echo "==> [1/4] Installing native dependencies via apt"
sudo apt update
sudo apt install -y python3-numpy python3-opencv python3-picamera2 git mosquitto

echo "==> [2/4] Creating venv (.venv) with --system-site-packages"
python3 -m venv --system-site-packages .venv

echo "==> [3/4] Installing pure-Python dependencies into the venv"
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "==> [4/4] Verifying OpenCV + ArUco"
if ! python3 -c "import cv2, sys; sys.exit(0 if hasattr(cv2, 'aruco') else 1)"; then
    echo "    apt OpenCV has no aruco module - installing opencv-contrib-python in the venv"
    pip install opencv-contrib-python
fi
python3 -c "import cv2; print('    OpenCV', cv2.__version__, '| aruco:', hasattr(cv2, 'aruco'))"

echo
echo "Done. Activate the environment before running anything:"
echo "    source .venv/bin/activate"
