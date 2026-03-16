#!/usr/bin/env python3
"""
generate_world_graph.py: Generate world_graph.json from world_plan + dialogue.

Loads world_plan.json and dialogue.json, extracts narrative area order from the
dialogue graph, and builds a linear world graph that follows the story flow.
Must work for any story — no hardcoded area or NPC names.
"""

from __future__ import annotations

import json
import os
import sys

# Add project root for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from Worldplan import (
    extract_narrative_area_order,
    make_world_graph,
    validate_world_graph,
    validate_world_graph_connectivity,
)


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main() -> None:
    plan_path = os.environ.get("WORLD_PLAN_PATH", "world_plan.json")
    dialogue_path = os.environ.get("DIALOGUE_PATH", "dialogue.json")
    out_path = os.environ.get("WORLD_GRAPH_PATH", "world_graph.json")

    if not os.path.exists(plan_path):
        print(f"Error: {plan_path} not found. Run Worldplan.py first.")
        sys.exit(1)
    if not os.path.exists(dialogue_path):
        print(f"Error: {dialogue_path} not found. Run DialogueGen.py first.")
        sys.exit(1)

    wp = load_json(plan_path)
    dialogue = load_json(dialogue_path)

    narrative_order = extract_narrative_area_order(dialogue, wp)
    print(f"Narrative area order: {narrative_order}")

    wg = make_world_graph(areas=wp["areas"], narrative_order=narrative_order)

    area_ids = [a["id"] for a in wp["areas"]]
    validate_world_graph(wg)
    validate_world_graph_connectivity(wg, area_ids)

    save_json(wg, out_path)
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()