#!/usr/bin/env python3
"""
build_game_bundle.py

Produces a single game-ready JSON from pipeline output.
Reads: narrative_spec.json, world_graph_layout.json, world_entity_layout_out.json
Outputs: output/<run>/game_bundle.json

Usage:
  OUTPUT_DIR=output/20260218_223200 python3 build_game_bundle.py
  Or: NARRATIVE_SPEC_PATH=... WORLD_GRAPH_LAYOUT=... WORLD_ENTITY_LAYOUT=... OUTPUT_DIR=... python3 build_game_bundle.py
"""

import json
import os

NARRATIVE_SPEC_PATH = os.environ.get("NARRATIVE_SPEC_PATH", "narrative_spec.json")
WORLD_GRAPH_LAYOUT_PATH = os.environ.get(
    "WORLD_GRAPH_LAYOUT", os.environ.get("WORLD_GRAPH_LAYOUT_PATH", "")
)
WORLD_ENTITY_LAYOUT_PATH = os.environ.get(
    "WORLD_ENTITY_LAYOUT", os.environ.get("WORLD_ENTITY_LAYOUT_PATH", "")
)
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output/20260218_223200")


def load_json(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def main() -> None:
    # Resolve paths relative to OUTPUT_DIR when not explicit
    wgl_path = WORLD_GRAPH_LAYOUT_PATH or os.path.join(OUTPUT_DIR, "world_graph_layout.json")
    wel_path = WORLD_ENTITY_LAYOUT_PATH or os.path.join(OUTPUT_DIR, "world_entity_layout_out.json")

    spec = load_json(NARRATIVE_SPEC_PATH)
    wgl = load_json(wgl_path)
    wel = load_json(wel_path)

    anchor_ids = {a["id"] for a in spec.get("anchors", [])}
    ws = wel.get("world_space") or {}
    ws_areas = ws.get("areas") or {}

    # areas: from world_graph_layout.areas (rect, center, gates) + roads_world from world_entity_layout
    areas = {}
    for aid, a in (wgl.get("areas") or {}).items():
        rect = a.get("rect") or {}
        x0 = rect.get("x0", 0)
        y0 = rect.get("y0", 0)
        x1 = rect.get("x1", 0)
        y1 = rect.get("y1", 0)
        area_data = {
            "id": aid,
            "name": a.get("name", aid),
            "rect": {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0},
            "center": a.get("center", {"x": 0, "y": 0}),
            "gates": a.get("gates", []),
        }
        # Add per-area roads from world_entity_layout for Godot road rendering
        if aid in ws_areas:
            roads = ws_areas[aid].get("roads_world", [])
            if roads:
                area_data["roads_world"] = [[float(p[0]), float(p[1])] for p in roads if isinstance(p, (list, tuple)) and len(p) >= 2]
        areas[aid] = area_data

    # connections: road polylines
    connections = []
    for c in wgl.get("connections") or []:
        poly = c.get("polyline") or []
        if poly:
            connections.append({"from": c.get("from"), "to": c.get("to"), "polyline": poly})

    # entities: flat list from world_space.areas.*.entities_world (anchors + supplementary)
    entities = []
    area_data = ws_areas
    entity_anchor_ids = set()
    for area_id, adata in area_data.items():
        ents = adata.get("entities_world") or {}
        for eid, e in ents.items():
            ent_id = e.get("id") or eid
            is_anchor = ent_id in anchor_ids
            entity_anchor_ids.add(ent_id)
            entities.append({
                "id": ent_id,
                "area_id": area_id,
                "x": float(e.get("x", 0)),
                "y": float(e.get("y", 0)),
                "w": float(e.get("w", 0.2)),
                "h": float(e.get("h", 0.2)),
                "kind": e.get("kind", "landmark"),
                # Critical for asset reuse + normalization (e.g. bench_1, bench_2 share group=bench)
                "group": e.get("group", None),
                "is_anchor": is_anchor,
                "anchor_id": ent_id if is_anchor else None,
                "needs_frontage": bool(e.get("needs_frontage", False)),
            })

    # Synthetic entities for NPC/clue anchors missing from layout (e.g. chapel_steps dropped by clustering)
    npcs = spec.get("npcs", [])
    clues = spec.get("clues", [])
    required_anchor_ids = set()
    for n in npcs:
        if n.get("anchor_id"):
            required_anchor_ids.add(n["anchor_id"])
    for c in clues:
        if c.get("anchor_id"):
            required_anchor_ids.add(c["anchor_id"])
    missing_anchor_ids = [aid for aid in required_anchor_ids if aid not in entity_anchor_ids and aid in anchor_ids]
    if missing_anchor_ids:
        spawn_area_id = wgl.get("spawn_point", {}).get("area_id")
        fallback_area_id = spawn_area_id or (list(areas.keys())[0] if areas else None)
        if fallback_area_id and fallback_area_id in areas:
            area_center = areas[fallback_area_id].get("center", {"x": 0, "y": 0})
            cx, cy = float(area_center.get("x", 0)), float(area_center.get("y", 0))
            for i, aid in enumerate(missing_anchor_ids):
                # Offset each synthetic entity slightly to avoid overlap
                offset = 0.15 * (i + 1)
                entities.append({
                    "id": aid,
                    "area_id": fallback_area_id,
                    "x": cx - 0.1 + (offset * 0.7 if i % 2 else -offset * 0.5),
                    "y": cy - 0.1 + (offset * 0.5 if i % 2 else offset * 0.3),
                    "w": 0.2,
                    "h": 0.2,
                    "kind": "landmark",
                    "is_anchor": True,
                    "anchor_id": aid,
                    "needs_frontage": False,
                })
            print(f"  Added {len(missing_anchor_ids)} synthetic anchor(s) for missing NPC/clue locations: {missing_anchor_ids}")

    # spawn_point
    spawn = wgl.get("spawn_point") or {}
    spawn_point = {
        "area_id": spawn.get("area_id"),
        "x": float(spawn.get("x", 0)),
        "y": float(spawn.get("y", 0)),
        "connected_to": spawn.get("connected_to"),
        "kind": spawn.get("kind", "road"),
    }

    # narrative: chapters, clues, npcs, ending
    meta = dict(spec.get("meta") or {})
    ending = spec.get("ending") or {}
    # Start screen title: prefer the story/game title from ending, then meta.title, then premise
    if not meta.get("title") and ending.get("title"):
        meta["title"] = str(ending["title"]).strip()[:80]
    if not meta.get("title"):
        meta["title"] = (meta.get("one_sentence_premise") or "Story")[:80]
    narrative = {
        "chapters": spec.get("chapters", []),
        "clues": spec.get("clues", []),
        "npcs": spec.get("npcs", []),
        "ending": ending,
        "meta": meta,
    }

    # atmosphere: time_of_day (0-24), fog_intensity (0-1); applied once at game start
    atmosphere_spec = meta.get("atmosphere")
    if isinstance(atmosphere_spec, dict):
        atmosphere = {
            "time_of_day": float(atmosphere_spec.get("time_of_day", 12.0)),
            "fog_intensity": float(atmosphere_spec.get("fog_intensity", 0.0)),
        }
        atmosphere["time_of_day"] = max(0.0, min(24.0, atmosphere["time_of_day"]))
        atmosphere["fog_intensity"] = max(0.0, min(1.0, atmosphere["fog_intensity"]))
    else:
        atmosphere = {"time_of_day": 12.0, "fog_intensity": 0.0}
    # sky_path relative to output dir for Godot (load from same dir as game_bundle)
    sky_path = "sky.png"

    bundle = {
        "areas": areas,
        "connections": connections,
        "entities": entities,
        "spawn_point": spawn_point,
        "narrative": narrative,
        "atmosphere": atmosphere,
        "sky_path": sky_path,
    }

    out_path = os.path.join(OUTPUT_DIR, "game_bundle.json")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(bundle, f, indent=2)

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
