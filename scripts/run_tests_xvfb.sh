#!/usr/bin/env bash
# Helper script to run tests under Xvfb for CI or headless environments.
set -euo pipefail
XVFB_DISPLAY=${XVFB_DISPLAY:-":99"}
SCREEN=${SCREEN:-"0 1024x768x24"}

# Start Xvfb in background
Xvfb ${XVFB_DISPLAY} -screen ${SCREEN} &
XVFB_PID=$!
export DISPLAY=${XVFB_DISPLAY}

# Wait briefly for Xvfb to start
sleep 0.5

# Run pytest
pytest -q "$@"

# Kill Xvfb
kill ${XVFB_PID}
