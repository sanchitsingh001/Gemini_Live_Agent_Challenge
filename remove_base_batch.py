import bpy
import os
import sys
from mathutils import Vector

# ----------------------------
# Heuristic:
# - Split into loose parts
# - Score each part as "likely base" if:
#   - it's near the lowest Z in the scene
#   - it has low thickness in Z
#   - it has big XY footprint (area)
# We delete the top-scoring part.
# ----------------------------

def clean_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    # purge orphan data (run a few times to be safe)
    for _ in range(3):
        try:
            bpy.ops.outliner.orphans_purge(do_recursive=True)
        except Exception:
            # Older Blender versions may not support this op
            break


def import_glb(path: str):
    bpy.ops.import_scene.gltf(filepath=path)


def export_glb(path: str):
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format='GLB',
        export_apply=True,
    )


def bbox_world(obj: bpy.types.Object):
    # world-space bounding box corners
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))


def split_loose_parts(obj: bpy.types.Object):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    if obj.type != 'MESH':
        return

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.separate(type='LOOSE')
    bpy.ops.object.mode_set(mode='OBJECT')


def score_as_base(obj: bpy.types.Object, global_min_z: float) -> float:
    (xmin, xmax), (ymin, ymax), (zmin, zmax) = bbox_world(obj)
    footprint = (xmax - xmin) * (ymax - ymin)
    thickness = (zmax - zmin)

    # Ignore degenerate or microscopic pieces
    if footprint <= 0.0 or thickness <= 0.0:
        return 0.0

    # How close is the object to the lowest point in the scene?
    near_ground = max(0.0, 1.0 - abs(zmin - global_min_z) / 0.05)  # ~5 cm tolerance

    # Prefer flat pieces (small thickness), clamp to avoid exploding scores
    flatness = min(1.0 / max(thickness, 1e-6), 100.0)

    # Big footprint is suspicious (ground plane / blobby base)
    # We don't normalize heavily here; you can tweak if needed.
    footprint_score = footprint

    # Weighted score
    return (2.5 * near_ground) + (1.5 * flatness) + (1.0 * footprint_score)


def remove_base() -> bool:
    # Collect mesh objects
    mesh_objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not mesh_objs:
        return False

    # Apply transforms for consistent bounding boxes
    bpy.ops.object.select_all(action='DESELECT')
    for o in mesh_objs:
        o.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.ops.object.select_all(action='DESELECT')

    # Compute global scene bounds and min Z
    global_min_z = None
    global_max_z = None
    global_xmin = None
    global_xmax = None
    global_ymin = None
    global_ymax = None
    for o in mesh_objs:
        (xmin, xmax), (ymin, ymax), (zmin, zmax) = bbox_world(o)
        global_min_z = zmin if global_min_z is None else min(global_min_z, zmin)
        global_max_z = zmax if global_max_z is None else max(global_max_z, zmax)
        global_xmin = xmin if global_xmin is None else min(global_xmin, xmin)
        global_xmax = xmax if global_xmax is None else max(global_xmax, xmax)
        global_ymin = ymin if global_ymin is None else min(global_ymin, ymin)
        global_ymax = ymax if global_ymax is None else max(global_ymax, ymax)

    if global_min_z is None or global_max_z is None:
        return False

    scene_x_span = (global_xmax - global_xmin) if (global_xmax is not None and global_xmin is not None) else 0.0
    scene_y_span = (global_ymax - global_ymin) if (global_ymax is not None and global_ymin is not None) else 0.0
    scene_footprint = max(scene_x_span * scene_y_span, 0.0)

    # Split each mesh into loose parts (once per original object)
    originals = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    for o in originals:
        split_loose_parts(o)

    mesh_objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not mesh_objs:
        return False

    # First, try a strict geometric filter: delete ALL very flat,
    # ground-hugging pieces with reasonably large footprint.
    base_parts = []
    scene_height = max(global_max_z - global_min_z, 0.0)

    # Anything whose top is in the bottom 30% of the model and is thin
    # relative to the whole height is a strong base candidate.
    z_cutoff = global_min_z + scene_height * 0.3
    max_thickness = max(0.03, scene_height * 0.15)  # at most ~15% of total height

    # At least 0.5% of scene footprint (but allow if we can't compute)
    rel_footprint_threshold = 0.005

    for o in mesh_objs:
        (xmin, xmax), (ymin, ymax), (zmin, zmax) = bbox_world(o)
        thickness = zmax - zmin
        footprint = (xmax - xmin) * (ymax - ymin)

        if thickness <= 0.0 or footprint <= 0.0:
            continue

        # Footprint must be "sizable" compared to the whole scene
        big_enough = False
        if scene_footprint > 0.0:
            big_enough = (footprint >= scene_footprint * rel_footprint_threshold)
        else:
            big_enough = footprint > 0.0

        # Top of the piece should live in the lower band of the scene.
        low_band = (zmax <= z_cutoff)

        if low_band and thickness <= max_thickness and big_enough:
            base_parts.append(o)

    if base_parts:
        # Delete all detected base parts
        bpy.ops.object.select_all(action='DESELECT')
        for o in base_parts:
            o.select_set(True)
        bpy.ops.object.delete()
        return True

    # Fallback: use the scoring heuristic to remove a single best candidate
    scored = []
    for o in mesh_objs:
        s = score_as_base(o, global_min_z)
        scored.append((s, o))

    if not scored:
        return False

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, base_candidate = scored[0]

    if best_score <= 0.0:
        return False

    (_, _), (_, _), (zmin, zmax) = bbox_world(base_candidate)
    if (zmax - zmin) > 1.5:  # safety guard
        return False

    bpy.ops.object.select_all(action='DESELECT')
    base_candidate.select_set(True)
    bpy.ops.object.delete()
    return True


def process_file(in_path: str, out_path: str) -> bool:
    clean_scene()
    import_glb(in_path)
    removed = remove_base()
    export_glb(out_path)
    return removed


def main():
    # Usage:
    # blender -b -P remove_base_batch.py -- <input_folder> <output_folder>
    argv = sys.argv
    if "--" not in argv:
        print("Missing args. Use: blender -b -P remove_base_batch.py -- <in_dir> <out_dir>")
        return

    args = argv[argv.index("--") + 1:]
    if len(args) < 2:
        print("Missing args. Use: blender -b -P remove_base_batch.py -- <in_dir> <out_dir>")
        return

    in_dir = args[0]
    out_dir = args[1]
    os.makedirs(out_dir, exist_ok=True)

    exts = (".glb", ".gltf")
    files = [f for f in os.listdir(in_dir) if f.lower().endswith(exts)]
    files.sort()

    total = len(files)
    if total == 0:
        print(f"No .glb/.gltf files found in {in_dir}")
        return

    removed_count = 0

    for i, fn in enumerate(files, 1):
        in_path = os.path.join(in_dir, fn)
        out_name = fn
        if out_name.lower().endswith(".gltf"):
            out_name = out_name[:-5] + ".glb"
        out_path = os.path.join(out_dir, out_name)

        try:
            removed = process_file(in_path, out_path)
            removed_count += int(bool(removed))
            print(f"[{i}/{total}] {fn} -> cleaned ({'base removed' if removed else 'no base removed'})")
        except Exception as e:
            print(f"[{i}/{total}] {fn} -> ERROR: {e}")

    print(f"Done. Base removed in {removed_count}/{total} files.")


if __name__ == "__main__":
    main()
