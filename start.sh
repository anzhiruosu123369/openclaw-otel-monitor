#!/bin/bash
# OpenClaw OTel Monitor - Start script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/venv"

# Check if venv exists
if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
fi

# Run the server
cd "$SCRIPT_DIR"
"$VENV/bin/python" run.py
