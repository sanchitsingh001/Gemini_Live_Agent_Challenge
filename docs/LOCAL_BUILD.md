# Local build (JSON + Godot)

No cloud required.

1. **Full pipeline + exports** (from repo root):

   ```bash
   ./run_world_pipeline.sh your_story.txt --export
   ```

   Outputs: `output/<timestamp>/` with `game_bundle.json`, plots, and `export/web/` (web build).

2. **Narrative API** (writes to `output_jobs/<id>/`):

   ```bash
   ./narrative_server/run_server.sh 8000
   # POST /generate { "story": "..." } then GET /jobs/{job_id}
   ```

3. **Custom GLBs** (you already have or place models in `STORY_DIR/assets/*.glb`):

   ```bash
   ./stage_and_export_story.sh STORY_DIR
   ```

   Requires `game_bundle.json`, `3d_asset_prompts.json`, and matching `.glb` names under `assets/`.

4. **Game + chat** (point at any output folder):

   ```bash
   export GAME_OUTPUT=output_jobs/My_Story_Title
   ./run_game.sh
   ```
