#!/usr/bin/env python3
"""world_entity_layout_llm_v3.py

Pipeline
1) Read world_plan.json (areas + entity groups)
2) Read world_graph_layout.json (area rectangles + gate positions)
3) For each area:
   - Expand entities (group/count) into per-instance IDs
   - Ask an LLM for semantic intent (optional):
       {id: {relative_to: "anchor"|other_id, dir: N/NE/E/SE/S/SW/W/NW, dist_bucket: tiny/small/medium/large}}
     IMPORTANT: "anchor" is an ABSTRACT center point, not an entity.
   - Deterministically place rectangles near their intended targets, avoid overlaps.
   - If can't fit, grow the area and retry (gates stay on the edges, preserving edge fraction).
4) Draw a world map (all areas) with entities + gates, export PNG/PDF.
5) Export layout JSON.

Run
  python world_entity_layout_llm_v3.py

LLM mode
  USE_LLM=1 GOOGLE_CLOUD_PROJECT=... python world_entity_layout_llm_v3.py
"""
from __future__ import annotations

import json
import math
import os
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

# Optional plotting dependency. We still want JSON output even if matplotlib
# isn't installed (e.g., minimal environments / CI).
HAS_MPL = True
try:
    import matplotlib  # type: ignore
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # type: ignore
    from matplotlib.patches import Rectangle  # type: ignore
except Exception:
    HAS_MPL = False

# -----------------------------
# Config
# -----------------------------

PLAN_PATH = os.environ.get("WORLD_PLAN", "world_plan.json")
WGL_PATH = os.environ.get("WORLD_GRAPH_LAYOUT", "world_graph_layout.json")

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", ".")
OUT_BASE = os.environ.get("OUT_BASE", "world_entity_layout_llm_v3")
# If OUTPUT_DIR is set, prefix outputs (unless OUT_BASE already contains a path)
if OUTPUT_DIR != "." and not os.path.dirname(OUT_BASE):
    _out_base = os.path.join(OUTPUT_DIR, OUT_BASE)
else:
    _out_base = OUT_BASE
OUT_PNG = _out_base + "_out.png"
OUT_PDF = _out_base + "_out.pdf"
OUT_JSON = _out_base + "_out.json"

USE_LLM = os.environ.get("USE_LLM", "0") in {"1", "true", "True", "YES", "yes"}
import gemini_client as _gc
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", _gc.DEFAULT_MODEL)

# deterministic (for repeatability when not using LLM)
RNG_SEED = int(os.environ.get("SEED", "7"))
random.seed(RNG_SEED)

# If you want extra breathing room, increase this.
GLOBAL_ENTITY_PADDING_TILES = float(os.environ.get("ENTITY_PADDING", "1.5"))

# When area grows, how aggressively?
GROWTH_FACTOR = float(os.environ.get("GROWTH_FACTOR", "1.25"))
MAX_GROW_ITERS = int(os.environ.get("MAX_GROW_ITERS", "12"))

# Drawing knobs
WORLD_DPI = int(os.environ.get("WORLD_DPI", "250"))
CROP_PADDING = float(os.environ.get("CROP_PADDING", "12"))

WORLD_ROAD_ALPHA = float(os.environ.get("WORLD_ROAD_ALPHA", "0.22"))
WORLD_ROAD_ZORDER = int(os.environ.get("WORLD_ROAD_ZORDER", "1"))
WORLD_CONN_LW = float(os.environ.get("WORLD_CONN_LW", "4.0"))          # inter-area connection thickness
WORLD_CONN_ALPHA = float(os.environ.get("WORLD_CONN_ALPHA", "0.75"))
WORLD_CONN_ZORDER = int(os.environ.get("WORLD_CONN_ZORDER", "5"))
# If you ever get a huge outlier area that makes everything tiny, set:
#   WORLD_CROP_MODE=robust
WORLD_CROP_MODE = os.environ.get("WORLD_CROP_MODE", "normal").strip().lower()  # normal|robust
ROBUST_Q = float(os.environ.get("ROBUST_Q", "0.02"))  # used only when robust

# Entity label knobs (THIS fixes your readability request)
ENTITY_LABEL_FONTSIZE = float(os.environ.get("ENTITY_LABEL_FONTSIZE", "6"))
ENTITY_LABEL_DY_WORLD = float(os.environ.get("ENTITY_LABEL_DY_WORLD", "1.2"))  # offset above entity box (world units)
ENTITY_LABEL_BOX = os.environ.get("ENTITY_LABEL_BOX", "1") in {"1", "true", "True", "YES", "yes"}

# Distance bucket mapping: these are *radii* in tiles, scaled by area size.
DIST_BUCKETS = ["tiny", "small", "medium", "large"]
DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

# Size buckets: small/medium/large/huge only (no tiny — avoid 2x2 tiles that break placement)
SIZE_BUCKETS = ["small", "medium", "large", "huge"]

# Map size_bucket -> (w_tiles, h_tiles). LLM chooses bucket; we use these exact numbers for placement.
SIZE_BUCKET_FOOTPRINT: Dict[str, Tuple[float, float]] = {
    "small": (3.0, 3.0),
    "medium": (5.0, 5.0),
    "large": (7.0, 7.0),
    "huge": (10.0, 10.0),
}


def _size_bucket_to_footprint(size_bucket: str) -> Tuple[float, float]:
    """Convert LLM size_bucket string to exact (w, h) in tiles. Maps tiny -> small."""
    b = str(size_bucket).lower().strip()
    if b == "tiny":
        b = "small"
    return SIZE_BUCKET_FOOTPRINT.get(b, SIZE_BUCKET_FOOTPRINT["medium"])


def _size_multiplier(size_bucket: str) -> float:
    """Multiplier for heuristic mode (base footprint * mult). Tiny treated as small."""
    b = str(size_bucket).lower().strip()
    if b == "tiny":
        b = "small"
    mapping = {
        "small": 0.75,
        "medium": 1.00,
        "large": 1.70,
        "huge": 2.40,
    }
    return float(mapping.get(b, 1.00))

# -----------------------------
# Helpers
# -----------------------------

def tile_size_world_from_rect(rect: dict, tiles: int) -> float:
    w = float(rect["w"]); h = float(rect["h"])
    tiles = max(1, int(tiles))
    return min(w, h) / float(tiles)

def entity_tile_rect_to_world(rect: dict, tiles: int, p: dict) -> dict:
    x0, y0 = float(rect["x"]), float(rect["y"])
    ts = tile_size_world_from_rect(rect, tiles)
    pw, ph = float(p["w"]), float(p["h"])
    return {
        "x": x0 + float(p["x"]) * ts,
        "y": y0 + float(p["y"]) * ts,
        "w": pw * ts,
        "h": ph * ts,
        "kind": p.get("kind"),
        "group": p.get("group"),
        "id": p.get("id"),
        "needs_frontage": bool(p.get("needs_frontage", False)),
        "placeable_3d_asset": True,
        "grid_footprint_tiles": {"w": pw, "h": ph},
    }

def tile_xy_to_world_xy(rect: dict, tiles: int, tx: float, ty: float) -> list[float]:
    x0, y0 = float(rect["x"]), float(rect["y"])
    ts = tile_size_world_from_rect(rect, tiles)
    return [x0 + float(tx) * ts, y0 + float(ty) * ts]

def load_json(path: str) -> Any:
    if not os.path.exists(path):
        print(f"[error] Required file not found: {path}")
        print("  - Either place the file at that path, or set the env vars WORLD_PLAN and WORLD_GRAPH_LAYOUT")
        print("  - Example: WORLD_PLAN=./my_plan.json WORLD_GRAPH_LAYOUT=./my_wgl.json python world_entity_layout_llm_v3.py")
        raise SystemExit(2)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_rect(rect: dict) -> dict:
    """Normalize various rect encodings to {x,y,w,h}."""
    if rect is None:
        return {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}
    if all(k in rect for k in ("x", "y", "w", "h")):
        return {"x": float(rect["x"]), "y": float(rect["y"]), "w": float(rect["w"]), "h": float(rect["h"])}
    if all(k in rect for k in ("x", "y", "width", "height")):
        return {"x": float(rect["x"]), "y": float(rect["y"]), "w": float(rect["width"]), "h": float(rect["height"])}
    if all(k in rect for k in ("x0", "y0", "x1", "y1")):
        x0, y0, x1, y1 = float(rect["x0"]), float(rect["y0"]), float(rect["x1"]), float(rect["y1"])
        return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
    # fallbacks
    x = float(rect.get("x", rect.get("x0", 0.0)))
    y = float(rect.get("y", rect.get("y0", 0.0)))
    w = float(rect.get("w", rect.get("width", rect.get("x1", x) - x)))
    h = float(rect.get("h", rect.get("height", rect.get("y1", y) - y)))
    return {"x": x, "y": y, "w": w, "h": h}


def save_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def norm(s: str) -> str:
    return s.strip().lower().replace(" ", "_")


def dir_to_vec(d: str) -> Tuple[int, int]:
    d = d.upper()
    mapping = {
        "N": (0, 1),
        "NE": (1, 1),
        "E": (1, 0),
        "SE": (1, -1),
        "S": (0, -1),
        "SW": (-1, -1),
        "W": (-1, 0),
        "NW": (-1, 1),
    }
    return mapping.get(d, (0, 0))


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _quantile(vals: List[float], q: float) -> float:
    if not vals:
        return 0.0
    vals2 = sorted(vals)
    q = clamp(q, 0.0, 1.0)
    idx = int(round(q * (len(vals2) - 1)))
    return float(vals2[idx])


@dataclass
class Instance:
    id: str
    kind: str
    w: float
    h: float
    group: str


def _segment_intersects_rect(p0, p1, rect):
    # Liang-Barsky style: returns (t_enter, t_exit) or None
    x0, y0 = p0
    x1, y1 = p1
    rx, ry, rw, rh = rect["x"], rect["y"], rect["w"], rect["h"]
    xmin, xmax = rx, rx + rw
    ymin, ymax = ry, ry + rh

    dx = x1 - x0
    dy = y1 - y0

    p = [-dx, dx, -dy, dy]
    q = [x0 - xmin, xmax - x0, y0 - ymin, ymax - y0]

    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if abs(pi) < 1e-12:
            if qi < 0:
                return None
        else:
            t = qi / pi
            if pi < 0:
                u1 = max(u1, t)
            else:
                u2 = min(u2, t)

    if u1 > u2:
        return None
    return (u1, u2)


def _edge_t_from_point(rect, px, py):
    x, y, w, h = rect["x"], rect["y"], rect["w"], rect["h"]
    # find closest edge
    dl = abs(px - x)
    dr = abs(px - (x + w))
    db = abs(py - y)
    dt = abs(py - (y + h))
    mind = min(dl, dr, db, dt)

    if mind == dl:
        edge = "left"
        t = (py - y) / h if h > 0 else 0.5
    elif mind == dr:
        edge = "right"
        t = (py - y) / h if h > 0 else 0.5
    elif mind == db:
        edge = "bottom"
        t = (px - x) / w if w > 0 else 0.5
    else:
        edge = "top"
        t = (px - x) / w if w > 0 else 0.5

    return edge, clamp(t, 0.0, 1.0)

# -----------------------------
# Plan parsing
# -----------------------------

def _default_footprint_tiles(area_tiles_hint: int) -> Tuple[float, float]:
    """Default base footprint when LLM does not provide w_tiles/h_tiles (e.g. heuristic mode)."""
    base = max(4, int(area_tiles_hint * 0.08))
    return (base, base)


def expand_instances_from_plan(plan: Dict[str, Any], area_id: str, area_tiles_hint: int) -> Tuple[List[Instance], Optional[str]]:
    areas = plan.get("areas") or plan.get("world", {}).get("areas") or {}
    if isinstance(areas, list):
        areas_list = areas
        areas = {}
        for a in areas_list:
            if not isinstance(a, dict):
                continue
            k = a.get("id") or a.get("name") or a.get("area_id")
            if k is None:
                continue
            areas[str(k)] = a

    area = areas.get(area_id) or areas.get(norm(area_id))
    if area is None:
        for k, v in areas.items():
            if norm(k) == norm(area_id):
                area = v
                break
    if area is None:
        return [], None

    anchor_hint = area.get("anchor") or area.get("anchor_entity") or None
    instances: List[Instance] = []

    entities = area.get("entities") or area.get("assets") or area.get("objects") or []
    if isinstance(entities, dict):
        entities_iter = []
        for g, info in entities.items():
            if isinstance(info, dict):
                entities_iter.append({"group": g, **info})
            else:
                entities_iter.append({"group": g, "count": int(info)})
        entities = entities_iter

    for ent in entities:
        if not isinstance(ent, dict):
            continue
        group = ent.get("group") or ent.get("name") or ent.get("id") or "entity"
        group = norm(str(group))
        kind = ent.get("kind") or ent.get("type") or group
        kind = norm(str(kind))

        if kind == "scatter" or ent.get("is_scatter") is True:
            continue

        count = ent.get("count", 1)
        try:
            count = int(count)
        except Exception:
            count = 1

        # Use plan size_bucket for 2D grid footprint when present (placeable 3D asset). No tiny.
        sb = (ent.get("size_bucket") or "").strip().lower()
        if sb == "tiny":
            sb = "small"
        if sb not in SIZE_BUCKET_FOOTPRINT:
            sb = "medium"
        w, h = SIZE_BUCKET_FOOTPRINT[sb]

        for i in range(1, count + 1):
            inst_id = f"{group}_{i}" if count > 1 else group
            instances.append(Instance(id=inst_id, kind=kind, w=w, h=h, group=group))

    return instances, (norm(anchor_hint) if isinstance(anchor_hint, str) else None)


# -----------------------------
# Gates + layout helpers
# -----------------------------

def build_gate_edge_fraction(area_rect: Dict[str, float], gate_world: Dict[str, Any]) -> Dict[str, Any]:
    x0, y0, w, h = float(area_rect["x"]), float(area_rect["y"]), float(area_rect["w"]), float(area_rect["h"])
    gx, gy = float(gate_world.get("x", x0 + w * 0.5)), float(gate_world.get("y", y0 + h * 0.5))
    if w <= 0 or h <= 0:
        return {"edge": "top", "t": 0.5}

    u = clamp((gx - x0) / w, 0.0, 1.0)
    v = clamp((gy - y0) / h, 0.0, 1.0)

    d_left = u
    d_right = 1.0 - u
    d_bottom = v
    d_top = 1.0 - v

    mind = min(d_left, d_right, d_bottom, d_top)
    if mind == d_left:
        edge = "left"
        t = v
    elif mind == d_right:
        edge = "right"
        t = v
    elif mind == d_bottom:
        edge = "bottom"
        t = u
    else:
        edge = "top"
        t = u

    return {"edge": edge, "t": float(t)}


def gate_pos_from_edge_fraction(area_rect: Dict[str, float], edge_frac: Dict[str, Any]) -> Tuple[float, float]:
    x0, y0, w, h = float(area_rect["x"]), float(area_rect["y"]), float(area_rect["w"]), float(area_rect["h"])
    edge = edge_frac.get("edge", "top")
    t = clamp(float(edge_frac.get("t", 0.5)), 0.0, 1.0)

    if edge == "left":
        return (x0, y0 + t * h)
    if edge == "right":
        return (x0 + w, y0 + t * h)
    if edge == "bottom":
        return (x0 + t * w, y0)
    return (x0 + t * w, y0 + h)


def compass_from_gate(area_rect: Dict[str, float], gate_xy: Tuple[float, float]) -> str:
    x0, y0, w, h = float(area_rect["x"]), float(area_rect["y"]), float(area_rect["w"]), float(area_rect["h"])
    cx, cy = x0 + 0.5 * w, y0 + 0.5 * h
    gx, gy = gate_xy
    dx, dy = gx - cx, gy - cy
    if abs(dx) > abs(dy):
        return "E" if dx > 0 else "W"
    return "N" if dy > 0 else "S"

def split_connections_through_areas(wgl):
    areas = wgl.get("areas", {})
    conns = wgl.get("connections", [])
    if not conns:
        return

    new_conns = []

    # ensure every area has gates list
    for a in areas.values():
        a.setdefault("gates", [])

    def add_gate(area_id, edge, t, world_x, world_y):
        g = {"edge": edge, "t": t, "x": world_x, "y": world_y, "connects_to": None}
        areas[area_id]["gates"].append(g)
        return g

    for c in conns:
        ga = c.get("gate_a") or c.get("from_gate") or {}
        gb = c.get("gate_b") or c.get("to_gate") or {}
        if not all(k in ga for k in ("x", "y")) or not all(k in gb for k in ("x", "y")):
            new_conns.append(c)
            continue

        p0 = (float(ga["x"]), float(ga["y"]))
        p1 = (float(gb["x"]), float(gb["y"]))

        # find first blocking area (any area rect that the segment passes through)
        blocker = None
        enter_exit = None
        for aid, aobj in areas.items():
            r = normalize_rect(aobj.get("rect", {}))
            # skip if endpoint is inside this rect (usually same-area)
            hit = _segment_intersects_rect(p0, p1, r)
            if not hit:
                continue
            u1, u2 = hit
            # ignore trivial touches at endpoints
            if u2 <= 1e-3 or u1 >= 1.0 - 1e-3:
                continue
            blocker = aid
            enter_exit = (u1, u2, r)
            break

        if not blocker:
            new_conns.append(c)
            continue

        u1, u2, r = enter_exit
        ex = p0[0] + (p1[0] - p0[0]) * u1
        ey = p0[1] + (p1[1] - p0[1]) * u1
        lx = p0[0] + (p1[0] - p0[0]) * u2
        ly = p0[1] + (p1[1] - p0[1]) * u2

        edge1, t1 = _edge_t_from_point(r, ex, ey)
        edge2, t2 = _edge_t_from_point(r, lx, ly)

        g_in = add_gate(blocker, edge1, t1, ex, ey)
        g_out = add_gate(blocker, edge2, t2, lx, ly)

        # split into two connections
        new_conns.append({"gate_a": ga, "gate_b": g_in})
        new_conns.append({"gate_a": g_out, "gate_b": gb})

    wgl["connections"] = new_conns

# -----------------------------
# Intent generation (Heuristic + LLM)
# -----------------------------

def heuristic_intent(
    instances: List[Instance],
    npc_anchor_ids: Optional[Set[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    npc_anchor_ids = npc_anchor_ids or set()

    def score(inst: Instance) -> float:
        a = inst.w * inst.h
        bonus = 0.0
        k = inst.kind
        if any(t in k for t in ["shrine", "altar", "tower", "gateway", "temple", "palace", "cathedral"]):
            bonus += 80
        if any(t in k for t in ["market", "warehouse", "dock", "inn", "tavern", "shop", "hall"]):
            bonus += 40
        return a + bonus

    ranked = sorted(instances, key=score, reverse=True)

    # Residential buildings (houses, dwellings) must get at least medium so they don't end up 3×3
    def _is_residential(inst: Instance) -> bool:
        grp = (inst.group or "").lower()
        return "house" in grp or "dwelling" in grp or "home" in grp or "residential" in grp

    for idx, inst in enumerate(ranked):
        d = DIRS[idx % len(DIRS)]
        dist_bucket = ["tiny", "small", "medium", "large"][min(3, idx // 4)]

        if idx == 0:
            size_bucket = "huge"
        elif idx <= 2:
            size_bucket = "large"
        elif idx <= 6:
            size_bucket = "medium"
        else:
            size_bucket = "small"

        # Residential entities get at least medium so footprint is plausible (e.g. 6×6 base → 6×6 or 5×5)
        if _is_residential(inst) and _size_multiplier(size_bucket) < _size_multiplier("medium"):
            size_bucket = "medium"

        k = inst.kind
        needs_frontage = any(t in k for t in ["market", "shop", "inn", "dock", "gate", "warehouse", "stall", "tavern"])
        # NPC anchors: entities where NPCs stand must be accessible (needs_frontage=true)
        if inst.group in npc_anchor_ids or inst.id in npc_anchor_ids:
            needs_frontage = True

        out[inst.id] = {
            "relative_to": "anchor",
            "dir": d,
            "dist_bucket": dist_bucket,
            "size_bucket": size_bucket,
            "needs_frontage": needs_frontage,
        }

    return out

def _call_gemini_for_intent(
    area_id: str,
    instances: List[Instance],
    gates_summary: List[Dict[str, Any]],
    npc_anchor_ids: Optional[Set[str]] = None,
) -> Optional[Dict[str, Dict[str, Any]]]:
    try:
        import gemini_client as gc
    except Exception as e:
        print(f"[warn] gemini_client not available: {e}")
        return None

    ids = [i.id for i in instances]
    valid_ids = set(ids)

    entities_compact = [
        {"id": i.id, "kind": i.kind, "group": i.group, "w_tiles_base": i.w, "h_tiles_base": i.h}
        for i in instances
    ]

    npc_anchor_ids = npc_anchor_ids or set()
    npc_anchor_note = ""
    if npc_anchor_ids:
        npc_anchors_in_area = [i.id for i in instances if i.group in npc_anchor_ids or i.id in npc_anchor_ids]
        if npc_anchors_in_area:
            npc_anchor_note = (
                f"IMPORTANT: These entity IDs are NPC anchors (NPCs stand next to them): {npc_anchors_in_area}. "
                "Place them with needs_frontage=true so NPCs are accessible."
            )

    sys_msg = (
        "You design semantic layouts inside a rectangular area. "
        "You do NOT output coordinates. "
        "For each entity, output: relative_to, dir, dist_bucket, size_bucket, needs_frontage. "
        "The 'anchor' is an abstract center point. "
        "size_bucket controls footprint: use small, medium, large, or huge only (no tiny — every entity must have a solid grid footprint). "
        "Choose size_bucket from the entity's kind/group (e.g. houses at least medium, statues small or medium, towers large). "
        "Set needs_frontage=true for entities that should connect to roads/paths (shops, markets, docks, inns, etc). "
        "Use varied dist_bucket and size_bucket so things don't cluster or look same-sized. "
        + npc_anchor_note
    )

    user_payload = {
        "area_id": area_id,
        "entities": entities_compact,
        "allowed_dirs": DIRS,
        "allowed_dist_buckets": DIST_BUCKETS,
        "allowed_size_buckets": SIZE_BUCKETS,
        "gates": gates_summary,
        "requirements": [
            "Return an intent for EVERY entity id.",
            "Use only allowed dirs/dist_buckets/size_buckets.",
            "relative_to must be 'anchor' or another entity id.",
            "needs_frontage must be boolean.",
        ],
    }

    schema_only = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "intents": {
                "type": "array",
                "minItems": len(ids),
                "maxItems": len(ids),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string"},
                        "relative_to": {"type": "string"},
                        "dir": {"type": "string", "enum": DIRS},
                        "dist_bucket": {"type": "string", "enum": DIST_BUCKETS},
                        "size_bucket": {"type": "string", "enum": SIZE_BUCKETS},
                        "needs_frontage": {"type": "boolean"},
                    },
                    "required": ["id", "relative_to", "dir", "dist_bucket", "size_bucket", "needs_frontage"],
                },
            }
        },
        "required": ["intents"],
    }

    def _normalize_and_validate(parsed: dict) -> Optional[Dict[str, Dict[str, Any]]]:
        intents_arr = parsed.get("intents", [])
        mapping: Dict[str, Dict[str, Any]] = {}

        for row in intents_arr:
            try:
                _id = norm(row["id"])
                rel = norm(row["relative_to"])
                d = str(row["dir"]).upper()
                b = str(row["dist_bucket"]).lower()
                sb = str(row["size_bucket"]).lower()
                needs_frontage = bool(row.get("needs_frontage", False))
            except Exception:
                continue

            if _id not in valid_ids:
                continue
            if rel != "anchor" and rel not in valid_ids:
                rel = "anchor"
            if d not in DIRS:
                d = random.choice(DIRS)
            if b not in DIST_BUCKETS:
                b = "medium"
            if sb not in SIZE_BUCKETS:
                sb = "small" if sb == "tiny" else "medium"

            mapping[_id] = {
                "relative_to": rel,
                "dir": d,
                "dist_bucket": b,
                "size_bucket": sb,
                "needs_frontage": needs_frontage,
            }

        if len(mapping) != len(ids):
            return None
        return mapping

    user = json.dumps(user_payload) + "\n\nSchema: " + json.dumps(schema_only)
    try:
        parsed = gc.generate_json(sys_msg, user, model=GEMINI_MODEL, temperature=0.2)
        mapping = _normalize_and_validate(parsed if isinstance(parsed, dict) else {})
        if mapping is not None:
            return mapping
    except Exception as e:
        print(f"[warn] Gemini intent call failed: {e}")
    print("[warn] LLM returned invalid intent; falling back to heuristic.")
    return None
def get_intent(
    instances: List[Instance],
    area_id: str,
    gates_summary: List[Dict[str, Any]],
    npc_anchor_ids: Optional[Set[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    if USE_LLM:
        m = _call_gemini_for_intent(
            area_id=area_id,
            instances=instances,
            gates_summary=gates_summary,
            npc_anchor_ids=npc_anchor_ids,
        )
        if m is not None:
            return m
    return heuristic_intent(instances, npc_anchor_ids=npc_anchor_ids)


# -----------------------------
# Deterministic placement
# -----------------------------

def _bucket_radius_tiles(bucket: str, tiles: int) -> float:
    tiles = max(16, int(tiles))
    base = max(5.0, tiles * 0.12)
    mapping = {
        "tiny": 1.00 * base,
        "small": 1.60 * base,
        "medium": 2.30 * base,
        "large": 3.10 * base,
    }
    return float(mapping.get(bucket, 1.2 * base))


def _rects_overlap(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float], pad: float) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (
        ax + aw + pad <= bx or
        bx + bw + pad <= ax or
        ay + ah + pad <= by or
        by + bh + pad <= ay
    )


def _inside_bounds(x: float, y: float, w: float, h: float, tiles: float) -> bool:
    return (x >= 0 and y >= 0 and (x + w) <= tiles and (y + h) <= tiles)


def _spiral_candidates(cx: float, cy: float, step: float, max_r: float) -> List[Tuple[float, float]]:
    pts: List[Tuple[float, float]] = []
    r = 0.0
    while r <= max_r:
        n = max(8, int(2 * math.pi * max(1.0, r) / max(1e-6, step)))
        for k in range(n):
            ang = (2 * math.pi * k) / n
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        r += step
    return pts


import heapq
import math

def _edge_index_from_xy(tile_xy: tuple[int,int], edge: str) -> int:
    x, y = tile_xy
    edge = (edge or "top").lower()
    return y if edge in ("left", "right") else x

def _t_from_tile_on_edge(edge: str, idx: int, tiles: int) -> float:
    # idx in [0..tiles-1] -> t in [0..1]
    if tiles <= 1:
        return 0.5
    return float(idx) / float(tiles - 1)

def _candidate_indices_around(idx0: int, tiles: int, radius: int = 4) -> list[int]:
    lo = max(0, idx0 - radius)
    hi = min(tiles - 1, idx0 + radius)
    # center-out ordering
    out = []
    for d in range(0, radius + 1):
        a = idx0 - d
        b = idx0 + d
        if lo <= a <= hi: out.append(a)
        if d != 0 and lo <= b <= hi: out.append(b)
    # dedup while preserving order
    seen = set()
    out2 = []
    for v in out:
        if v not in seen:
            seen.add(v)
            out2.append(v)
    return out2

def _a_star_cost_only(
    start: tuple[int, int],
    goals: set[tuple[int, int]],
    blocked_hard: set[tuple[int, int]],
    blocked_soft: set[tuple[int, int]],
    tiles: int,
    road_tiles: set[tuple[int, int]],
    reuse_bonus: float = 0.4,
    prox_penalty_radius: int = 1,
    prox_penalty: float = 0.25,
) -> float | None:
    """
    Returns cheapest cost from start to ANY goal tile, without reconstructing a path.
    - blocked_hard: cannot enter
    - blocked_soft: adds proximity penalty (soft avoidance)
    """
    tiles = int(tiles)
    if start in blocked_hard:
        return None
    if start in goals:
        return 0.0

    def prox_cost(nx: int, ny: int) -> float:
        if prox_penalty_radius <= 0:
            return 0.0
        # penalize if we're close to the soft blocked region
        for dx in range(-prox_penalty_radius, prox_penalty_radius + 1):
            for dy in range(-prox_penalty_radius, prox_penalty_radius + 1):
                if (nx + dx, ny + dy) in blocked_soft:
                    return prox_penalty
        return 0.0

    # heuristic: Manhattan to closest goal (good enough for these grid sizes)
    def h(x: int, y: int) -> float:
        best = 1e18
        for gx, gy in goals:
            best = min(best, abs(gx - x) + abs(gy - y))
        return float(best)

    open_heap: list[tuple[float, tuple[int, int]]] = []
    gscore: dict[tuple[int, int], float] = {start: 0.0}
    heapq.heappush(open_heap, (h(*start), start))
    closed: set[tuple[int, int]] = set()

    while open_heap:
        _, cur = heapq.heappop(open_heap)
        if cur in closed:
            continue
        closed.add(cur)

        if cur in goals:
            return gscore[cur]

        cx, cy = cur
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if not (0 <= nx < tiles and 0 <= ny < tiles):
                continue
            if (nx, ny) in blocked_hard:
                continue

            step = 1.0
            if (nx, ny) in road_tiles:
                step = max(0.05, step - reuse_bonus)
            step += prox_cost(nx, ny)

            ng = gscore[cur] + step
            if ng < gscore.get((nx, ny), 1e30):
                gscore[(nx, ny)] = ng
                heapq.heappush(open_heap, (ng + h(nx, ny), (nx, ny)))

    return None


def _edge_index_from_xy(tile_xy: tuple[int, int], edge: str) -> int:
    x, y = tile_xy
    edge = (edge or "top").lower()
    return y if edge in ("left", "right") else x


def _t_from_tile_on_edge(edge: str, idx: int, tiles: int) -> float:
    if tiles <= 1:
        return 0.5
    idx = max(0, min(int(tiles) - 1, int(idx)))
    return float(idx) / float(int(tiles) - 1)


def _candidate_indices_around(idx0: int, tiles: int, radius: int = 12) -> list[int]:
    tiles = int(tiles)
    idx0 = max(0, min(tiles - 1, int(idx0)))
    radius = max(1, int(radius))

    out: list[int] = []
    for d in range(0, radius + 1):
        a = idx0 - d
        b = idx0 + d
        if 0 <= a <= tiles - 1:
            out.append(a)
        if d != 0 and 0 <= b <= tiles - 1:
            out.append(b)

    # dedup
    seen = set()
    out2 = []
    for v in out:
        if v not in seen:
            seen.add(v)
            out2.append(v)
    return out2


def optimize_gates_for_roads(
    gates: list[dict],
    blocked_hard: set[tuple[int, int]],
    blocked_soft: set[tuple[int, int]],
    tiles: int,
    anchor: tuple[int, int],
    search_radius_tiles: int = 16,
) -> tuple[list[dict], list[tuple[int, int]]]:
    """
    Slides each gate along its edge (changes t) to a nearby reachable tile.
    If local search fails (because entity blocks the edge segment), scan the whole edge.
    """
    tiles = int(tiles)
    road_tiles: set[tuple[int, int]] = {anchor}

    updated: list[dict] = []
    gate_tiles: list[tuple[int, int]] = []

    for g in (gates or []):
        edge = (g.get("edge") or "top").lower()
        t0 = float(g.get("t", 0.5))

        start_tile = gate_tile_xy(edge, t0, tiles=tiles)
        idx0 = _edge_index_from_xy(start_tile, edge)

        best_tile = None
        best_t = t0
        best_cost = None

        # -----------------------------
        # 1) Local search around idx0
        # -----------------------------
        for idx in _candidate_indices_around(idx0, tiles=tiles, radius=search_radius_tiles):
            t = _t_from_tile_on_edge(edge, idx, tiles)
            cand_tile = gate_tile_xy(edge, t, tiles=tiles)

            if cand_tile in blocked_hard:
                continue

            cost = _a_star_cost_only(
                start=cand_tile,
                goals=road_tiles,
                blocked_hard=blocked_hard,
                blocked_soft=blocked_soft,
                tiles=tiles,
                road_tiles=road_tiles,
            )
            if cost is None:
                continue

            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_tile = cand_tile
                best_t = t

        # -----------------------------
        # 2) Fallback: scan entire edge
        #    (handles case where a big entity blocks the local segment)
        # -----------------------------
        if best_tile is None:
            for idx in range(0, tiles):
                t = _t_from_tile_on_edge(edge, idx, tiles)
                cand_tile = gate_tile_xy(edge, t, tiles=tiles)
                if cand_tile in blocked_hard:
                    continue

                cost = _a_star_cost_only(
                    start=cand_tile,
                    goals=road_tiles,
                    blocked_hard=blocked_hard,
                    blocked_soft=blocked_soft,
                    tiles=tiles,
                    road_tiles=road_tiles,
                )

                # If reachable, prefer cheapest reachable
                if cost is not None and (best_cost is None or cost < best_cost):
                    best_cost = cost
                    best_tile = cand_tile
                    best_t = t

            # If still none reachable, at least choose nearest UNBLOCKED position
            # (so the gate moves off the entity even if pathfinding can't connect yet)
            if best_tile is None:
                nearest = None
                nearest_d = None
                for idx in range(0, tiles):
                    t = _t_from_tile_on_edge(edge, idx, tiles)
                    cand_tile = gate_tile_xy(edge, t, tiles=tiles)
                    if cand_tile in blocked_hard:
                        continue
                    d = abs(idx - idx0)
                    if nearest_d is None or d < nearest_d:
                        nearest_d = d
                        nearest = (cand_tile, t)
                if nearest is not None:
                    best_tile, best_t = nearest

        # As a last resort (edge fully blocked), keep original
        if best_tile is None:
            best_tile = start_tile
            best_t = t0

        g2 = dict(g)
        g2["t"] = float(best_t)
        updated.append(g2)
        gate_tiles.append(best_tile)

        # grow network seed so future gates prefer joining earlier connected points
        road_tiles.add(best_tile)

    return updated, gate_tiles# -----------------------------
# Placement + Roads: required helpers you are currently missing
# Paste this whole section ABOVE grow_until_fit()
# -----------------------------

def gate_tile_xy(edge: str, tfrac: float, tiles: int) -> tuple[int, int]:
    """
    Convert (edge, t) -> an *interior* walkable tile coordinate.
    - left  edge => x = 1
    - right edge => x = tiles-2
    - bottom     => y = 1
    - top        => y = tiles-2
    """
    edge = (edge or "top").lower()
    tfrac = clamp(float(tfrac), 0.0, 1.0)
    tiles = int(tiles)

    if tiles <= 2:
        return (0, 0)

    idx = int(round(tfrac * (tiles - 1)))
    idx = max(0, min(tiles - 1, idx))

    if edge == "left":
        return (1, idx)
    if edge == "right":
        return (tiles - 2, idx)
    if edge == "bottom":
        return (idx, 1)
    # top
    return (idx, tiles - 2)

def build_blocked_from_placements(
    placements: dict[str, dict],
    tiles: int,
    pad: int = 0,
) -> set[tuple[int, int]]:
    """
    Returns a set of blocked grid tiles occupied by entity rectangles.
    pad expands the blocked area around entities (integer tiles).
    """
    blocked: set[tuple[int, int]] = set()
    tiles = int(tiles)
    pad = int(pad)

    for _, p in (placements or {}).items():
        x = float(p["x"])
        y = float(p["y"])
        w = float(p["w"])
        h = float(p["h"])

        x0 = int(math.floor(x)) - pad
        y0 = int(math.floor(y)) - pad
        x1 = int(math.ceil(x + w)) + pad - 1
        y1 = int(math.ceil(y + h)) + pad - 1

        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(tiles - 1, x1)
        y1 = min(tiles - 1, y1)

        for tx in range(x0, x1 + 1):
            for ty in range(y0, y1 + 1):
                blocked.add((tx, ty))

    return blocked

def pick_frontage_door(
    p: dict,
    blocked_hard: set[tuple[int, int]],
    tiles: int,
    prefer: tuple[int, int],
) -> tuple[int, int] | None:
    """
    Pick a walkable tile adjacent to the entity footprint to serve as a door/frontage point.
    We search perimeter-adjacent tiles and pick the one closest to `prefer`.
    """
    tiles = int(tiles)
    px, py = float(p["x"]), float(p["y"])
    pw, ph = float(p["w"]), float(p["h"])

    # entity bbox in tile coords
    x0 = int(math.floor(px))
    y0 = int(math.floor(py))
    x1 = int(math.ceil(px + pw)) - 1
    y1 = int(math.ceil(py + ph)) - 1

    candidates: list[tuple[int, int]] = []

    # tiles immediately outside each side
    for x in range(x0, x1 + 1):
        candidates.append((x, y0 - 1))  # below
        candidates.append((x, y1 + 1))  # above
    for y in range(y0, y1 + 1):
        candidates.append((x0 - 1, y))  # left
        candidates.append((x1 + 1, y))  # right

    # keep in bounds and not hard-blocked
    good: list[tuple[int, int]] = []
    for (cx, cy) in candidates:
        if 0 <= cx < tiles and 0 <= cy < tiles and (cx, cy) not in blocked_hard:
            good.append((cx, cy))

    if not good:
        return None

    tx, ty = prefer
    good.sort(key=lambda c: abs(c[0] - tx) + abs(c[1] - ty))
    return good[0]

def a_star_to_network(
    start: tuple[int, int],
    goals: set[tuple[int, int]],
    blocked_hard: set[tuple[int, int]],
    blocked_soft: set[tuple[int, int]],
    tiles: int,
    road_tiles: set[tuple[int, int]],
    reuse_bonus: float = 0.4,
    prox_penalty_radius: int = 1,
    prox_penalty: float = 0.25,
) -> list[tuple[int, int]] | None:
    """
    Find a path from start to ANY goal in `goals`. Returns list of tiles including start+goal.
    """
    tiles = int(tiles)
    if start in blocked_hard:
        return None
    if start in goals:
        return [start]

    def prox_cost(nx: int, ny: int) -> float:
        if prox_penalty_radius <= 0:
            return 0.0
        for dx in range(-prox_penalty_radius, prox_penalty_radius + 1):
            for dy in range(-prox_penalty_radius, prox_penalty_radius + 1):
                if (nx + dx, ny + dy) in blocked_soft:
                    return prox_penalty
        return 0.0

    def h(x: int, y: int) -> float:
        best = 1e18
        for gx, gy in goals:
            best = min(best, abs(gx - x) + abs(gy - y))
        return float(best)

    open_heap: list[tuple[float, tuple[int, int]]] = []
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    gscore: dict[tuple[int, int], float] = {start: 0.0}
    heapq.heappush(open_heap, (h(*start), start))
    closed: set[tuple[int, int]] = set()

    while open_heap:
        _, cur = heapq.heappop(open_heap)
        if cur in closed:
            continue
        closed.add(cur)

        if cur in goals:
            # reconstruct
            path = [cur]
            while path[-1] != start:
                path.append(came_from[path[-1]])
            path.reverse()
            return path

        cx, cy = cur
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if not (0 <= nx < tiles and 0 <= ny < tiles):
                continue
            if (nx, ny) in blocked_hard:
                continue

            step = 1.0
            if (nx, ny) in road_tiles:
                step = max(0.05, step - reuse_bonus)
            step += prox_cost(nx, ny)

            ng = gscore[cur] + step
            if ng < gscore.get((nx, ny), 1e30):
                gscore[(nx, ny)] = ng
                came_from[(nx, ny)] = cur
                heapq.heappush(open_heap, (ng + h(nx, ny), (nx, ny)))

    return None


def place_area(
    instances: list[Instance],
    tiles: int,
    intent: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]] | None:
    """
    Deterministically places rectangles in tile-space using intent.
    Returns placements dict or None if cannot place all.
    """
    tiles = int(tiles)
    pad = float(GLOBAL_ENTITY_PADDING_TILES)

    anchor = (tiles * 0.5, tiles * 0.5)

    # place largest first for stability (footprint from size_bucket -> exact w,h)
    def area_score(inst: Instance) -> float:
        it = intent.get(inst.id) or {}
        sb = it.get("size_bucket", "medium")
        w, h = _size_bucket_to_footprint(sb)
        return w * h

    ordered = sorted(instances, key=area_score, reverse=True)

    placed_rects: list[tuple[float, float, float, float]] = []
    placements: dict[str, dict[str, Any]] = {}

    def target_for(inst: Instance) -> tuple[float, float]:
        it = intent.get(inst.id) or {}
        rel = it.get("relative_to", "anchor")
        d = it.get("dir", "N")
        b = it.get("dist_bucket", "medium")

        if rel != "anchor" and rel in placements:
            base = placements[rel]
            cx = float(base["x"]) + 0.5 * float(base["w"])
            cy = float(base["y"]) + 0.5 * float(base["h"])
        else:
            cx, cy = anchor

        vx, vy = dir_to_vec(str(d))
        r = _bucket_radius_tiles(str(b), tiles=tiles)
        return (cx + vx * r, cy + vy * r)

    for inst in ordered:
        it = intent.get(inst.id) or {}
        # LLM only gives size_bucket (tiny/small/medium/large/huge); we map to exact w, h
        sb = it.get("size_bucket", "medium")
        w, h = _size_bucket_to_footprint(sb)
        w = max(2.0, min(w, tiles - 2.0))
        h = max(2.0, min(h, tiles - 2.0))

        tx, ty = target_for(inst)

        # candidate centers around target
        step = max(0.75, min(w, h) * 0.35)
        max_r = float(tiles) * 0.65
        candidates = _spiral_candidates(tx, ty, step=step, max_r=max_r)

        ok = False
        for cx, cy in candidates:
            x = cx - 0.5 * w
            y = cy - 0.5 * h

            # clamp to inside bounds
            x = clamp(x, 0.0, tiles - w)
            y = clamp(y, 0.0, tiles - h)

            rect = (x, y, w, h)

            # overlap test
            bad = False
            for r2 in placed_rects:
                if _rects_overlap(rect, r2, pad=pad):
                    bad = True
                    break
            if bad:
                continue

            if not _inside_bounds(x, y, w, h, float(tiles)):
                continue

            placements[inst.id] = {
                "id": inst.id,
                "kind": inst.kind,
                "group": inst.group,
                "x": float(x),
                "y": float(y),
                "w": float(w),
                "h": float(h),
                "needs_frontage": bool((intent.get(inst.id) or {}).get("needs_frontage", False)),
                "placeable_3d_asset": True,
                "grid_footprint_tiles": {"w": float(w), "h": float(h)},
            }
            placed_rects.append(rect)
            ok = True
            break

        if not ok:
            return None

    return placements


def normalize_group_sizes(intent: Dict[str, Dict[str, Any]], instances: List[Instance]) -> Dict[str, Dict[str, Any]]:
    """
    Normalize size_bucket for all instances with the same group.
    Uses the BIGGEST size_bucket per group (largest footprint).
    This ensures consistent footprints: all "inn" buildings have same size across areas.
    The normalized sizes are written to placements JSON and used in PNG rendering.
    """
    # Group instances by group name
    group_to_instances: Dict[str, List[str]] = {}
    for inst in instances:
        group = inst.group
        if group not in group_to_instances:
            group_to_instances[group] = []
        group_to_instances[group].append(inst.id)
    
    # For each group, find the BIGGEST size_bucket (by footprint area)
    group_to_size_bucket: Dict[str, str] = {}
    for group, inst_ids in group_to_instances.items():
        seen_buckets: set[str] = set()
        for inst_id in inst_ids:
            it = intent.get(inst_id, {})
            sb = str(it.get("size_bucket", "medium")).lower().strip()
            if sb not in SIZE_BUCKETS:
                sb = "small" if sb == "tiny" else "medium"
            seen_buckets.add(sb)
        
        # Pick the biggest bucket by footprint area (w * h)
        if seen_buckets:
            best_sb = max(seen_buckets, key=lambda sb: SIZE_BUCKET_FOOTPRINT.get(sb, SIZE_BUCKET_FOOTPRINT["medium"])[0] * SIZE_BUCKET_FOOTPRINT.get(sb, SIZE_BUCKET_FOOTPRINT["medium"])[1])
        else:
            best_sb = "medium"
        group_to_size_bucket[group] = best_sb
    
    # Apply normalized size_bucket to all instances in each group
    normalized_intent = dict(intent)
    for group, inst_ids in group_to_instances.items():
        normalized_sb = group_to_size_bucket[group]
        for inst_id in inst_ids:
            if inst_id not in normalized_intent:
                normalized_intent[inst_id] = {}
            normalized_intent[inst_id]["size_bucket"] = normalized_sb
            # Preserve other intent fields
            if inst_id in intent:
                for k, v in intent[inst_id].items():
                    if k != "size_bucket":
                        normalized_intent[inst_id][k] = v
    
    return normalized_intent


def grow_until_fit(instances: List[Instance], start_tiles: int, intent: Dict[str, Dict[str, Any]]) -> Tuple[int, Dict[str, Dict[str, Any]]]:
    tiles = max(16, int(start_tiles))
    for _ in range(MAX_GROW_ITERS):
        placed = place_area(instances=instances, tiles=tiles, intent=intent)
        if placed is not None:
            return tiles, placed
        tiles = int(math.ceil(tiles * GROWTH_FACTOR))
    placed = place_area(instances=instances, tiles=tiles, intent=intent)
    if placed is None:
        return tiles, {}
    return tiles, placed


# -----------------------------
# World drawing
# -----------------------------

def _iter_placements(area_obj):
    pl = area_obj.get("placements")
    if not pl:
        return []
    if isinstance(pl, dict):
        return list(pl.values())
    if isinstance(pl, list):
        return pl
    return []


def draw_area(ax, ao, title=""):
    ts = ao.get("tile_size")
    if ts and isinstance(ts, (list, tuple)) and len(ts) == 2:
        tw, th = int(ts[0]), int(ts[1])
    else:
        t = ao.get("tiles", 20)
        tw, th = int(t), int(t)

    # padding so labels aren't clipped
    x_pad = 0.5
    y_pad_bottom = 0.5
    y_pad_top = max(2.0, 0.10 * th)

    def gate_tile_xy_local(edge: str, tfrac: float) -> Tuple[float, float]:
        edge = (edge or "top").lower()
        tfrac = clamp(float(tfrac), 0.0, 1.0)
        if edge == "left":
            return (0.0, tfrac * th)
        if edge == "right":
            return (float(tw), tfrac * th)
        if edge == "bottom":
            return (tfrac * tw, 0.0)
        return (tfrac * tw, float(th))

    # area border
    ax.add_patch(plt.Rectangle((0, 0), tw, th, fill=False))

    # -----------------------------
    # ROADS (draw first, under everything)
    # -----------------------------
    roads = ao.get("roads") or {}
    road_tiles = roads.get("road_tiles") or []
    if road_tiles:
        for (tx, ty) in road_tiles:
            # draw road as filled 1x1 tile
            ax.add_patch(plt.Rectangle((tx, ty), 1.0, 1.0, fill=True, alpha=0.25, linewidth=0))

    # OPTIONAL: show terminals and anchor for debugging
    terminals = roads.get("terminals") or []
    if terminals:
        ax.scatter([t[0] for t in terminals], [t[1] for t in terminals], s=18, marker="x", alpha=0.9)

    anchor_tile = roads.get("anchor_tile")
    if anchor_tile:
        ax.scatter([anchor_tile[0]], [anchor_tile[1]], s=28, marker="*", alpha=0.9)

    # -----------------------------
    # GATES
    # -----------------------------
    for gi, g in enumerate(ao.get("gates", []) or [], start=1):
        gx, gy = gate_tile_xy(g.get("edge", "top"), g.get("t", 0.5), tiles=tw)
        ax.plot([gx], [gy], marker="o", markersize=5)

        connect_to = g.get("connect_to")
        edge = g.get("edge", "gate")
        label = f"{edge}#{gi}"
        if connect_to:
            label = f"{label}→{connect_to}"

        # ax.annotate(
        #     label,
        #     xy=(gx, gy),
        #     xytext=(6, 6),
        #     textcoords="offset points",
        #     ha="left",
        #     va="bottom",
        #     fontsize=7,
        #     bbox=dict(facecolor="white", edgecolor="none", alpha=0.75, pad=0.3),
        #     clip_on=False,
        # )

    # -----------------------------
    # ENTITIES
    # -----------------------------
    for ent_id, p in (ao.get("placements") or {}).items():
        x, y = float(p["x"]), float(p["y"])
        w, h = float(p["w"]), float(p["h"])
        edge_col = "red" if p.get("needs_frontage") else "black"
        ax.add_patch(plt.Rectangle((x, y), w, h, fill=False, edgecolor=edge_col))
        ax.plot([x + w / 2.0], [y + h / 2.0], marker="x", markersize=3, color=edge_col)

        # label above box
        label = ent_id or p.get("group") or p.get("kind") or ""
        if label:
            ax.text(
                x + w * 0.5,
                y + h + 0.4,
                str(label),
                fontsize=7,
                ha="center",
                va="bottom",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.75, pad=0.3),
                clip_on=False,
            )

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-x_pad, tw + x_pad)
    ax.set_ylim(-y_pad_bottom, th + y_pad_top)
    ax.set_title(title)
def sync_wgl_gates_and_connections(wgl: dict, area_layouts: dict, eps: float = 2.0) -> None:
    """
    Updates:
      - wgl["areas"][aid]["gates"] to the moved gate positions from area_layouts
      - wgl["connections"] endpoints so inter-area lines point to the moved gates

    Strategy for connections:
      - For each endpoint (x,y), infer which area it belongs to (on/near boundary or inside rect)
      - Snap that endpoint to the nearest gate in that area (after movement)
    """

    areas = wgl.get("areas", {}) or {}

    # -------- helpers --------
    def _rect_dist2(rect: dict, x: float, y: float) -> float:
        # squared distance from point to axis-aligned rect (0 if inside)
        rx, ry, rw, rh = float(rect["x"]), float(rect["y"]), float(rect["w"]), float(rect["h"])
        x0, x1 = rx, rx + rw
        y0, y1 = ry, ry + rh
        dx = 0.0
        if x < x0:
            dx = x0 - x
        elif x > x1:
            dx = x - x1
        dy = 0.0
        if y < y0:
            dy = y0 - y
        elif y > y1:
            dy = y - y1
        return dx * dx + dy * dy

    def _point_in_or_near_rect(rect: dict, x: float, y: float, eps_: float) -> bool:
        rx, ry, rw, rh = float(rect["x"]), float(rect["y"]), float(rect["w"]), float(rect["h"])
        x0, x1 = rx - eps_, rx + rw + eps_
        y0, y1 = ry - eps_, ry + rh + eps_
        return (x0 <= x <= x1) and (y0 <= y <= y1)

    def _find_area_for_point(x: float, y: float) -> str | None:
        # 1) Prefer areas where point is inside/near (expanded by eps)
        near = []
        for aid, aobj in areas.items():
            rect = normalize_rect(aobj.get("rect", {}))
            aobj["rect"] = rect
            if _point_in_or_near_rect(rect, x, y, eps):
                # distance to rect boundary/inside
                near.append((aid, _rect_dist2(rect, x, y)))
        if near:
            near.sort(key=lambda t: t[1])
            return near[0][0]

        # 2) Fallback: closest rect
        best_aid = None
        best_d2 = None
        for aid, aobj in areas.items():
            rect = normalize_rect(aobj.get("rect", {}))
            aobj["rect"] = rect
            d2 = _rect_dist2(rect, x, y)
            if best_d2 is None or d2 < best_d2:
                best_d2 = d2
                best_aid = aid
        return best_aid

    def _nearest_gate_xy(aid: str, x: float, y: float) -> tuple[float, float] | None:
        gts = (areas.get(aid, {}) or {}).get("gates") or []
        if not gts:
            return None
        best = None
        best_d2 = None
        for g in gts:
            gx = float(g.get("x", g.get("world_x", 0.0)))
            gy = float(g.get("y", g.get("world_y", 0.0)))
            d2 = (gx - x) ** 2 + (gy - y) ** 2
            if best_d2 is None or d2 < best_d2:
                best_d2 = d2
                best = (gx, gy)
        return best

    # -------- 1) overwrite WGL area gates with updated positions --------
    for aid, layout in (area_layouts or {}).items():
        if aid not in areas:
            continue
        rect = normalize_rect(areas[aid].get("rect", {}))
        areas[aid]["rect"] = rect

        new_gates = []
        for g in (layout.get("gates") or []):
            gx = float(g.get("world_x", g.get("x", 0.0)))
            gy = float(g.get("world_y", g.get("y", 0.0)))
            new_gates.append({
                "x": gx,
                "y": gy,
                "world_x": gx,
                "world_y": gy,
                "edge": g.get("edge", "top"),
                "t": float(g.get("t", 0.5)),
                # preserve either naming
                "connects_to": g.get("connects_to") or g.get("connect_to") or None,
            })
        areas[aid]["gates"] = new_gates

    wgl["areas"] = areas

    # -------- 2) snap existing connection endpoints to nearest UPDATED gates --------
    conns = wgl.get("connections", []) or []
    for c in conns:
        # support both gate_a/b and from_gate/to_gate
        a_key = "gate_a" if "gate_a" in c else ("from_gate" if "from_gate" in c else None)
        b_key = "gate_b" if "gate_b" in c else ("to_gate" if "to_gate" in c else None)
        if not a_key or not b_key:
            continue

        ga = c.get(a_key) or {}
        gb = c.get(b_key) or {}
        if not ("x" in ga and "y" in ga and "x" in gb and "y" in gb):
            continue

        ax, ay = float(ga["x"]), float(ga["y"])
        bx, by = float(gb["x"]), float(gb["y"])

        aid_a = _find_area_for_point(ax, ay)
        aid_b = _find_area_for_point(bx, by)

        snap_a = _nearest_gate_xy(aid_a, ax, ay) if aid_a else None
        snap_b = _nearest_gate_xy(aid_b, bx, by) if aid_b else None

        if snap_a is not None:
            ga["x"], ga["y"] = float(snap_a[0]), float(snap_a[1])
        if snap_b is not None:
            gb["x"], gb["y"] = float(snap_b[0]), float(snap_b[1])

        c[a_key] = ga
        c[b_key] = gb

    wgl["connections"] = conns

def draw_world(wgl: Dict[str, Any], area_layouts: Dict[str, Any], out_png: str, out_pdf: str) -> None:
    if not HAS_MPL:
        print("[warn] matplotlib not installed; skipping PNG/PDF drawing.")
        return

    areas = wgl.get("areas", {})
    if not areas:
        print("[warn] No areas found in WGL; nothing to draw.")
        return

    # -----------------------------
    # World drawing knobs (env override)
    # -----------------------------
    WORLD_ROAD_ALPHA = float(os.environ.get("WORLD_ROAD_ALPHA", "0.22"))
    WORLD_ROAD_ZORDER = int(os.environ.get("WORLD_ROAD_ZORDER", "1"))

    WORLD_CONN_LW = float(os.environ.get("WORLD_CONN_LW", "4.0"))
    WORLD_CONN_ALPHA = float(os.environ.get("WORLD_CONN_ALPHA", "0.75"))
    WORLD_CONN_ZORDER = int(os.environ.get("WORLD_CONN_ZORDER", "5"))

    # --- Normalize rects once ---
    normed = {}
    for area_id, a in areas.items():
        rect = normalize_rect(a.get("rect", {}))
        a["rect"] = rect
        normed[area_id] = a
    areas = normed

    # --- World bounds (from WGL rects) ---
    xs0, ys0, xs1, ys1 = [], [], [], []
    for a in areas.values():
        r = a["rect"]
        x0, y0, w, h = float(r["x"]), float(r["y"]), float(r["w"]), float(r["h"])
        xs0.append(x0)
        ys0.append(y0)
        xs1.append(x0 + w)
        ys1.append(y0 + h)

    minx = min(xs0)
    miny = min(ys0)
    maxx = max(xs1)
    maxy = max(ys1)

    world_w = max(1e-6, maxx - minx)
    world_h = max(1e-6, maxy - miny)

    # Auto-padding so small-coordinate worlds don't get "tiny/compact"
    pad = max(0.05 * max(world_w, world_h), 0.5)
    print(f"[draw_world] bounds: x=({minx:.2f},{maxx:.2f}) y=({miny:.2f},{maxy:.2f}) pad={pad:.2f}")

    # --- Figure + axis ---
    fig_w = max(8.0, world_w * 0.15)
    fig_h = max(6.0, world_h * 0.15)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=WORLD_DPI)

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(minx - pad, maxx + pad)
    ax.set_ylim(miny - pad, maxy + pad)
    ax.axis("off")

    # --- Draw areas + gates + entities + intra-area roads (world space) ---
    for area_id, a in areas.items():
        rect = a["rect"]
        x0, y0, w, h = float(rect["x"]), float(rect["y"]), float(rect["w"]), float(rect["h"])

        # area box + label
        ax.add_patch(Rectangle((x0, y0), w, h, fill=False, linewidth=2))

        ax.annotate(
            area_id,
            xy=(x0, y0 + h),
            xytext=(4, -4),
            textcoords="offset points",
            ha="left",
            va="top",
            fontsize=10,
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.75, pad=0.3),
            clip_on=True,
        )

        layout = area_layouts.get(area_id, {})
        tiles_val = max(1, int(layout.get("tiles", max(1, int(min(w, h))))))
        tile_size_world = min(w, h) / float(tiles_val)

        # -----------------------------
        # WORLD MAP: intra-area roads (tile -> world)
        # -----------------------------
        roads = layout.get("roads") or {}
        road_tiles = roads.get("road_tiles") or []
        if road_tiles:
            for (tx, ty) in road_tiles:
                rx = x0 + float(tx) * tile_size_world
                ry = y0 + float(ty) * tile_size_world
                ax.add_patch(
                    Rectangle(
                        (rx, ry),
                        tile_size_world,
                        tile_size_world,
                        fill=True,
                        linewidth=0,
                        alpha=WORLD_ROAD_ALPHA,
                        zorder=WORLD_ROAD_ZORDER,
                    )
                )

        # -----------------------------
        # Gates (plot + label)
        # -----------------------------
        for gi, g in enumerate(layout.get("gates", []), start=1):
            gx, gy = float(g["world_x"]), float(g["world_y"])
            ax.plot([gx], [gy], marker="o", markersize=4, zorder=10)

            gate_name = g.get("name") or g.get("id")
            connect_to = g.get("connect_to")
            edge = g.get("edge", "gate")
            if gate_name:
                label = str(gate_name)
            else:
                label = f"{edge}#{gi}"
            if connect_to:
                label = f"{label}→{connect_to}"

            ax.text(
                gx + 0.8,
                gy + 0.8,
                label,
                fontsize=7,
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.75, pad=0.4),
                clip_on=True,
                zorder=11,
            )

        # -----------------------------
        # Entities (boxes only, no labels)
        # -----------------------------
        for _, p in (layout.get("placements") or {}).items():
            ex = x0 + float(p["x"]) * tile_size_world
            ey = y0 + float(p["y"]) * tile_size_world
            ew = float(p["w"]) * tile_size_world
            eh = float(p["h"]) * tile_size_world
            edge_col = "red" if p.get("needs_frontage") else "black"
            ax.add_patch(Rectangle((ex, ey), ew, eh, fill=False, linewidth=1, edgecolor=edge_col, zorder=8))

        # anchor marker if present
        anc = layout.get("anchor_world")
        if anc:
            ax.plot([anc[0]], [anc[1]], marker="x", markersize=5, zorder=12)

    # -----------------------------
    # Inter-area connections (thicker)
    # -----------------------------
    for c in wgl.get("connections", []):
        ga = (c.get("gate_a") or c.get("from_gate") or {})
        gb = (c.get("gate_b") or c.get("to_gate") or {})
        if "x" in ga and "y" in ga and "x" in gb and "y" in gb:
            ax.plot(
                [float(ga["x"]), float(gb["x"])],
                [float(ga["y"]), float(gb["y"])],
                linewidth=WORLD_CONN_LW,
                alpha=WORLD_CONN_ALPHA,
                solid_capstyle="round",
                zorder=WORLD_CONN_ZORDER,
            )

    fig.tight_layout(pad=0.2)
    fig.savefig(out_png, bbox_inches="tight")
    fig.savefig(out_pdf, bbox_inches="tight")
    plt.close(fig)

    # ---- Per-area grid ----
    out_areas_png = os.path.splitext(out_png)[0] + "_areas.png"
    n = max(1, len(area_layouts))
    cols = min(3, n)
    rows = (n + cols - 1) // cols
    fig2, axes = plt.subplots(rows, cols, figsize=(5 * cols, 5 * rows))
    if rows * cols == 1:
        axes = [axes]
    else:
        axes = axes.ravel()

    for i, (aid, ao) in enumerate(area_layouts.items()):
        ax2 = axes[i]
        ts = ao.get("tile_size")
        if ts and isinstance(ts, (list, tuple)) and len(ts) == 2:
            display_tw, display_th = int(ts[0]), int(ts[1])
        else:
            t = ao.get("tiles", 20)
            display_tw, display_th = int(t), int(t)
            ao["tile_size"] = (display_tw, display_th)
        draw_area(ax2, ao, title=f"{aid} ({display_tw}x{display_th})")

    for j in range(len(area_layouts), rows * cols):
        axes[j].axis("off")

    fig2.tight_layout()
    fig2.savefig(out_areas_png, bbox_inches="tight")
    plt.close(fig2)
def build_area_roads(area_layout: dict, blocked_pad: int = 1) -> dict:
    tiles = int(area_layout["tiles"])
    placements = area_layout.get("placements") or {}
    gates = area_layout.get("gates") or []
    anchor = (tiles // 2, tiles // 2)

    # hard vs soft blocking (soft expands by blocked_pad so roads avoid hugging buildings)
    blocked_hard = build_blocked_from_placements(placements, tiles=tiles, pad=0)
    blocked_soft = build_blocked_from_placements(placements, tiles=tiles, pad=int(blocked_pad))
    blocked_hard.discard(anchor)
    blocked_soft.discard(anchor)

    # 1) Slide gates along edges to reachable, non-blocked positions
    gates_opt, gate_terms = optimize_gates_for_roads(
        gates=gates,
        blocked_hard=blocked_hard,
        blocked_soft=blocked_soft,
        tiles=tiles,
        anchor=anchor,
        search_radius_tiles=16,
    )

    # 2) Choose doors for frontage entities
    doors: dict[str, list[int]] = {}
    entity_terms: list[tuple[int, int]] = []
    for ent_id, p in (placements or {}).items():
        if not p.get("needs_frontage"):
            continue
        door = pick_frontage_door(p, blocked_hard=blocked_hard, tiles=tiles, prefer=anchor)
        if door is None:
            continue
        doors[ent_id] = [int(door[0]), int(door[1])]
        entity_terms.append(door)

    # ---- GATES-FIRST ROAD NETWORK ----
    road_tiles: set[tuple[int, int]] = set()
    connected = 0

    # A) Connect gates to each other first (spanning tree)
    gate_network: set[tuple[int, int]] = set()
    if gate_terms:
        gate_network.add(gate_terms[0])
        road_tiles.add(gate_terms[0])

        for t in gate_terms[1:]:
            path = a_star_to_network(
                start=t,
                goals=gate_network,
                blocked_hard=blocked_hard,
                blocked_soft=blocked_soft,
                tiles=tiles,
                road_tiles=road_tiles,
            )
            if path is None:
                # gate couldn't connect; skip (still keep it as a terminal so you can debug)
                continue
            for cell in path:
                road_tiles.add(cell)
            gate_network.add(t)
            connected += 1
    else:
        # no gates: fall back to anchor-only seed
        road_tiles.add(anchor)

    # B) Connect anchor to the gate network (so roads “flow inward”)
    if anchor not in road_tiles:
        path = a_star_to_network(
            start=anchor,
            goals=road_tiles if road_tiles else {anchor},
            blocked_hard=blocked_hard,
            blocked_soft=blocked_soft,
            tiles=tiles,
            road_tiles=road_tiles,
        )
        if path is not None:
            for cell in path:
                road_tiles.add(cell)
            connected += 1
        road_tiles.add(anchor)

    # C) Connect frontage entity doors to the existing road network
    for t in entity_terms:
        path = a_star_to_network(
            start=t,
            goals=road_tiles,
            blocked_hard=blocked_hard,
            blocked_soft=blocked_soft,
            tiles=tiles,
            road_tiles=road_tiles,
        )
        if path is None:
            continue
        for cell in path:
            road_tiles.add(cell)
        connected += 1

    ordered_terms = gate_terms + entity_terms

    return {
        "anchor_tile": [int(anchor[0]), int(anchor[1])],
        "terminals": [[int(x), int(y)] for (x, y) in ordered_terms],
        "doors": doors,
        "road_tiles": [[int(x), int(y)] for (x, y) in sorted(road_tiles)],
        "gates_opt": gates_opt,
        "connected_terminals": int(connected),
        "total_terminals": int(len(ordered_terms) + 1),  # +1 for anchor connect attempt
        "blocked_pad": int(blocked_pad),
    }
def tile_size_world_from_rect(rect: dict, tiles: int) -> float:
    w = float(rect["w"])
    h = float(rect["h"])
    tiles = max(1, int(tiles))
    return min(w, h) / float(tiles)


def entity_tile_rect_to_world(rect: dict, tiles: int, p: dict) -> dict:
    x0, y0 = float(rect["x"]), float(rect["y"])
    ts = tile_size_world_from_rect(rect, tiles)
    pw, ph = float(p["w"]), float(p["h"])
    return {
        "x": x0 + float(p["x"]) * ts,
        "y": y0 + float(p["y"]) * ts,
        "w": pw * ts,
        "h": ph * ts,
        "kind": p.get("kind"),
        "group": p.get("group"),
        "id": p.get("id"),
        "needs_frontage": bool(p.get("needs_frontage", False)),
        "placeable_3d_asset": True,
        "grid_footprint_tiles": {"w": pw, "h": ph},
    }


def tile_xy_to_world_xy(rect: dict, tiles: int, tx: float, ty: float, center: bool = False) -> list[float]:
    x0, y0 = float(rect["x"]), float(rect["y"])
    ts = tile_size_world_from_rect(rect, tiles)
    if center:
        return [x0 + (float(tx) + 0.5) * ts, y0 + (float(ty) + 0.5) * ts]
    return [x0 + float(tx) * ts, y0 + float(ty) * ts]



# -----------------------------
# Main
# -----------------------------

def main() -> None:
    plan = load_json(PLAN_PATH)
    wgl = load_json(WGL_PATH)

    npc_anchor_ids: Set[str] = set()
    for n in plan.get("npcs", []) or []:
        aid = n.get("anchor_id") if isinstance(n, dict) else None
        if aid:
            npc_anchor_ids.add(norm(str(aid)))

    # Ensure connections are split through blocking areas BEFORE we place/optimize gates.
    split_connections_through_areas(wgl)

    areas = wgl.get("areas", {})

    # PLAN/WGL consistency check
    plan_area_ids = []
    raw_plan_areas = plan.get("areas") or plan.get("world_plan", {}).get("areas") or []
    if isinstance(raw_plan_areas, list):
        for a in raw_plan_areas:
            if isinstance(a, dict):
                pid = a.get("id") or a.get("name")
                if pid:
                    plan_area_ids.append(pid)
    elif isinstance(raw_plan_areas, dict):
        plan_area_ids = list(raw_plan_areas.keys())

    overlap = set(plan_area_ids) & set(areas.keys())
    if plan_area_ids and not overlap:
        print("[warn] PLAN and WGL area ids do not overlap; using PLAN areas for visualization.")
        grid_cols = max(1, int(len(plan_area_ids) ** 0.5))
        spacing = 120
        new_areas = {}
        for i, aid in enumerate(plan_area_ids):
            col = i % grid_cols
            row = i // grid_cols
            x0 = col * spacing
            y0 = row * spacing
            new_areas[aid] = {"rect": {"x": x0, "y": y0, "w": 100, "h": 100}, "gates": []}
        areas = new_areas
        wgl["areas"] = areas  # so drawing uses the same

    area_layouts: Dict[str, Any] = {}

    # NEW: self-contained world-space export for Godot / PNG replication
    world_space: Dict[str, Any] = {"areas": {}, "connections": []}

    for area_id, a in areas.items():
        rect = normalize_rect(a.get("rect", {}))
        a["rect"] = rect

        start_tiles = int(round(max(rect["w"], rect["h"])))
        instances, anchor_hint = expand_instances_from_plan(plan, area_id=area_id, area_tiles_hint=start_tiles)

        gates_summary: List[Dict[str, Any]] = []
        for g in a.get("gates", []):
            edge_frac = build_gate_edge_fraction(rect, g)
            gx, gy = gate_pos_from_edge_fraction(rect, edge_frac)
            gates_summary.append(
                {
                    "edge": edge_frac["edge"],
                    "compass": compass_from_gate(rect, (gx, gy)),
                    "connect_to": g.get("connects_to") or g.get("to") or g.get("neighbor") or None,
                }
            )

        intent = get_intent(
            instances=instances,
            area_id=area_id,
            gates_summary=gates_summary,
            npc_anchor_ids=npc_anchor_ids,
        )
        
        # Normalize size_bucket per group: all instances with same group use same size_bucket
        # This ensures consistent footprints across areas (e.g., all "inn" buildings same size)
        intent = normalize_group_sizes(intent, instances)
        
        tiles, placements = grow_until_fit(instances=instances, start_tiles=start_tiles, intent=intent)

        x0, y0, w, h = float(rect["x"]), float(rect["y"]), float(rect["w"]), float(rect["h"])
        tile_size_world = min(w, h) / max(1.0, float(tiles))
        anchor_world = (x0 + (tiles * 0.5) * tile_size_world, y0 + (tiles * 0.5) * tile_size_world)

        # initial gates from WGL (edge+t from world x/y)
        gates_out: List[Dict[str, Any]] = []
        for g in a.get("gates", []):
            edge_frac = build_gate_edge_fraction(rect, g)
            gx, gy = gate_pos_from_edge_fraction(rect, edge_frac)
            gates_out.append(
                {
                    "edge": edge_frac["edge"],
                    "t": edge_frac["t"],
                    "world_x": gx,
                    "world_y": gy,
                    "connect_to": g.get("connects_to") or g.get("to") or g.get("neighbor") or None,
                }
            )

        area_layouts[area_id] = {
            "tiles": tiles,
            "tile_size": (tiles, tiles),
            "anchor_hint": anchor_hint,
            "anchor_world": [anchor_world[0], anchor_world[1]],
            "gates": gates_out,
            "placements": placements,
            "intent": intent,
        }

        # -----------------------------
        # Build roads and slide gates
        # -----------------------------
        roads = build_area_roads(area_layouts[area_id])
        area_layouts[area_id]["roads"] = roads

        # overwrite gates with optimized gate t values (moved gates)
        if roads.get("gates_opt"):
            area_layouts[area_id]["gates"] = roads["gates_opt"]

            # recompute world_x/world_y after t changes
            new_gates_world: List[Dict[str, Any]] = []
            for g in area_layouts[area_id]["gates"]:
                edge = g.get("edge", "top")
                tfrac = float(g.get("t", 0.5))
                gx, gy = gate_pos_from_edge_fraction(rect, {"edge": edge, "t": tfrac})
                g2 = dict(g)
                g2["world_x"] = float(gx)
                g2["world_y"] = float(gy)
                new_gates_world.append(g2)
            area_layouts[area_id]["gates"] = new_gates_world

        # -----------------------------
        # NEW: World-space snapshot (self-contained)
        # -----------------------------
        ts_world = tile_size_world_from_rect(rect, tiles)

        entities_world: Dict[str, Any] = {}
        for ent_id, p in (placements or {}).items():
            entities_world[ent_id] = entity_tile_rect_to_world(rect, tiles, p)

        roads_obj = area_layouts[area_id].get("roads") or {}
        road_tiles = roads_obj.get("road_tiles") or []
        roads_world = [tile_xy_to_world_xy(rect, tiles, tx, ty, center=True) for (tx, ty) in road_tiles]

        gates_world = []
        for g in (area_layouts[area_id].get("gates") or []):
            gates_world.append(
                {
                    "edge": g.get("edge", "top"),
                    "t": float(g.get("t", 0.5)),
                    "world_x": float(g.get("world_x", 0.0)),
                    "world_y": float(g.get("world_y", 0.0)),
                    "connect_to": g.get("connect_to"),
                }
            )

        world_space["areas"][area_id] = {
            "rect": {"x": float(rect["x"]), "y": float(rect["y"]), "w": float(rect["w"]), "h": float(rect["h"])},
            "tiles": int(tiles),
            "tile_size_world": float(ts_world),
            "anchor_world": area_layouts[area_id].get("anchor_world"),
            "gates_world": gates_world,
            "entities_world": entities_world,
            "roads_world": roads_world,
        }

    # Snap WGL's gates + connections to the moved gates so the PNG and exported connections match
    sync_wgl_gates_and_connections(wgl, area_layouts)

    # Export exactly what draw_world uses for inter-area connections (world space)
    conns_world = []
    for c in wgl.get("connections", []) or []:
        ga = (c.get("gate_a") or c.get("from_gate") or {})
        gb = (c.get("gate_b") or c.get("to_gate") or {})
        if "x" in ga and "y" in ga and "x" in gb and "y" in gb:
            conns_world.append({"a": [float(ga["x"]), float(ga["y"])], "b": [float(gb["x"]), float(gb["y"])]})
    world_space["connections"] = conns_world

    out = {
        "meta": {
            "plan_path": PLAN_PATH,
            "wgl_path": WGL_PATH,
            "use_llm": USE_LLM,
            "gemini_model": GEMINI_MODEL if USE_LLM else None,
            "seed": RNG_SEED,
            "entity_padding_tiles": GLOBAL_ENTITY_PADDING_TILES,
            "growth_factor": GROWTH_FACTOR,
        },
        "areas": area_layouts,          # tile-space + intent + debugging
        "world_space": world_space,     # NEW: self-contained snapshot for Godot / PNG replication
    }

    out_dir = os.path.dirname(OUT_PNG)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    save_json(OUT_JSON, out)
    draw_world(wgl=wgl, area_layouts=area_layouts, out_png=OUT_PNG, out_pdf=OUT_PDF)

    print(f"Wrote: {OUT_PNG}")
    print(f"Wrote: {OUT_PDF}")
    print(f"Wrote: {OUT_JSON}")
    print(f"Wrote: {os.path.splitext(OUT_PNG)[0]}_areas.png")

if __name__ == "__main__":
    main()