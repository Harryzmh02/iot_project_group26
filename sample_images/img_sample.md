# Sample Board Image Dataset

This folder contains standardised board images captured from the current Raspberry Pi Camera Module setup.

## Purpose

These images are intended to support:

- grid calibration
- stone colour thresholding
- black/white piece detection
- board coordinate mapping
- early robustness testing under different visual conditions

## Image List

| File | Description |
|---|---|
| `01_empty_board.jpg` | Empty 15x15 Gomoku board |
| `02_black_center.jpg` | Single black piece near board centre |
| `03_white_center.jpg` | Single white piece near board centre |
| `04_black_corner.jpg` | Black piece near board edge/corner |
| `05_white_corner.jpg` | White piece near board edge/corner |
| `06_mixed_sparse.jpg` | Small number of mixed black and white pieces |
| `07_mixed_dense.jpg` | Denser mixed board state |
| `08_edge_positions.jpg` | Multiple pieces placed near board boundaries |
| `09_shadow_test.jpg` | Board captured with mild shadowing |
| `10_low_light_test.jpg` | Board captured under weaker ambient lighting |

## Capture Notes

- Captured using Raspberry Pi 3 Model B with Raspberry Pi Camera Module.
- Camera positioned overhead above the board.
- Board orientation kept constant across images where possible.
- These images are intended for early calibration and algorithm development, not final model benchmarking.