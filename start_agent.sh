#!/usr/bin/env bash
# Polymarket Trading Agent - continuous runner
# Usage: ./start_agent.sh [interval_minutes]
# Directories are auto-created by config/paths.py. Set WORKSPACE_DIR in .env.

set -euo pipefail

INTERVAL=${1:-30}

cd "$(dirname "$0")"

echo "Starting Polymarket Trading Agent"
echo "Interval: ${INTERVAL} minutes"
echo ""

# Use python3 on Unix, fall back to python (Windows/venv)
PYTHON=${PYTHON:-$(command -v python3 2>/dev/null || command -v python)}
exec "$PYTHON" -m agent.scheduler --interval "$INTERVAL"
