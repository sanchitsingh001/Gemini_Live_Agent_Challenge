# Building orientation (face the road)

## Where to check VLM output (per asset)

The VLM does **not** run per entity; it runs **per GLB asset**. One result per model file (e.g. `home_above_shop`, `EU-home`). All entities that use the same GLB share that asset’s `front_yaw_deg`.

**1. Raw VLM result per asset (from Blender run)**  
- **Path:** `mesh_dir/renders/<asset_name>/front.json`  
- **Fields:** `front_panel` (A/B/C/D), `front_yaw_deg` (0/90/180/270)  
- **Panel mapping:** A=0°, B=90°, C=180°, D=270°

**2. What Godot uses (merged)**  
- **Path:** `godot_world/generated/asset_metadata.json`  
- Same `front_yaw_deg` / `front_panel` per asset, merged from all `front.json` by `consolidate_metadata.py`.

**3. List all VLM results from the project root:**  
```bash
python3 mesh_dir/show_vlm_results.py
```
This prints every asset’s `front_panel` and `front_yaw_deg` from both `mesh_dir/renders/` and `asset_metadata.json`.

**4. Per-entity values in Godot**  
- Select the WorldLoader node → enable **Debug Orientation** → run the game.  
- The console will print for each entity: `layout dir->yaw`, `asset front_yaw`, `rotation_yaw` so you can see why each building faces that direction.

---

## Did `run_orientation_only.sh` have an effect?

**Yes.** The loader uses `godot_world/generated/asset_metadata.json` for every placed entity:

- **entity_facing_yaw** comes from the world layout’s `intent[entity_id].dir` (N, S, E, W, etc.) → converted to degrees (N=0°, E=90°, S=180°, W=270°).
- **asset_front_yaw** comes from `asset_metadata[asset_name].front_yaw_deg` (from Blender + VLM via `run_orientation_only.sh` / `batch_blender.py`).
- **Final rotation:** `rotation_yaw = entity_facing_yaw - asset_front_yaw`, so the building’s “front” (from the GLB) faces the direction the layout says (toward the road).

So orientation is applied. If some buildings still face the wrong way, it’s usually one of the two below.

---

## If a building faces away from the road

### 1. Wrong asset front (VLM picked the wrong side)

Edit `godot_world/generated/asset_metadata.json` for that asset and **flip by 180°**:

- If `front_yaw_deg` is **0** → set to **180**
- If `front_yaw_deg` is **180** → set to **0**
- If **90** → try **270** (and vice versa)

Save, then run the game again. No need to regenerate world or re-run Blender unless you want to re-detect front for that asset.

### 2. Wrong layout direction (intent.dir)

The layout’s `intent[entity_id].dir` might not match where the road actually is. That comes from the world layout (e.g. `world_entity_layout_llm_v3_out.json`). Fix by regenerating the layout or editing the layout JSON so that entity’s `dir` points toward the road.

---

## Debug in Godot

On the WorldLoader node (or whatever node has the world_loader script), enable **Debug Orientation**. The console will print for each placed entity:

- `layout dir->yaw` (from intent.dir)
- `asset front_yaw` (from asset_metadata)
- `rotation_yaw` (final applied rotation)

Use this to see which value is wrong for buildings that face the wrong way.
