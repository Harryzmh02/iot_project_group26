#!/bin/bash

cd "$(dirname "$0")"

PASS=0
FAIL=0
PYTHON_BIN="${PYTHON:-}"

find_python() {
    for candidate in "$PYTHON_BIN" python3 python python.exe; do
        if [ -z "$candidate" ]; then
            continue
        fi
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import numpy" >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    echo "python3"
}

PYTHON_BIN="$(find_python)"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"
echo "Using Python: $PYTHON_BIN"

run_test() {
    echo ""
    echo "=== $1 ==="
    if "$PYTHON_BIN" "$1"; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
    fi
}

# No hardware required
run_test test_frame_stability.py
run_test test_image_preprocessing.py
run_test test_pipeline_structure.py
run_test test_pipeline_integration.py
run_test test_cv_mqtt_integration.py

echo ""
echo "=============================="
echo "Results: $PASS passed, $FAIL failed"
echo "=============================="

if [ $FAIL -ne 0 ]; then
    exit 1
fi
