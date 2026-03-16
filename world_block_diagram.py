#!/usr/bin/env python3
"""
world_graph_plot.py

High-level world graph visualization for papers:
- Draws each area as a labeled rectangle (size ~ scale_hint)
- Connects areas using world_graph.json connections (no edges needed)
- Uses an academic-style color scheme (white background, muted tones)
- Removes redundant connections: if A and B are already connected
  via other areas, the direct A-B edge is omitted in the plot.
- Also outputs world_graph_layout.json with exact coordinates and gates.
"""

import json
import math
import os

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


# ----------------------------
# CONFIG
# ----------------------------

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
WORLD_PLAN_PATH = os.environ.get("WORLD_PLAN_PATH", "world_plan.json")
WORLD_GRAPH_PATH = os.environ.get("WORLD_GRAPH_PATH", "world_graph.json")
NARRATIVE_SPEC_PATH = os.environ.get("NARRATIVE_SPEC_PATH", "")
USE_LLM_SPAWN = os.environ.get("USE_LLM", "1").strip().lower() in ("1", "true", "yes")

# Distance buckets in abstract "world units" (tighter = less scattered layout)
DIST_UNITS = {
    "near": 0.85,
    "medium": 1.5,
    "far": 2.2,
}

# Box size per scale_hint in "world units"
SCALE_SIZE = {
    "tiny":   0.9,
    "small":  1.2,
    "medium": 1.6,
    "large":  2.1,
    "huge":   2.7,
}

# Connection style per kind
EDGE_STYLES = {
    "road": {
        "color": "#1b9e77",
        "linewidth": 2.0,
        "linestyle": "-",
        "label": "road",
    },
    "trunk_road": {
        "color": "#d95f02",
        "linewidth": 2.6,
        "linestyle": "-",
        "label": "trunk road",
    },
    "footpath": {
        "color": "#7570b3",
        "linewidth": 1.6,
        "linestyle": "--",
        "label": "footpath",
    },
}

# Default style for unknown kinds
DEFAULT_EDGE_STYLE = {
    "color": "#4d4d4d",
    "linewidth": 1.5,
    "linestyle": "-",
    "label": "other",
}

# Overlap separation settings (in same units as DIST_UNITS)
ENABLE_OVERLAP_SEPARATION = True
MIN_GAP_UNITS = 0.35
OVERLAP_ITERS = 120

DIR_ANGLES = {
    "N": math.pi / 2,
    "NE": math.pi / 4,
    "E": 0.0,
    "SE": -math.pi / 4,
    "S": -math.pi / 2,
    "SW": -3 * math.pi / 4,
    "W": math.pi,
    "NW": 3 * math.pi / 4,
}


# ----------------------------
# IO helpers
# ----------------------------

def load_json(path: str):
    with open(path, "r") as f:
        return json.load(f)


def build_area_info(world_plan):
    """
    Returns:
      area_info: dict[id] -> {"scale_hint": str, "size": float}
    """
    info = {}
    for a in world_plan.get("areas", []):
        aid = a["id"]
        scale = a.get("scale_hint", "medium")
        size = SCALE_SIZE.get(scale, SCALE_SIZE["medium"])
        info[aid] = {"scale_hint": scale, "size": float(size)}
    return info


# ----------------------------
# Layout: positions from placements + spring relaxation
# ----------------------------

def initial_positions(world_graph):
    """
    Compute initial continuous positions from placements.
    Uses center_area_id + placements + distance buckets.
    """
    positions = {}
    center_id = world_graph.get("center_area_id")
    if center_id:
        positions[center_id] = (0.0, 0.0)

    placements = world_graph.get("placements", [])

    # resolve placements even if 'relative_to' appears later by doing multiple passes
    for _ in range(10):  # small graphs converge quickly
        changed_any = False
        for p in placements:
            aid = p["area_id"]
            if aid in positions:
                continue

            ref_id = p.get("relative_to")
            if ref_id == "center":
                ref_id = center_id

            if ref_id not in positions:
                continue

            ref_x, ref_y = positions[ref_id]
            direction = p.get("dir", "E")
            dist_bucket = p.get("dist_bucket", "medium")
            angle = DIR_ANGLES.get(direction, 0.0)
            dist = DIST_UNITS.get(dist_bucket, DIST_UNITS["medium"])

            x = ref_x + dist * math.cos(angle)
            y = ref_y + dist * math.sin(angle)
            positions[aid] = (x, y)
            changed_any = True

        if not changed_any:
            break

    # Make sure all areas mentioned in connections exist
    for c in world_graph.get("connections", []):
        positions.setdefault(c["from_area_id"], (0.0, 0.0))
        positions.setdefault(c["to_area_id"], (0.0, 0.0))

    return positions


def relax_positions(world_graph, positions, iters=80, lr=0.15):
    """
    Light spring relaxation so that connection distances roughly match DIST_UNITS.
    Keeps overall structure but cleans up crowding along edges.
    """
    if not world_graph.get("connections"):
        return positions

    pos = dict(positions)  # copy
    center_id = world_graph.get("center_area_id")
    fixed = {center_id} if center_id in pos else set()
    eps = 1e-6

    for _ in range(iters):
        for c in world_graph["connections"]:
            a = c["from_area_id"]
            b = c["to_area_id"]
            target = DIST_UNITS.get(c.get("distance", "medium"), DIST_UNITS["medium"])

            ax, ay = pos[a]
            bx, by = pos[b]
            dx, dy = (bx - ax), (by - ay)
            d = math.hypot(dx, dy)
            if d < eps:
                dx, dy, d = 1.0, 0.0, 1.0

            err = d - target
            ux, uy = dx / d, dy / d
            # move each endpoint half the correction
            cx = ux * err * 0.5 * lr
            cy = uy * err * 0.5 * lr

            if a not in fixed:
                pos[a] = (ax + cx, ay + cy)
            if b not in fixed:
                pos[b] = (bx - cx, by - cy)

    return pos


# ----------------------------
# Overlap separation on rectangles
# ----------------------------

def rects_from_positions(positions, area_info):
    """
    positions: dict[area_id] -> (cx, cy)
    area_info: dict[area_id] -> {"size": s}
    Returns dict[area_id] -> (x0, y0, x1, y1)
    """
    rects = {}
    for aid, (cx, cy) in positions.items():
        size = area_info.get(aid, {}).get("size", SCALE_SIZE["medium"])
        w = size
        h = size
        x0 = cx - w / 2.0
        y0 = cy - h / 2.0
        x1 = cx + w / 2.0
        y1 = cy + h / 2.0
        rects[aid] = (x0, y0, x1, y1)
    return rects


def rect_overlap_with_gap(r1, r2, gap):
    """
    r1, r2: (x0, y0, x1, y1)
    gap: minimum clearance requested (both rects expanded by gap/2)
    Returns (ox, oy) >= 0 overlap in x & y or (0,0) if none.
    """
    x0, y0, x1, y1 = r1
    a0, b0, a1, b1 = r2

    half = gap / 2.0
    x0 -= half; y0 -= half; x1 += half; y1 += half
    a0 -= half; b0 -= half; a1 += half; b1 += half

    ix0 = max(x0, a0)
    iy0 = max(y0, b0)
    ix1 = min(x1, a1)
    iy1 = min(y1, b1)

    if ix1 > ix0 and iy1 > iy0:
        return (ix1 - ix0, iy1 - iy0)
    return (0.0, 0.0)


def separate_overlaps(positions, area_info,
                      min_gap=MIN_GAP_UNITS,
                      iters=OVERLAP_ITERS):
    """
    Iteratively push area centers apart so that their rectangles don't overlap,
    with at least 'min_gap' units of clearance.
    """
    pos = dict(positions)
    ids = list(pos.keys())
    if len(ids) <= 1:
        return pos

    for _ in range(iters):
        rects = rects_from_positions(pos, area_info)
        moved_any = False

        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a = ids[i]
                b = ids[j]
                ra = rects[a]
                rb = rects[b]

                ox, oy = rect_overlap_with_gap(ra, rb, min_gap)
                if ox <= 0.0 and oy <= 0.0:
                    continue

                ax, ay = pos[a]
                bx, by = pos[b]
                dx = bx - ax
                dy = by - ay

                if abs(dx) < 1e-6 and abs(dy) < 1e-6:
                    dx, dy = 1.0, 0.0

                if ox <= oy:
                    step = ox / 2.0 + 0.05
                    sign = 1.0 if dx >= 0 else -1.0
                    pos[a] = (ax - sign * step, ay)
                    pos[b] = (bx + sign * step, by)
                else:
                    step = oy / 2.0 + 0.05
                    sign = 1.0 if dy >= 0 else -1.0
                    pos[a] = (ax, ay - sign * step)
                    pos[b] = (bx, by + sign * step)

                moved_any = True

        if not moved_any:
            break

    return pos


# ----------------------------
# Connection reduction for plotting
# ----------------------------

def compute_minimal_edges(world_graph):
    """
    From world_graph['connections'], build a minimal undirected edge set
    for plotting:
      - At most one edge per unordered pair (A, B)
      - Prefer stronger kinds: trunk_road > road > footpath > other
      - Remove transitive edges: only keep an edge if A and B are not
        already connected via previously kept edges.
    Returns a list of (a, b, connection_dict).
    """
    # 1) For each unordered pair, keep the "best" connection by kind
    priority = {"trunk_road": 3, "road": 2, "footpath": 1}
    pair_best = {}

    for c in world_graph.get("connections", []):
        a = c["from_area_id"]
        b = c["to_area_id"]
        if a == b:
            continue
        key = tuple(sorted((a, b)))
        kind = c.get("kind", "")
        pr = priority.get(kind, 0)
        old = pair_best.get(key)
        if old is None or pr > old[0]:
            pair_best[key] = (pr, c)

    edges = [(a, b, c) for (a, b), (_, c) in pair_best.items()]

    # 2) Build a spanning forest: skip edges that are already connected
    adj = {}

    def has_path(u, v):
        if u == v:
            return True
        visited = set()
        stack = [u]
        while stack:
            cur = stack.pop()
            if cur == v:
                return True
            if cur in visited:
                continue
            visited.add(cur)
            for nb in adj.get(cur, ()):
                if nb not in visited:
                    stack.append(nb)
        return False

    kept = []
    for a, b, c in edges:
        if not has_path(a, b):
            kept.append((a, b, c))
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)

    return kept


# ----------------------------
# Gate computation
# ----------------------------

def gate_on_rect(center, other_center, rect):
    """
    Given a rectangle and a line from center -> other_center,
    compute the intersection point with the rectangle boundary.
    center, other_center: (cx, cy), (tx, ty)
    rect: (x0, y0, x1, y1)
    Returns (gx, gy) on the rectangle edge.
    """
    cx, cy = center
    tx, ty = other_center
    x0, y0, x1, y1 = rect

    dx = tx - cx
    dy = ty - cy

    # If centers coincide, just return center as fallback
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return cx, cy

    candidates = []

    # Intersect with vertical edges
    if dx > 0:
        t = (x1 - cx) / dx
        if t > 0:
            y = cy + dy * t
            if y0 <= y <= y1:
                candidates.append((t, x1, y))
    elif dx < 0:
        t = (x0 - cx) / dx
        if t > 0:
            y = cy + dy * t
            if y0 <= y <= y1:
                candidates.append((t, x0, y))

    # Intersect with horizontal edges
    if dy > 0:
        t = (y1 - cy) / dy
        if t > 0:
            x = cx + dx * t
            if x0 <= x <= x1:
                candidates.append((t, x, y1))
    elif dy < 0:
        t = (y0 - cy) / dy
        if t > 0:
            x = cx + dx * t
            if x0 <= x <= x1:
                candidates.append((t, x, y0))

    if not candidates:
        return cx, cy  # should not really happen

    # Choose the closest intersection (smallest t)
    candidates.sort(key=lambda item: item[0])
    _, gx, gy = candidates[0]
    return gx, gy


# ----------------------------
# Plotting
# ----------------------------

def prettify_name(area_id: str) -> str:
    return area_id.replace("_", " ").title()


def plot_world_graph(world_plan, world_graph,
                     out_png="world_graph_plot.png",
                     out_pdf="world_graph_plot.pdf",
                     narrative_spec=None):
    area_info = build_area_info(world_plan)

    # 1) initial placement from world_graph placements
    positions0 = initial_positions(world_graph)

    # 2) spring relaxation to honor distance buckets
    positions1 = relax_positions(world_graph, positions0)

    # 3) separation to remove overlaps & increase clarity
    if ENABLE_OVERLAP_SEPARATION:
        positions = separate_overlaps(positions1, area_info)
    else:
        positions = positions1

    # Precompute rectangles from final positions
    rects = rects_from_positions(positions, area_info)

    # ---- Compute reduced edge set for plotting / layout ----
    minimal_edges = compute_minimal_edges(world_graph)
    # --------------------------------------------------------

    # ------------ Build layout JSON structure ---------------
    layout = {
        "areas": {},
        "connections": [],
        "config": {
            "DIST_UNITS": DIST_UNITS,
            "SCALE_SIZE": SCALE_SIZE,
            "min_gap_units": MIN_GAP_UNITS,
        },
    }

    # Areas
    for aid, info in area_info.items():
        if aid not in positions:
            continue
        cx, cy = positions[aid]
        x0, y0, x1, y1 = rects[aid]
        layout["areas"][aid] = {
            "id": aid,
            "name": prettify_name(aid),
            "scale_hint": info["scale_hint"],
            "size": info["size"],
            "center": {"x": cx, "y": cy},
            "rect": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
            "gates": [],  # to be filled below
        }
    # --------------------------------------------------------

    # Prepare figure
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 11,
    })

    fig, ax = plt.subplots(figsize=(6.5, 5.0), dpi=150)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # Bounds from rectangles
    all_x0 = [r[0] for r in rects.values()]
    all_y0 = [r[1] for r in rects.values()]
    all_x1 = [r[2] for r in rects.values()]
    all_y1 = [r[3] for r in rects.values()]

    margin = 0.8
    xmin = min(all_x0) - margin
    xmax = max(all_x1) + margin
    ymin = min(all_y0) - margin
    ymax = max(all_y1) + margin

    # Draw connections (under boxes) + fill gate info
    used_edge_labels = set()
    for a, b, c in minimal_edges:
        if a not in positions or b not in positions:
            continue

        ca = positions[a]
        cb = positions[b]
        ra = rects[a]
        rb = rects[b]

        # gate positions on each rect
        ga = gate_on_rect(ca, cb, ra)
        gb = gate_on_rect(cb, ca, rb)

        kind = c.get("kind", "")
        style = EDGE_STYLES.get(kind, DEFAULT_EDGE_STYLE)
        label = style["label"]

        legend_label = label if label not in used_edge_labels else None
        if legend_label:
            used_edge_labels.add(label)

        # Plot the connection line from gate to gate
        ax.plot(
            [ga[0], gb[0]],
            [ga[1], gb[1]],
            color=style["color"],
            linewidth=style["linewidth"],
            linestyle=style["linestyle"],
            alpha=0.95,
            zorder=1,
            label=legend_label,
        )

        # Update layout JSON
        conn_entry = {
            "from": a,
            "to": b,
            "kind": kind,
            "distance": c.get("distance", ""),
            "from_gate": {"x": ga[0], "y": ga[1]},
            "to_gate": {"x": gb[0], "y": gb[1]},
            "polyline": [
                {"x": ga[0], "y": ga[1]},
                {"x": gb[0], "y": gb[1]},
            ],
        }
        layout["connections"].append(conn_entry)

        # Per-area gate lists
        layout["areas"][a]["gates"].append({
            "connected_to": b,
            "kind": kind,
            "distance": c.get("distance", ""),
            "x": ga[0],
            "y": ga[1],
        })
        layout["areas"][b]["gates"].append({
            "connected_to": a,
            "kind": kind,
            "distance": c.get("distance", ""),
            "x": gb[0],
            "y": gb[1],
        })

    # Optional: compute spawn point from chapter 1 and add to layout (for plot + JSON)
    if narrative_spec is not None:
        try:
            from compute_spawn_point import compute_spawn_point
            spawn = compute_spawn_point(
                narrative_spec, world_plan, layout,
                use_llm=USE_LLM_SPAWN,
            )
            if spawn:
                layout["spawn_point"] = spawn
        except Exception as e:
            print(f"[warn] Spawn point computation skipped: {e}")

    # Draw area boxes + labels
    for aid, info in area_info.items():
        if aid not in positions:
            continue
        cx, cy = positions[aid]
        size = info["size"]
        w = size
        h = size

        x0 = cx - w / 2.0
        y0 = cy - h / 2.0

        rect_patch = Rectangle(
            (x0, y0),
            w,
            h,
            facecolor="#e0e0e0",   # light grey
            edgecolor="#333333",   # dark outline
            linewidth=1.3,
            zorder=2,
        )
        ax.add_patch(rect_patch)

        ax.text(
            cx,
            cy,
            prettify_name(aid),
            ha="center",
            va="center",
            fontsize=10,
            color="#000000",
            zorder=3,
        )

    # Draw spawn point if present (chapter-1 start, on road closest to area anchor)
    if layout.get("spawn_point"):
        sp = layout["spawn_point"]
        sx, sy = sp.get("x", 0), sp.get("y", 0)
        ax.scatter(
            [sx], [sy],
            s=280,
            marker="*",
            color="#e7298a",
            edgecolors="#333333",
            linewidths=1.2,
            zorder=5,
            label="Spawn",
        )
        ax.annotate(
            "Spawn",
            (sx, sy),
            xytext=(0, 12),
            textcoords="offset points",
            ha="center",
            fontsize=9,
            color="#c51b8a",
            zorder=5,
        )

    # Axes styling
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymax, ymin)  # flip Y for map-like orientation
    ax.set_aspect("equal", adjustable="datalim")

    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Legend
    if used_edge_labels:
        ax.legend(
            loc="upper right",
            frameon=True,
            framealpha=0.9,
            edgecolor="#444444",
            fontsize=9,
        )

    ax.set_title("World Graph Overview", fontsize=12, pad=12)

    fig.tight_layout()
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    fig.savefig(out_pdf, dpi=300, bbox_inches="tight")
    plt.close(fig)

    print(f"Saved: {out_png}")
    print(f"Saved: {out_pdf}")

    return layout


def main():
    if not os.path.exists(WORLD_PLAN_PATH):
        print(f"Error: {WORLD_PLAN_PATH} not found. Run narrative_spec_to_world.py first.")
        raise SystemExit(1)
    if not os.path.exists(WORLD_GRAPH_PATH):
        print(f"Error: {WORLD_GRAPH_PATH} not found. Run narrative_spec_to_world.py first.")
        raise SystemExit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    world_plan = load_json(WORLD_PLAN_PATH)
    world_graph = load_json(WORLD_GRAPH_PATH)

    narrative_spec = None
    if NARRATIVE_SPEC_PATH and os.path.exists(NARRATIVE_SPEC_PATH):
        narrative_spec = load_json(NARRATIVE_SPEC_PATH)

    out_png = os.path.join(OUTPUT_DIR, "world_graph_plot.png")
    out_pdf = os.path.join(OUTPUT_DIR, "world_graph_plot.pdf")
    layout = plot_world_graph(
        world_plan, world_graph,
        out_png=out_png, out_pdf=out_pdf,
        narrative_spec=narrative_spec,
    )

    out_json = os.path.join(OUTPUT_DIR, "world_graph_layout.json")
    with open(out_json, "w") as f:
        json.dump(layout, f, indent=2)
    print(f"Saved: {out_json}")


if __name__ == "__main__":
    main()