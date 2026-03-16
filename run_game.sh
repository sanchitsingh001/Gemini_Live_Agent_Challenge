#!/bin/bash
# Run the Narrator Web Game.
# Prerequisites: game_client built (npm run build), game_bundle.json in output/.../
# Set GOOGLE_CLOUD_PROJECT for NPC chat (Vertex Gemini + ADC).
#
# Flags:
#   GODOT=1  or  --godot   Also launch Godot 3D client with game_bundle (requires Godot 4.x)
#
# With --godot: copies game_bundle.json to godot_world/generated/, starts game_server in background,
# then launches Godot with GAME_BUNDLE_MODE=1 and GAME_OUTPUT set.

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
[ -f "$ROOT/venv/bin/activate" ] && . "$ROOT/venv/bin/activate"

RUN_GODOT=0
[[ "$GODOT" == "1" ]] && RUN_GODOT=1
for arg in "$@"; do
  if [[ "$arg" == "--godot" ]]; then
    RUN_GODOT=1
    break
  fi
done

# Ensure game_client is built (optional: skip if web client not present)
if [ -d "game_client" ] && [ -f "game_client/package.json" ]; then
  if [ ! -d "game_client/build" ]; then
    echo "Building game_client..."
    (cd game_client && npm install && npm run build)
  fi
else
  echo "No game_client directory found; skipping web client build (Godot + API only)."
fi

# Use latest *complete* output dir if GAME_OUTPUT not set (needs world_graph_layout + world_entity_layout)
if [ -z "$GAME_OUTPUT" ]; then
  for d in $(ls -1d output/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9] 2>/dev/null | sort -r); do
    if [ -f "$d/world_graph_layout.json" ] && [ -f "$d/world_entity_layout_out.json" ]; then
      GAME_OUTPUT="$d"
      break
    fi
  done
  if [ -z "$GAME_OUTPUT" ]; then
    echo "No complete output directories found (need world_graph_layout.json + world_entity_layout_out.json). Run run_world_pipeline.sh first."
    exit 1
  fi
fi

# Ensure game_bundle exists
if [ ! -f "$GAME_OUTPUT/game_bundle.json" ]; then
  echo "Generating game_bundle.json..."
  OUTPUT_DIR="$GAME_OUTPUT" python3 build_game_bundle.py
fi

# For Godot: copy game_bundle, sky, UI images, and audio to godot_world/generated/
if [ "$RUN_GODOT" = "1" ]; then
  mkdir -p godot_world/generated
  cp "$GAME_OUTPUT/game_bundle.json" godot_world/generated/
  echo "Copied game_bundle.json to godot_world/generated/"
  if [ -f "$GAME_OUTPUT/sky.png" ]; then
    cp "$GAME_OUTPUT/sky.png" godot_world/generated/
    echo "Copied sky.png to godot_world/generated/"
  fi
  for f in "$GAME_OUTPUT"/*.png; do
    [ -f "$f" ] && cp "$f" godot_world/generated/ && echo "Copied $(basename "$f") to godot_world/generated/"
  done
  if [ -d "$GAME_OUTPUT/audio" ]; then
    mkdir -p godot_world/generated/audio
    cp -R "$GAME_OUTPUT/audio"/* godot_world/generated/audio/
    echo "Copied audio/ to godot_world/generated/audio/"
  fi
fi

# Free port 8000 if already in use (lsof exits 1 when nothing on port; avoid set -e exit)
if command -v lsof &>/dev/null; then
  PIDS=$(lsof -ti:8000 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    echo "Killing existing process(es) on port 8000: $PIDS"
    echo "$PIDS" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
fi

if [ "$RUN_GODOT" = "1" ]; then
  echo "Starting game server in background..."
  (cd game_server && GAME_OUTPUT="$GAME_OUTPUT" python3 -m uvicorn main:app --host 127.0.0.1 --port 8000) &
  SERVER_PID=$!
  sleep 2
  echo "Launching Godot 3D client (GAME_OUTPUT=$GAME_OUTPUT)..."
  if command -v godot &>/dev/null; then
    GAME_BUNDLE_MODE=1 GAME_OUTPUT="$GAME_OUTPUT" godot --path godot_world
  elif command -v godot4 &>/dev/null; then
    GAME_BUNDLE_MODE=1 GAME_OUTPUT="$GAME_OUTPUT" godot4 --path godot_world
  else
    echo "Godot not found. Install Godot 4.x and add 'godot' or 'godot4' to PATH."
    echo "Falling back to web game only. Server running at http://127.0.0.1:8000"
    wait $SERVER_PID
  fi
  kill $SERVER_PID 2>/dev/null || true
else
  echo "Starting game server at http://127.0.0.1:8000"
  echo "GAME_OUTPUT=$GAME_OUTPUT"
  cd game_server && GAME_OUTPUT="$GAME_OUTPUT" python3 -m uvicorn main:app --host 127.0.0.1 --port 8000
fi
