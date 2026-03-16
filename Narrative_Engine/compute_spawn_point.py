#!/usr/bin/env python3
"""
compute_spawn_point.py

Uses chapter 1 of the narrative spec to decide which area the player should spawn in,
then places the spawn point on the road (gate) closest to that area's anchor/center.
Output: adds "spawn_point" to world_graph_layout.json for use by the 3D map.
"""

import json
import math
import os
from typing import Any, Dict, Optional

import gemini_client as gc


# -------------------------
# Config
# -------------------------

NARRATIVE_SPEC_PATH = os.environ.get("NARRATIVE_SPEC_PATH", "narrative_spec.json")
WORLD_PLAN_PATH = os.environ.get("WORLD_PLAN_PATH", "world_plan.json")
WORLD_GRAPH_LAYOUT_PATH = os.environ.get("WORLD_GRAPH_LAYOUT_PATH", "world_graph_layout.json")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", gc.DEFAULT_MODEL)

SPAWN_AREA_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "spawn_area_id": {
            "type": "string",
            "description": "Area id (snake_case) where the player should spawn at the start of chapter 1",
        },
    },
    "required": ["spawn_area_id"],
}


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)


def get_chapter_1(spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for ch in spec.get("chapters", []):
        if ch.get("id") == "chapter_1":
            return ch
    return None


def build_spawn_area_prompt(spec: Dict[str, Any], world_plan: Dict[str, Any]) -> str:
    """Build prompt for LLM to pick the single area where the player should spawn (chapter 1 start)."""
    ch1 = get_chapter_1(spec)
    if not ch1:
        return ""

    areas = world_plan.get("areas", [])
    area_ids = [a["id"] for a in areas]

    lines = [
        "The player starts the game at the beginning of CHAPTER 1. Choose the ONE area where the player should SPAWN.",
        "Spawn = where the player first appears in the 3D world (on a road at the edge of that area).",
        "",
        "CHAPTER 1:",
        f"  title: {ch1.get('title', '')}",
        f"  narration: {ch1.get('narration', '')}",
        f"  available_anchor_ids: {ch1.get('available_anchor_ids', [])}",
        f"  event_beats (first 3): {ch1.get('event_beats', [])[:3]}",
        "",
        "AREAS (each has entity/anchor ids that belong to this place):",
    ]
    for a in areas:
        eids = [e.get("id") for e in (a.get("entities") or []) if e.get("id")]
        lines.append(f"  - area_id=\"{a['id']}\", narrative=\"{a.get('narrative', '')[:120]}...\", entity_ids={eids}")
    lines.append("")
    lines.append(
        "Pick the single area_id where the story naturally begins (e.g. entrance, crossroads, or the area where the first event happens). "
        "Output JSON with exactly one field: spawn_area_id (must be one of the area ids listed above)."
    )
    return "\n".join(lines)


def call_spawn_area_llm(spec: Dict[str, Any], world_plan: Dict[str, Any], model: str) -> Optional[str]:
    """Return spawn_area_id from LLM, or None on failure."""
    ch1 = get_chapter_1(spec)
    if not ch1:
        return None

    prompt = build_spawn_area_prompt(spec, world_plan)
    if not prompt:
        return None

    system = "Reply with JSON only: {\"spawn_area_id\": \"<area_id>\"}."
    user = prompt + "\n\nSchema: " + json.dumps(SPAWN_AREA_SCHEMA)
    try:
        out = gc.generate_json(system, user, model=model, temperature=0.2)
        if isinstance(out, dict):
            return out.get("spawn_area_id")
    except Exception as e:
        print(f"[warn] Spawn area LLM failed: {e}")
    return None


def fallback_spawn_area(spec: Dict[str, Any], world_plan: Dict[str, Any]) -> str:
    """Pick spawn area by most chapter-1 anchors in an area; else first area."""
    ch1 = get_chapter_1(spec)
    available = set(ch1.get("available_anchor_ids", [])) if ch1 else set()

    # Build anchor_id -> area_id from world_plan
    anchor_to_area: Dict[str, str] = {}
    for a in world_plan.get("areas", []):
        aid = a.get("id", "")
        for e in a.get("entities", []):
            eid = e.get("id")
            if eid:
                anchor_to_area[eid] = aid

    # Count how many chapter-1 anchors each area has
    area_count: Dict[str, int] = {}
    for anchor_id in available:
        area_id = anchor_to_area.get(anchor_id)
        if area_id:
            area_count[area_id] = area_count.get(area_id, 0) + 1

    if area_count:
        best = max(area_count.items(), key=lambda x: x[1])
        return best[0]

    # Default: first area in world_plan
    areas = world_plan.get("areas", [])
    if areas:
        return areas[0].get("id", "")
    return ""


def gate_closest_to_center(layout: Dict[str, Any], area_id: str) -> Optional[Dict[str, Any]]:
    """From layout, get the gate (road endpoint) in this area that is closest to the area center."""
    areas = layout.get("areas", {})
    area = areas.get(area_id)
    if not area:
        return None
    center = area.get("center", {})
    cx = center.get("x", 0.0)
    cy = center.get("y", 0.0)
    gates = area.get("gates", [])
    if not gates:
        return None

    best = None
    best_d = float("inf")
    for g in gates:
        gx = g.get("x", 0.0)
        gy = g.get("y", 0.0)
        d = math.hypot(gx - cx, gy - cy)
        if d < best_d:
            best_d = d
            best = g
    return best


def compute_spawn_point(
    spec: Dict[str, Any],
    world_plan: Dict[str, Any],
    layout: Dict[str, Any],
    use_llm: bool = True,
    model: str = GEMINI_MODEL,
) -> Optional[Dict[str, Any]]:
    """
    Compute spawn_point for the 3D map: on the road closest to the anchor (area center) of the chapter-1 spawn area.
    Returns dict with area_id, x, y, connected_to (optional), or None if layout/chapter missing.
    """
    spawn_area_id = None
    if use_llm:
        spawn_area_id = call_spawn_area_llm(spec, world_plan, model)
    if not spawn_area_id:
        spawn_area_id = fallback_spawn_area(spec, world_plan)
    if not spawn_area_id:
        return None

    gate = gate_closest_to_center(layout, spawn_area_id)
    if not gate:
        return None

    return {
        "area_id": spawn_area_id,
        "x": gate.get("x", 0.0),
        "y": gate.get("y", 0.0),
        "connected_to": gate.get("connected_to"),
        "kind": gate.get("kind", "road"),
    }


def main() -> None:
    output_dir = os.environ.get("OUTPUT_DIR", "output")
    layout_path = os.environ.get("WORLD_GRAPH_LAYOUT") or os.path.join(output_dir, "world_graph_layout.json")
    plan_path = os.environ.get("WORLD_PLAN_PATH") or os.path.join(output_dir, "world_plan.json")
    narrative_path = os.environ.get("NARRATIVE_SPEC_PATH") or NARRATIVE_SPEC_PATH
    if not os.path.isabs(narrative_path):
        narrative_path = os.path.abspath(narrative_path)

    if not os.path.exists(narrative_path):
        print(f"Error: {narrative_path} not found.")
        raise SystemExit(1)
    if not os.path.exists(plan_path):
        print(f"Error: {plan_path} not found. Run narrative_spec_to_world.py first.")
        raise SystemExit(1)
    if not os.path.exists(layout_path):
        print(f"Error: {layout_path} not found. Run world_block_diagram.py first.")
        raise SystemExit(1)

    spec = load_json(narrative_path)
    world_plan = load_json(plan_path)
    layout = load_json(layout_path)

    use_llm = os.environ.get("USE_LLM", "1").strip().lower() in ("1", "true", "yes")
    spawn = compute_spawn_point(spec, world_plan, layout, use_llm=use_llm)
    if not spawn:
        print("[warn] Could not compute spawn point; layout unchanged.")
        return

    layout["spawn_point"] = spawn
    with open(layout_path, "w") as f:
        json.dump(layout, f, indent=2)
    print(f"Saved spawn_point to {layout_path}: area_id={spawn['area_id']} at ({spawn['x']:.3f}, {spawn['y']:.3f})")


if __name__ == "__main__":
    main()
