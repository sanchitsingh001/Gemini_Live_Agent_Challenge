#!/bin/bash
# Run the narrative_spec-based world generation pipeline.
#
# Usage:
#   ./run_world_pipeline.sh [story.txt] [--skip-3d] [--godot]
#
# If story.txt (or .json) is given: runs generate_narrative_spec.py first, then the rest.
# If not: requires narrative_spec.json to exist (run generate_narrative_spec.py yourself first).
#
# The pipeline always exports a web build (HTML5/WASM) to output/<timestamp>/export/web/.
#
# Flags:
#   --skip-3d   Skip 3D asset prompt generation (LLM call + prompts file)
#   --no-export  Stop after game_bundle + audio (no Godot export). Use with RUN_EXPORT=0 or --no-export for cloud Phase 1 or when export runs separately.
#   --godot     After pipeline, run Godot game with the new bundle (GAME_OUTPUT=this run's output)

set -e

# Unbuffered Python so logs from generate_narrative_spec.py etc. appear in real time
export PYTHONUNBUFFERED=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
[ -f "$ROOT/venv/bin/activate" ] && . "$ROOT/venv/bin/activate"

# Parse optional story file (first arg if it looks like .txt or .json)
STORY_FILE=""
SKIP_3D="${SKIP_3D:-0}"
RUN_GODOT=0
RUN_EXPORT="${RUN_EXPORT:-1}"
ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--skip-3d" ]]; then
    SKIP_3D=1
  elif [[ "$arg" == "--no-export" ]]; then
    RUN_EXPORT=0
  elif [[ "$arg" == "--godot" ]]; then
    RUN_GODOT=1
  elif [[ -z "$STORY_FILE" && ("$arg" == *.txt || "$arg" == *.json) ]]; then
    STORY_FILE="$arg"
  else
    ARGS+=("$arg")
  fi
done

OUTPUT_DIR="${OUTPUT_DIR:-output/$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$OUTPUT_DIR"

echo "▶ Output directory: $OUTPUT_DIR"

# Step 0: narrative_spec — from story file or existing file
NARRATIVE_SPEC_PATH="${NARRATIVE_SPEC_PATH:-}"
if [ -n "$STORY_FILE" ]; then
  if [ ! -f "$STORY_FILE" ]; then
    echo "Error: story file not found: $STORY_FILE"
    exit 1
  fi
  NARRATIVE_SPEC_PATH="$OUTPUT_DIR/narrative_spec.json"
  echo "▶ Generating narrative_spec from story: $STORY_FILE"
  python3 generate_narrative_spec.py --story "$STORY_FILE" --out "$NARRATIVE_SPEC_PATH"
elif [ -n "$NARRATIVE_SPEC_PATH" ]; then
  true
else
  NARRATIVE_SPEC_PATH="narrative_spec.json"
fi
if [ ! -f "$NARRATIVE_SPEC_PATH" ]; then
  echo "Error: $NARRATIVE_SPEC_PATH not found. Pass a story .txt file or run generate_narrative_spec.py first."
  exit 1
fi

# Step 1: narrative_spec → world_plan + world_graph
echo "▶ Converting narrative_spec to world_plan + world_graph"
NARRATIVE_SPEC_PATH="$NARRATIVE_SPEC_PATH" OUTPUT_DIR="$OUTPUT_DIR" python3 narrative_spec_to_world.py

# Step 1.5: Atmosphere from narrative (time_of_day, fog_intensity)
echo "▶ Deriving atmosphere from narrative (time of day, fog intensity)"
NARRATIVE_SPEC_PATH="$NARRATIVE_SPEC_PATH" OUTPUT_DIR="$OUTPUT_DIR" python3 atmosphere_from_narrative.py

# Step 2: World geometry + gates (and spawn point on plot if narrative spec present)
echo "▶ Computing world geometry + gates"
NARRATIVE_SPEC_PATH="$NARRATIVE_SPEC_PATH" \
WORLD_PLAN_PATH="$OUTPUT_DIR/world_plan.json" \
WORLD_GRAPH_PATH="$OUTPUT_DIR/world_graph.json" \
OUTPUT_DIR="$OUTPUT_DIR" \
python3 world_block_diagram.py

# Step 2.5: Spawn point from chapter 1 (road closest to spawn area anchor)
echo "▶ Computing spawn point (chapter 1 → area → road)"
NARRATIVE_SPEC_PATH="$NARRATIVE_SPEC_PATH" \
WORLD_PLAN_PATH="$OUTPUT_DIR/world_plan.json" \
WORLD_GRAPH_LAYOUT="$OUTPUT_DIR/world_graph_layout.json" \
OUTPUT_DIR="$OUTPUT_DIR" \
USE_LLM=1 \
python3 compute_spawn_point.py

# Step 3: Entity layout
echo "▶ Computing world entity layout"
WORLD_PLAN="$OUTPUT_DIR/world_plan.json" \
WORLD_GRAPH_LAYOUT="$OUTPUT_DIR/world_graph_layout.json" \
OUTPUT_DIR="$OUTPUT_DIR" \
OUT_BASE="$OUTPUT_DIR/world_entity_layout" \
USE_LLM=1 \
python3 world_entity_layout_llm_v3.py

# Step 4: 3D asset briefs (LLM) — maps entity_id → description; use with stage_and_export_story.sh + custom GLBs
if [[ "$SKIP_3D" != "1" ]]; then
  echo "▶ Generating 3D asset briefs (LLM)"
  NARRATIVE_SPEC_PATH="$NARRATIVE_SPEC_PATH" \
  WORLD_PLAN_PATH="$OUTPUT_DIR/world_plan.json" \
  WORLD_ENTITY_LAYOUT="$OUTPUT_DIR/world_entity_layout_out.json" \
  OUTPUT_DIR="$OUTPUT_DIR" \
  python3 generate_3d_asset_prompts.py
  echo "  → 3d_asset_prompts.json (for staging GLBs via stage_and_export_story.sh)"
else
  echo "▶ Skipping 3D asset prompt generation (SKIP_3D=1 or --skip-3d)"
fi

# Step 4.5: Generate sky.png from atmosphere (for Godot PanoramaSky)
echo "▶ Generating sky image from atmosphere"
NARRATIVE_SPEC_PATH="$NARRATIVE_SPEC_PATH" OUTPUT_DIR="$OUTPUT_DIR" python3 generate_sky_image.py

# Step 5: Build game bundle
echo "▶ Building game bundle"
NARRATIVE_SPEC_PATH="$NARRATIVE_SPEC_PATH" \
OUTPUT_DIR="$OUTPUT_DIR" \
python3 build_game_bundle.py

# Step 5.5: Generate audio (voiceover + BGM) — on by default; set GENERATE_AUDIO=0 to disable
if [ "${GENERATE_AUDIO:-1}" = "1" ]; then
  echo "▶ Generating audio (voiceover + BGM)"
  OUTPUT_DIR="$OUTPUT_DIR" python3 generate_audio.py
else
  echo "▶ Skipping audio generation (GENERATE_AUDIO=0)"
fi

# Step 6: Export Godot web build (unless RUN_EXPORT=0 or --no-export)
if [[ "${RUN_EXPORT:-1}" = "1" ]]; then
  echo ""
  echo "▶ Exporting Godot game (web)..."
  "$ROOT/export_godot.sh" "$OUTPUT_DIR"
else
  echo "▶ Skipping Godot export (RUN_EXPORT=0 or --no-export)"
fi

echo ""
echo "▶ Done. Outputs in $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"

if [ "$RUN_GODOT" = "1" ]; then
  echo ""
  echo "▶ Starting game (Godot + server)..."
  GAME_OUTPUT="$OUTPUT_DIR" "$ROOT/run_game.sh" --godot
fi
