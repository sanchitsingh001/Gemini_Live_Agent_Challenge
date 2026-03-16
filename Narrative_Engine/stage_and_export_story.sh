#!/bin/bash
# Stage JSON + GLB assets from a story folder into godot_world/generated, then run export.
# Use this when the story dir has game_bundle.json, 3d_asset_prompts.json, and assets/*.glb.
#
# Usage: ./stage_and_export_story.sh STORY_DIR
# Example: ./stage_and_export_story.sh The_Legend_s_Choice
#
# Prerequisites:
#   - Godot 4.x in PATH with export templates installed (Editor → Manage Export Templates)
#   - STORY_DIR must contain: game_bundle.json, 3d_asset_prompts.json, assets/*.glb (optional: runtime_config.json, sky.png)

set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

STORY_DIR="${1:?Usage: ./stage_and_export_story.sh STORY_DIR}"
if [ ! -d "$STORY_DIR" ]; then
  echo "Error: story directory not found: $STORY_DIR"
  exit 1
fi
STORY_DIR="$(cd "$STORY_DIR" && pwd)"
if [ ! -f "$STORY_DIR/game_bundle.json" ]; then
  echo "Error: game_bundle.json not found in $STORY_DIR"
  exit 1
fi
if [ ! -f "$STORY_DIR/3d_asset_prompts.json" ]; then
  echo "Error: 3d_asset_prompts.json not found in $STORY_DIR"
  exit 1
fi

BASENAME="$(basename "$STORY_DIR")"
mkdir -p "$STORY_DIR/generated"
echo "▶ Generating entity/npc model mappings..."
python3 generate_entity_model_mappings.py \
  --game-bundle "$STORY_DIR/game_bundle.json" \
  --prompts "$STORY_DIR/3d_asset_prompts.json" \
  --out-dir "$STORY_DIR/generated" \
  --assets-dir "$STORY_DIR/assets" \
  --assets-res-path "res://generated/assets"

echo "▶ Staging into godot_world/generated..."
# Only GLBs from the story's assets folder go into the export; clear any prior staged assets.
rm -rf godot_world/generated/assets
mkdir -p godot_world/generated/assets
cp "$STORY_DIR/generated/entity_models.json" "$STORY_DIR/generated/npc_models.json" godot_world/generated/
cp "$STORY_DIR/game_bundle.json" "$STORY_DIR/runtime_config.json" godot_world/generated/
[ -f "$STORY_DIR/sky.png" ] && cp "$STORY_DIR/sky.png" godot_world/generated/
echo '{}' > godot_world/generated/asset_metadata.json
if [ -d "$STORY_DIR/assets" ]; then
  # Only stage .glb files. Do not stage .png/.jpg here: many pipeline outputs use .png extension
  # but are actually JPEG or other format, which causes Godot "Not a PNG file" import errors.
  cp "$STORY_DIR/assets"/*.glb godot_world/generated/assets/ 2>/dev/null || true
fi
echo -n "staged" > godot_world/generated/.asset_stage_marker
echo "  → $(ls godot_world/generated/assets/*.glb 2>/dev/null | wc -l | tr -d ' ') GLBs, game_bundle, runtime_config, sky (if present)"

echo "▶ Running export_godot.sh..."
GAME_EXPORT_BASENAME="$BASENAME" ./export_godot.sh "$STORY_DIR"
echo "Done. Web build: $STORY_DIR/export/web/"
