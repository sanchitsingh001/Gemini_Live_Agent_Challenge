#!/usr/bin/env python3
"""
generate_entity_model_mappings.py

Builds entity_models.json and npc_models.json for Godot from game_bundle and
3d_asset_prompts. Assumes S3 assets/ keys are named by entity_id (e.g. <entity_id>.glb).
NPCs prefer their own character GLB (npc_id.glb) when available; otherwise fall back to anchor's GLB.

Usage:
  GAME_BUNDLE_PATH=... PROMPTS_JSON_PATH=... OUT_DIR=... python3 generate_entity_model_mappings.py
  Or: --game-bundle /path/to/game_bundle.json --prompts /path/to/3d_asset_prompts.json --out-dir work_dir/generated
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


_INSTANCE_SUFFIX_RE = re.compile(r"^(?P<base>.+)_(?P<n>\d+)$")


def _base_from_instance_id(entity_id: str) -> str:
    """
    If entity ids are expanded like 'bench_1', 'bench_2', return 'bench'.
    Otherwise, return the original id.
    """
    m = _INSTANCE_SUFFIX_RE.match(entity_id)
    return m.group("base") if m else entity_id


def _pick_asset_id_for_entity(
    *,
    entity_id: str,
    group: str | None,
    available_glb_stems: set[str] | None,
) -> str | None:
    """
    Decide which GLB stem to use for an entity.

    Priority (never chooses unrelated assets):
    1) exact entity_id stem (e.g. bench_1.glb)
    2) explicit group stem (e.g. bench.glb)
    3) base stem derived from instance id (bench.glb for bench_1)
    """
    entity_id = str(entity_id)
    group = str(group).strip() if group else ""
    base = _base_from_instance_id(entity_id)

    candidates = [entity_id]
    if group:
        candidates.append(group)
    if base and base not in candidates:
        candidates.append(base)

    if available_glb_stems is None:
        # No on-disk assets dir provided; cannot validate existence.
        # Return first candidate (exact id) and let caller decide whether to map.
        return candidates[0] if candidates else None

    for c in candidates:
        if c in available_glb_stems:
            return c
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate entity_models.json and npc_models.json for Godot")
    parser.add_argument("--game-bundle", default=os.environ.get("GAME_BUNDLE_PATH", ""), help="Path to game_bundle.json")
    parser.add_argument("--prompts", default=os.environ.get("PROMPTS_JSON_PATH", ""), help="Path to 3d_asset_prompts.json (entity_id -> prompt)")
    parser.add_argument("--out-dir", default=os.environ.get("OUT_DIR", ""), help="Output directory for entity_models.json and npc_models.json")
    parser.add_argument("--assets-dir", default=os.environ.get("ASSETS_DIR", ""), help="If set, only map entities that have a .glb in this dir (partial assets)")
    parser.add_argument("--assets-res-path", default="res://generated/assets", help="Godot res path prefix for GLBs")
    args = parser.parse_args()

    bundle_path = Path(args.game_bundle)
    prompts_path = Path(args.prompts)
    out_dir = Path(args.out_dir)
    if not bundle_path.exists():
        raise FileNotFoundError(f"game_bundle not found: {bundle_path}")
    if not prompts_path.exists():
        raise FileNotFoundError(f"3d_asset_prompts not found: {prompts_path}")
    if not args.out_dir:
        raise ValueError("set --out-dir or OUT_DIR")

    with open(bundle_path, "r") as f:
        bundle = json.load(f)
    with open(prompts_path, "r") as f:
        prompts_map = json.load(f)

    # Prompts are keyed by group (one prompt per group, e.g. memorial_tree → one GLB, multiple placements)
    all_prompt_entity_ids = set(prompts_map.keys()) if isinstance(prompts_map, dict) else set()

    # If --assets-dir given, only map entities that actually have a .glb (partial assets support)
    available_glb_stems: set[str] | None = None
    if args.assets_dir and Path(args.assets_dir).is_dir():
        assets_dir = Path(args.assets_dir)
        available_glb_stems = {f.stem for f in assets_dir.iterdir() if f.suffix.lower() == ".glb"}

    entities = bundle.get("entities", [])
    entity_id_to_group: dict[str, str] = {}
    for e in entities:
        if isinstance(e, dict) and e.get("id"):
            entity_id_to_group[str(e["id"])] = str(e.get("group") or "").strip()
    entity_models = {}
    for e in entities:
        eid = e.get("id")
        if not eid:
            continue
        eid = str(eid)
        group = entity_id_to_group.get(eid, "") or ""
        # Map if this placement's id or its group has a prompt (one GLB per group, multiple placements)
        if eid not in all_prompt_entity_ids and not (group and group in all_prompt_entity_ids):
            continue

        asset_id = _pick_asset_id_for_entity(
            entity_id=eid,
            group=group,
            available_glb_stems=available_glb_stems,
        )
        if asset_id is None:
            continue
        # If we have an assets dir, ensure the chosen GLB exists.
        if available_glb_stems is not None and asset_id not in available_glb_stems:
            continue
        entity_models[eid] = f"{args.assets_res_path}/{asset_id}.glb"

    npcs = (bundle.get("narrative") or {}).get("npcs", [])
    npc_models = {}
    for n in npcs:
        if not isinstance(n, dict):
            continue
        npc_id = n.get("id")
        anchor_id = n.get("anchor_id")
        if not npc_id:
            continue
        npc_id = str(npc_id)
        # Prefer NPC-specific character GLB (npc_id) over anchor's GLB; fall back to anchor if no NPC model.
        chosen: str | None = None
        chosen = _pick_asset_id_for_entity(
            entity_id=npc_id,
            group="",
            available_glb_stems=available_glb_stems,
        )
        if chosen is None and anchor_id:
            aid = str(anchor_id)
            chosen = _pick_asset_id_for_entity(
                entity_id=aid,
                group=entity_id_to_group.get(aid, ""),
                available_glb_stems=available_glb_stems,
            )
        if chosen is None:
            continue
        if available_glb_stems is not None and chosen not in available_glb_stems:
            continue
        npc_models[npc_id] = f"{args.assets_res_path}/{chosen}.glb"

    out_dir.mkdir(parents=True, exist_ok=True)
    entity_models_path = out_dir / "entity_models.json"
    npc_models_path = out_dir / "npc_models.json"
    with open(entity_models_path, "w") as f:
        json.dump(entity_models, f, indent=2)
    with open(npc_models_path, "w") as f:
        json.dump(npc_models, f, indent=2)
    print(f"Wrote {entity_models_path} ({len(entity_models)} entities), {npc_models_path} ({len(npc_models)} NPCs).")


if __name__ == "__main__":
    main()
