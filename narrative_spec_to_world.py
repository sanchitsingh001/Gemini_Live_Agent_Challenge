#!/usr/bin/env python3
"""
narrative_spec_to_world.py

Converts narrative_spec.json → world_plan.json + world_graph.json.

- Uses LLM to cluster anchors into 3–5 areas (placement_notes + chapter available_anchor_ids + full chapter context)
- Each area gets narrative-based entities from anchors
- World graph derived from chapter order (placements + connections)
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List

# Add project root for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gemini_client as gc

try:
    from Worldplan import (
        validate_world_graph,
        validate_world_graph_connectivity,
    )
except ImportError:
    validate_world_graph = None
    validate_world_graph_connectivity = None


# -------------------------
# Config
# -------------------------

NARRATIVE_SPEC_PATH = os.environ.get("NARRATIVE_SPEC_PATH", "narrative_spec.json")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
WORLD_PLAN_PATH = os.path.join(OUTPUT_DIR, "world_plan.json")
WORLD_GRAPH_PATH = os.path.join(OUTPUT_DIR, "world_graph.json")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", gc.DEFAULT_MODEL)

# -------------------------
# LLM clustering schema
# -------------------------

# Small props / scatter that must NOT be grid-placeable entities (no benches, flower beds, etc.)
SUPPLEMENTARY_FORBIDDEN_SMALL_PROPS = frozenset([
    "lantern", "lamp", "streetlamp", "street_light", "signpost", "sign_post",
    "barrel", "crate", "cart", "debris", "chandelier", "hanging_lantern", "bench_single",
    "bench", "stone_bench", "flower_bed",
])

# LLM supplementary entities schema (per-area extra buildings/landmarks)
# Each entity is a placeable 3D asset with size_bucket (small+ only; no tiny) and optional count for grouped instances.
SUPPLEMENTARY_ENTITIES_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "supplementary_per_area": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "area_id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                    "entities": {
                        "type": "array",
                        # Keep worlds sparse: allow 0–4 supplementary entities per area.
                        # The prompt further biases toward reuse + higher counts instead of new unique groups.
                        "minItems": 0,
                        "maxItems": 4,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                                "type": {"type": "string"},
                                "tags": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "size_bucket": {
                                    "type": "string",
                                    "enum": ["small", "medium", "large", "huge"],
                                    "description": "Grid footprint; use small or larger so placement looks correct in 3D.",
                                },
                                "count": {
                                    "anyOf": [
                                        {"type": "integer", "minimum": 1, "maximum": 20},
                                        {"type": "null"},
                                    ],
                                    "description": "Number of instances (e.g. 3 for memorial_tree). Null or 1 = single instance.",
                                },
                            },
                            "required": ["id", "type", "tags", "size_bucket"],
                        },
                    },
                },
                "required": ["area_id", "entities"],
            },
        },
    },
    "required": ["supplementary_per_area"],
}

AREA_CLUSTERING_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "areas": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                    "scale_hint": {
                        "type": "string",
                        "enum": ["tiny", "small", "medium", "large", "huge"],
                    },
                    "narrative": {"type": "string"},
                    "anchor_ids": {
                        "type": "array",
                        "items": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                        "minItems": 1,
                    },
                },
                "required": ["id", "scale_hint", "narrative", "anchor_ids"],
            },
        }
    },
    "required": ["areas"],
}


def _extract_tags(desc: str, anchor_type: str) -> List[str]:
    """Extract simple tags from description and type for entity tags."""
    tags = [anchor_type]
    words = re.findall(r"\b[a-z]{4,}\b", (desc or "").lower())
    # Keep a few descriptive words, avoiding common stopwords
    stop = {"with", "the", "that", "this", "from", "into", "some", "more", "very", "have", "been", "were", "their"}
    for w in words:
        if w not in stop and w not in tags and len(tags) < 10:
            tags.append(w)
    return tags[:10]


def anchor_to_entity(anchor: Dict[str, Any]) -> Dict[str, Any]:
    """Convert narrative_spec anchor to world_plan entity (placeable 3D asset with default grid footprint)."""
    eid = anchor["id"]
    return {
        "id": eid,
        "group": eid,  # GLB lookup: one asset per group; count>1 → id_1, id_2 share same group
        "kind": "landmark",
        "type": anchor.get("type", "landmark"),
        "tags": _extract_tags(anchor.get("description", ""), anchor.get("type", "landmark")),
        "count": 1,
        "placeable_3d_asset": True,
        "size_bucket": "medium",
    }


def build_clustering_prompt(spec: Dict[str, Any]) -> str:
    """Build user prompt for LLM area clustering."""
    meta = spec.get("meta", {})
    anchors = spec.get("anchors", [])
    chapters = spec.get("chapters", [])

    lines = [
        "PARTITION the following anchors into 3–5 distinct AREAS. Each area is a NAMED PLACE (e.g. graveyard, village_square, mausoleum_grounds).",
        "",
        "CRITICAL: Group by PLACE, not by type. If the story says the caretaker is in the graveyard and the entrance is the graveyard entrance, put BOTH in the SAME area (e.g. area id = graveyard). Same place = same area.",
        "Use placement_notes and chapter context to infer which anchors belong to the same location (e.g. 'near the entrance', 'in the graveyard' → same area).",
        "Consider: (1) which named place each anchor belongs to, (2) spatial proximity from placement_notes, (3) anchors that appear together per chapter, (4) chapter order and narrative flow.",
        "",
        "META:",
        f"  genre={meta.get('genre', '')}, tone={meta.get('tone', '')}",
        f"  premise: {meta.get('one_sentence_premise', '')[:200]}...",
        "",
        "ANCHORS:",
    ]
    for a in anchors:
        lines.append(f"  - id={a['id']}, type={a.get('type','')}, placement_notes=\"{a.get('placement_notes','')}\"")
    lines.append("")
    lines.append("CHAPTERS (keep all in mind for area construction):")
    for ch in chapters:
        lines.append(f"  - {ch['id']}: {ch.get('title','')}")
        lines.append(f"    narration: {ch.get('narration','')[:150]}...")
        lines.append(f"    available_anchor_ids: {ch.get('available_anchor_ids', [])}")
        lines.append(f"    event_beats: {ch.get('event_beats', [])[:3]}...")
    lines.append("")
    lines.append(
        "Output areas with: id (snake_case PLACE NAME, e.g. graveyard, village_square, tool_shed), scale_hint (tiny|small|medium|large|huge), narrative (short description of this place), anchor_ids (all anchors that belong in this place). Every anchor must appear in exactly one area."
    )
    return "\n".join(lines)


def call_clustering_llm(spec: Dict[str, Any], model: str) -> Dict[str, Any]:
    """Call LLM to cluster anchors into areas."""
    system = (
        "You partition anchors into 3–5 areas for a game world. Each area is a NAMED PLACE (e.g. graveyard, village_square, mausoleum_grounds). "
        "Group by PLACE: if the caretaker is in the graveyard and the entrance is the graveyard entrance, put both in the same area (e.g. id=graveyard). "
        "Use placement_notes to infer location (e.g. 'near the entrance', 'in the graveyard' → same place). "
        "Use chapter available_anchor_ids: anchors that appear together often belong in the same place. "
        "Keep chapter order and narrative flow in mind. Output valid JSON only. Every anchor id must appear in exactly one area. "
        "JSON must match schema with key 'areas' array of {id, scale_hint, narrative, anchor_ids}."
    )
    user = build_clustering_prompt(spec) + "\n\nSchema: " + json.dumps(AREA_CLUSTERING_SCHEMA)[:6000]
    return gc.generate_json(system, user, model=model, temperature=0.3)


def build_supplementary_prompt(spec: Dict[str, Any], world_plan: Dict[str, Any]) -> str:
    """Build prompt for LLM to suggest supplementary entities per area."""
    meta = spec.get("meta", {})
    areas = world_plan.get("areas", [])
    # Soft budget: this is NOT enforced in code; it just steers the model.
    # We keep it low so the whole game ends up with fewer unique asset groups.
    target_total_new_groups = int(os.environ.get("TARGET_TOTAL_SUPPLEMENTARY_GROUPS", "10"))
    lines = [
        "Goal: keep the world sparse and re-usable so the whole game uses fewer unique 3D assets.",
        "",
        "For each area, suggest 0–4 ADDITIONAL entities (buildings, landmarks, structures) that fit the place.",
        f"Across ALL areas combined, try to introduce no more than ~{target_total_new_groups} NEW unique entity ids total. "
        "Prefer REUSING the same entity ids across multiple areas (\"glue\" assets), and prefer using `count`>1 instead of inventing many new ids.",
        "Each entity must be a solid, discrete object that occupies 1+ cells on a 2D square grid.",
        "NO hanging objects (hanging lantern, chandelier), NO paths/trails/roads, NO floating/suspended structures.",
        "Do NOT suggest benches, flower beds, or any small/tiny props. Only solid buildings and large structures that match each area's narrative architecture (e.g. Japanese village → storehouse, shrine wall, wooden gate; European → stone_well, market_cross—never mix regions). No barrels, crates, carts, lanterns, signposts, debris.",
        "Use count when appropriate (e.g. memorial_tree count 3) so the layout can place multiple instances of the same asset.",
        "Each entity is a placeable 3D asset with a 2D grid footprint (use size_bucket: small|medium|large|huge only; no tiny).",
        "Do NOT repeat any existing entity ids.",
        "",
        "VARIETY REQUIREMENTS:",
        "- Each AREA should still feel distinct, but achieve this with small differences and `count`, not by inventing lots of new entity ids.",
        "- It is GOOD to reuse a few \"glue\" entities (e.g. stone_wall, memorial_tree, village_gate) across multiple areas with the SAME id so they share the same 3D asset.",
        "- Only introduce area-unique entities when they are narratively important for that specific place.",
        "",
        f"META: genre={meta.get('genre', '')}, tone={meta.get('tone', '')}",
        f"SETTING (obey for every entity): {(meta.get('visual_setting_lock') or meta.get('intro_premise') or '')[:800]}",
        "",
        "AREAS (with existing entities):",
    ]
    for a in areas:
        area_id = a.get("id", "")
        narrative = a.get("narrative", "")
        scale = a.get("scale_hint", "medium")
        existing = [e.get("id") or e.get("group") for e in (a.get("entities") or [])]
        lines.append(f"  area_id={area_id}, scale={scale}")
        lines.append(f"    narrative: {narrative[:200]}...")
        lines.append(f"    existing_entity_ids: {existing}")
        lines.append("")
    lines.append(
        "Output supplementary_per_area: array of {area_id, entities: [{id, type, tags?, size_bucket?, count?}]}. "
        "id must be snake_case and unique per area. type: building|structure|landmark|natural|etc. "
        "Include 0–4 solid buildings/structures per area (no benches, flower beds, hanging/path/floating, no small props). "
        "size_bucket: small|medium|large|huge. Use count for repeats (e.g. memorial_tree count 3)."
    )
    return "\n".join(lines)


def call_supplementary_entities_llm(
    spec: Dict[str, Any],
    world_plan: Dict[str, Any],
    model: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """Ask LLM to suggest supplementary entities per area. Returns {area_id: [entity, ...]}."""
    system = (
        "You suggest 0–4 supplementary entities per area for a game world. "
        "Bias toward a sparse world with fewer unique 3D assets: reuse the same entity ids across areas and use count>1 when appropriate. "
        "Each entity must fit that area's cultural/architectural setting—do NOT default to European chapel or Gothic forms when the area narrative is non-European. "
        "Each entity must be a solid building or large structure that occupies 1+ cells on a 2D square grid. "
        "Do NOT suggest benches, flower beds, or any small/tiny props. No barrels, crates, carts, lanterns, signposts, debris. "
        "NO hanging objects (hanging lantern, chandelier), NO paths/trails/roads, NO floating or suspended structures. "
        "Use snake_case for ids. Do not duplicate existing entity ids. "
        "Use count when appropriate (e.g. memorial_tree count 3). "
        "Set size_bucket (small|medium|large|huge only; no tiny) for 2D grid footprint. Output valid JSON only."
    )
    user = build_supplementary_prompt(spec, world_plan) + "\n\nSchema: " + json.dumps(SUPPLEMENTARY_ENTITIES_SCHEMA)[:8000]

    try:
        out = gc.generate_json(system, user, model=model, temperature=0.4)
    except Exception as e:
        print(f"[warn] Supplementary entities LLM failed: {e}")
        return {}

    result: Dict[str, List[Dict[str, Any]]] = {}
    for item in out.get("supplementary_per_area", []):
        aid = item.get("area_id", "")
        if aid:
            result[aid] = item.get("entities", [])
    return result


def _supplementary_to_entity(ent: Dict[str, Any]) -> Dict[str, Any]:
    """Convert LLM supplementary entity to world_plan entity format (placeable 3D asset with grid footprint hint)."""
    eid = ent.get("id", "entity")
    etype = ent.get("type", "landmark")
    tags = ent.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    size_bucket = (ent.get("size_bucket") or "").strip().lower()
    if size_bucket not in ("small", "medium", "large", "huge"):
        size_bucket = "small" if size_bucket == "tiny" else "medium"
    count = ent.get("count")
    if count is not None:
        try:
            count = max(1, min(20, int(count)))
        except (TypeError, ValueError):
            count = 1
    else:
        count = 1
    out = {
        "id": eid,
        "group": eid,  # One GLB per group; count>1 → eid_1, eid_2, eid_3 share same group for placement
        "kind": "landmark",
        "type": etype,
        "tags": tags[:10] if tags else [etype],
        "count": count,
        "placeable_3d_asset": True,
        "size_bucket": size_bucket,
    }
    return out


def _is_small_prop_entity(ent: Dict[str, Any]) -> bool:
    """True if entity id/type looks like a forbidden small prop (not a major placeable object)."""
    raw = " ".join([
        str(ent.get("id", "")),
        str(ent.get("type", "")),
    ]).lower()
    return any(p in raw for p in SUPPLEMENTARY_FORBIDDEN_SMALL_PROPS)


def merge_supplementary_entities(
    world_plan: Dict[str, Any],
    supplementary: Dict[str, List[Dict[str, Any]]],
) -> None:
    """Append supplementary entities to each area in world_plan (in-place). No small props."""
    existing_ids: Dict[str, set] = {}
    for a in world_plan.get("areas", []):
        aid = a.get("id", "")
        existing_ids[aid] = {str(e.get("id") or e.get("group", "")).lower() for e in a.get("entities", [])}

    for a in world_plan.get("areas", []):
        aid = a.get("id", "")
        extras = supplementary.get(aid, [])
        entities = list(a.get("entities") or [])
        for ent in extras:
            eid = str(ent.get("id", "")).lower()
            if not eid or eid in existing_ids.get(aid, set()):
                continue
            if _is_small_prop_entity(ent):
                continue
            entities.append(_supplementary_to_entity(ent))
            existing_ids.setdefault(aid, set()).add(eid)
        a["entities"] = entities


# Default supplementary entities (solid buildings/structures only; no benches, flower beds, or tiny props)
_FALLBACK_SUPPLEMENTARY_PER_AREA: List[Dict[str, Any]] = [
    # Graveyard / memorial / somber places
    {
        "id": "weathered_obelisk",
        "type": "landmark",
        "tags": ["obelisk", "memorial", "stone"],
        "size_bucket": "medium",
        "count": 1,
        "themes": ["grave", "cemetery", "memorial", "tomb", "crypt"],
    },
    {
        "id": "family_crypt",
        "type": "structure",
        "tags": ["crypt", "mausoleum", "family"],
        "size_bucket": "medium",
        "count": 1,
        "themes": ["grave", "cemetery", "memorial", "crypt", "mausoleum"],
    },
    {
        "id": "stone_shrine",
        "type": "structure",
        "tags": ["shrine", "stone"],
        "size_bucket": "small",
        "count": 1,
        "themes": ["grave", "cemetery", "memorial", "chapel"],
    },
    # Village squares / markets
    {
        "id": "market_stall",
        "type": "structure",
        "tags": ["market", "stall"],
        "size_bucket": "small",
        "count": 3,
        "themes": ["market", "square", "plaza", "village", "bazaar"],
    },
    {
        "id": "public_notice_board",
        "type": "structure",
        "tags": ["notice", "board"],
        "size_bucket": "small",
        "count": 1,
        "themes": ["square", "plaza", "village", "market"],
    },
    {
        "id": "village_gazebo",
        "type": "structure",
        "tags": ["gazebo", "village"],
        "size_bucket": "medium",
        "count": 1,
        "themes": ["square", "plaza", "village", "park"],
    },
    # Gardens / parks
    {
        "id": "memorial_tree",
        "type": "landmark",
        "tags": ["tree", "memorial"],
        "size_bucket": "medium",
        "count": 1,
        "themes": ["garden", "park", "grove", "cemetery", "forest"],
    },
    {
        "id": "flower_garden_cluster",
        "type": "natural",
        "tags": ["flowers", "garden"],
        "size_bucket": "medium",
        "count": 2,
        "themes": ["garden", "park", "courtyard"],
    },
    {
        "id": "stone_fountain",
        "type": "landmark",
        "tags": ["fountain", "stone"],
        "size_bucket": "medium",
        "count": 1,
        "themes": ["square", "plaza", "garden", "park"],
    },
    # Edges / walls / gates (generic glue)
    {
        "id": "stone_wall",
        "type": "structure",
        "tags": ["wall", "stone"],
        "size_bucket": "large",
        "count": 1,
        "themes": ["grave", "cemetery", "village", "gate", "edge", "perimeter"],
    },
    {
        "id": "village_gate",
        "type": "structure",
        "tags": ["gate", "village"],
        "size_bucket": "large",
        "count": 1,
        "themes": ["village", "gate", "entrance", "road"],
    },
    {
        "id": "stone_guardhouse",
        "type": "structure",
        "tags": ["guardhouse", "stone"],
        "size_bucket": "medium",
        "count": 1,
        "themes": ["village", "gate", "entrance", "fortified"],
    },
]


def _ensure_fallback_supplementary(world_plan: Dict[str, Any]) -> None:
    """Ensure each area has at least 4 supplementary-style entities (anchors + supplementary). Adds defaults if needed."""
    # Keep worlds sparse by default; only ensure a small minimum.
    # Set ENSURE_MIN_ENTITIES_PER_AREA=0 to disable backfill entirely.
    min_entities_per_area = int(os.environ.get("ENSURE_MIN_ENTITIES_PER_AREA", "3"))
    if min_entities_per_area <= 0:
        return
    # Track how often each fallback group is used globally so we can bias toward underused ones.
    global_usage: Dict[str, int] = {}
    for area in world_plan.get("areas", []):
        for e in area.get("entities") or []:
            gid = str(e.get("group") or e.get("id", "")).lower()
            if not gid:
                continue
            for tmpl in _FALLBACK_SUPPLEMENTARY_PER_AREA:
                base_id = str(tmpl.get("id", "")).lower()
                if base_id and gid.endswith(base_id):
                    global_usage[base_id] = global_usage.get(base_id, 0) + 1

    for idx, a in enumerate(world_plan.get("areas", [])):
        entities = a.get("entities") or []
        aid = a.get("id", "")
        narrative = (a.get("narrative") or "").lower()
        # Simple theme tokens from area id + narrative text
        theme_tokens = set(str(aid).lower().split("_"))
        for w in narrative.replace(",", " ").replace(".", " ").split():
            if len(w) >= 4:
                theme_tokens.add(w)

        existing = {str(e.get("id") or e.get("group", "")).lower() for e in entities}
        needed = min_entities_per_area - len(entities)
        if needed <= 0:
            continue

        # Build a candidate list filtered by themes when possible.
        themed: List[Dict[str, Any]] = []
        neutral: List[Dict[str, Any]] = []
        for tmpl in _FALLBACK_SUPPLEMENTARY_PER_AREA:
            base_id = tmpl.get("id", "entity")
            themes = set(str(t).lower() for t in tmpl.get("themes", []))
            if themes and theme_tokens & themes:
                themed.append(tmpl)
            else:
                neutral.append(tmpl)

        # Prefer themed matches, then fall back to neutral ones.
        candidates = themed if themed else neutral
        if not candidates:
            candidates = _FALLBACK_SUPPLEMENTARY_PER_AREA

        # Bias toward globally underused base_ids and rotate per-area so areas don't get identical sets.
        def usage_key(tmpl: Dict[str, Any]) -> tuple:
            base = str(tmpl.get("id", "")).lower()
            return (global_usage.get(base, 0), base)

        sorted_candidates = sorted(candidates, key=usage_key)
        # Rotate candidate list by area index to further diversify
        if sorted_candidates:
            rot = idx % len(sorted_candidates)
            sorted_candidates = sorted_candidates[rot:] + sorted_candidates[:rot]

        for default in sorted_candidates:
            if needed <= 0:
                break
            base_id = default.get("id", "entity")
            base_key = str(base_id).lower()
            eid = f"{aid}_{base_id}"
            if eid.lower() in existing:
                continue
            # One GLB per group; layout expands count into base_id_1, base_id_2, ...
            ent = {
                "id": eid,
                "group": base_id,
                "kind": "landmark",
                "type": default.get("type", "landmark"),
                "tags": default.get("tags", []),
                "count": int(default.get("count", 1)),
                "placeable_3d_asset": True,
                "size_bucket": str(default.get("size_bucket", "medium")),
            }
            entities.append(ent)
            existing.add(eid.lower())
            global_usage[base_key] = global_usage.get(base_key, 0) + 1
            needed -= 1
        a["entities"] = entities


def build_world_plan(spec: Dict[str, Any], clustering: Dict[str, Any]) -> Dict[str, Any]:
    """Build world_plan.json from spec + clustering."""
    anchors_by_id = {a["id"]: a for a in spec.get("anchors", [])}
    npcs = spec.get("npcs", [])
    npc_anchor_ids = {n["anchor_id"] for n in npcs if n.get("anchor_id")}

    areas = []
    for area_def in clustering.get("areas", []):
        area_id = area_def["id"]
        entities = []
        for aid in area_def.get("anchor_ids", []):
            anchor = anchors_by_id.get(aid)
            if not anchor:
                continue
            ent = anchor_to_entity(anchor)
            entities.append(ent)

        areas.append({
            "id": area_id,
            "scale_hint": area_def.get("scale_hint", "medium"),
            "narrative": area_def.get("narrative", ""),
            "entities": entities,
        })

    return {
        "areas": areas,
        "npcs": [{"npc_id": n["id"], "anchor_id": n["anchor_id"]} for n in npcs if n.get("anchor_id")],
    }


def build_world_graph(spec: Dict[str, Any], clustering: Dict[str, Any]) -> Dict[str, Any]:
    """Build world_graph.json from chapter order and area clustering."""
    chapters = spec.get("chapters", [])
    area_defs = {a["id"]: a for a in clustering.get("areas", [])}
    anchor_to_area = {}
    for a in clustering.get("areas", []):
        for aid in a.get("anchor_ids", []):
            anchor_to_area[aid] = a["id"]

    if not area_defs:
        return {
            "center_area_id": "main",
            "placements": [],
            "connections": [],
        }

    # Chapter order: which areas are "primary" for each chapter
    area_ids = list(area_defs.keys())
    center_area_id = area_ids[0]

    # Build connections from chapter flow: consecutive chapters share or connect areas
    seen_areas = set()
    area_order = []
    for ch in chapters:
        anchor_ids = ch.get("available_anchor_ids", [])
        for aid in anchor_ids:
            a = anchor_to_area.get(aid)
            if a and a not in seen_areas:
                seen_areas.add(a)
                area_order.append(a)

    # Ensure all areas are in order (append any missing)
    for aid in area_ids:
        if aid not in area_order:
            area_order.append(aid)

    if area_order and not center_area_id in area_order:
        center_area_id = area_order[0]

    placements = []
    connections = []

    dirs = ["E", "NE", "N", "NW", "W", "SW", "S", "SE"]
    dist_buckets = ["near", "medium", "far"]

    for i, aid in enumerate(area_order):
        if aid == center_area_id:
            continue
        placements.append({
            "area_id": aid,
            "relative_to": "center" if i == 0 else area_order[i - 1],
            "dir": dirs[i % len(dirs)],
            "dist_bucket": dist_buckets[min(i // 2, 2)],
        })

    for i in range(len(area_order) - 1):
        a, b = area_order[i], area_order[i + 1]
        connections.append({
            "from_area_id": a,
            "to_area_id": b,
            "kind": "road",
            "distance": "medium",
        })

    return {
        "center_area_id": center_area_id,
        "placements": placements,
        "connections": connections,
    }


def main() -> None:
    if not os.path.exists(NARRATIVE_SPEC_PATH):
        print(f"Error: {NARRATIVE_SPEC_PATH} not found. Run generate_narrative_spec.py first.")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(NARRATIVE_SPEC_PATH, "r", encoding="utf-8") as f:
        spec = json.load(f)

    print("Clustering anchors into areas (LLM)...")
    clustering = call_clustering_llm(spec, GEMINI_MODEL)
    if not clustering.get("areas"):
        print("Error: LLM returned no areas.")
        sys.exit(1)
    print(f"  -> {len(clustering['areas'])} areas")

    world_plan = build_world_plan(spec, clustering)

    print("Adding supplementary entities per area (LLM)...")
    supplementary = call_supplementary_entities_llm(spec, world_plan, GEMINI_MODEL)
    if supplementary:
        merge_supplementary_entities(world_plan, supplementary)
        total = sum(len(a.get("entities", [])) for a in world_plan.get("areas", []))
        print(f"  -> merged; {total} total entities across areas")
    else:
        print("  -> skipped (LLM failed or returned nothing)")
    # Fallback: ensure every area has at least some supplementary entities (major placeable only)
    _ensure_fallback_supplementary(world_plan)

    world_graph = build_world_graph(spec, clustering)

    area_ids = [a["id"] for a in world_plan["areas"]]
    if validate_world_graph:
        validate_world_graph(world_graph)
    if validate_world_graph_connectivity and world_graph.get("connections"):
        validate_world_graph_connectivity(world_graph, area_ids)

    with open(WORLD_PLAN_PATH, "w", encoding="utf-8") as f:
        json.dump(world_plan, f, indent=2)
    with open(WORLD_GRAPH_PATH, "w", encoding="utf-8") as f:
        json.dump(world_graph, f, indent=2)

    print(f"Saved {WORLD_PLAN_PATH}")
    print(f"Saved {WORLD_GRAPH_PATH}")


if __name__ == "__main__":
    main()
