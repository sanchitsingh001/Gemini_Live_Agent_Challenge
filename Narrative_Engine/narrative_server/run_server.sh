#!/bin/bash
# Run the Narrative Engine server.
# Usage: ./run_server.sh [port]
# Prerequisites: Install deps (pip install -r requirements.txt, project root requirements)
# Set GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION; gcloud auth application-default login

set -e

PORT="${1:-8000}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env if present
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/.env"
  set +a
fi

export PROJECT_ROOT
cd "$PROJECT_ROOT"

# Use venv Python so uvicorn is available
PYTHON="${PROJECT_ROOT}/venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
  PYTHON=python3
fi

echo "▶ Narrative Engine server on port $PORT (PROJECT_ROOT=$PROJECT_ROOT)"
exec "$PYTHON" -m uvicorn narrative_server.main:app --host 0.0.0.0 --port "$PORT"
