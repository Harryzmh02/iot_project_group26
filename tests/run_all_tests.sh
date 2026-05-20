#!/bin/bash

cd "$(dirname "$0")"

PASS=0
FAIL=0

run_test() {
    echo ""
    echo "=== $1 ==="
    if python3 "$1"; then
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
run_test test_dashboard_flow_contract.py
run_test test_script_entrypoints.py

echo ""
echo "=============================="
echo "Results: $PASS passed, $FAIL failed"
echo "=============================="

if [ $FAIL -ne 0 ]; then
    exit 1
fi
