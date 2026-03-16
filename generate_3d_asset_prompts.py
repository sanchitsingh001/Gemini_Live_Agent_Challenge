#!/usr/bin/env python3
"""
generate_3d_asset_prompts.py

LLM-generated per-entity visual briefs (entity_id → description).
Use with stage_and_export_story.sh: place matching .glb files under STORY_DIR/assets/.

Reads: narrative_spec.json, world_plan.json, world_entity_layout_out.json
Outputs: 3d_asset_prompts.txt, 3d_asset_prompts.json
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import gemini_client as gc


# -------------------------
# Config
# -------------------------

NARRATIVE_SPEC_PATH = os.environ.get("NARRATIVE_SPEC_PATH", "narrative_spec.json")
WORLD_PLAN_PATH = os.environ.get("WORLD_PLAN_PATH", "")
WORLD_ENTITY_LAYOUT_PATH = os.environ.get(
    "WORLD_ENTITY_LAYOUT", os.environ.get("WORLD_ENTITY_LAYOUT_PATH", "")
)
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", gc.DEFAULT_MODEL)

# Strict visual brief rules (modeling / asset staging)
IMAGE_TO_3D_PROMPT_TEMPLATE = (
    "Image for image-to-3D (3D reconstruction) input. Single subject: {subject}. "
    "Stylized cartoon 3D render (toy-like / clay / hand-painted PBR look) with clear depth and volume. Vibrant, full of colors; cartoonish style. "
    "— NOT a 2D illustration, NOT a painting, NOT a flat cutout/billboard, NOT a poster/sign. "
    "Full subject visible, centered, three-quarter view, clean silhouette, coherent 3D form, high material detail. "
    "Pure white background (#FFFFFF) — no environment (no ground/floor line/horizon), no shadows, even studio lighting, sharp focus. "
    "No text/logo/watermark."
)

# NPC character prompt template (standing humanoid, full body)
NPC_IMAGE_TO_3D_TEMPLATE = (
    "Image for image-to-3D (3D reconstruction) input. Single subject: {subject}. "
    "Stylized cartoon 3D character (toy-like / clay / hand-painted PBR look) with clear depth and volume. Vibrant, full of colors; cartoonish style. "
    "Standing humanoid figure, full body visible, neutral standing pose, coherent 3D form. "
    "— NOT a 2D illustration, NOT a painting, NOT a flat cutout/billboard. "
    "Full subject visible, centered, three-quarter view, clean silhouette, high material detail. "
    "Pure white background (#FFFFFF) — no environment (no ground/floor line/horizon), no shadows, even studio lighting, sharp focus. "
    "No text/logo/watermark."
)

ASSET_PROMPTS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "prompts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "entity_id": {"type": "string"},
                    "image_prompt": {
                        "type": "string",
                        "description": "Complete visual brief for the entity (modeling / concept)",
                    },
                },
                "required": ["entity_id", "image_prompt"],
            },
        },
    },
    "required": ["prompts"],
}


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)


def collect_placeable_entities(
    spec: Dict[str, Any],
    world_plan: Dict[str, Any],
    entity_layout: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Collect one entry per unique GROUP for prompt generation (one GLB per group, multiple placements)."""
    anchor_by_id: Dict[str, Dict[str, Any]] = {}
    for a in spec.get("anchors", []):
        aid = a.get("id")
        if aid:
            anchor_by_id[aid] = a

    seen_groups: set = set()
    entities: List[Dict[str, Any]] = []

    def add_entity(group_id: str, eid: str, kind: str, desc: str, tags: list, label: str) -> None:
        if not group_id or group_id in seen_groups:
            return
        seen_groups.add(group_id)
        entities.append({
            "id": group_id,
            "kind": kind,
            "description": desc,
            "tags": tags,
            "label": label or group_id.replace("_", " ").title(),
        })

    # From world_plan (id/group; count>1 → one GLB per group)
    for area in world_plan.get("areas", []):
        for e in area.get("entities", []) or []:
            if not e.get("placeable_3d_asset"):
                continue
            group_id = e.get("group") or e.get("id")
            eid = e.get("id") or group_id
            if not group_id:
                continue
            anchor = anchor_by_id.get(eid, {}) or anchor_by_id.get(group_id, {})
            desc = anchor.get("description", "") or anchor.get("label", "")
            tags = e.get("tags") or []
            kind = e.get("kind") or e.get("type", "landmark")
            add_entity(group_id, eid, kind, desc, tags, anchor.get("label", ""))

    # From world_entity_layout (placements: memorial_tree_1, memorial_tree_2 → group memorial_tree)
    ws = entity_layout.get("world_space") or {}
    for area_id, adata in (ws.get("areas") or entity_layout.get("areas") or {}).items():
        ents = adata.get("entities_world") or {}
        for eid, p in ents.items():
            if not p.get("placeable_3d_asset"):
                continue
            group_id = p.get("group") or eid
            if "_" in group_id and group_id[-1].isdigit():
                base = group_id.rsplit("_", 1)[0]
                if base and not base[-1].isdigit():
                    group_id = base
            anchor = anchor_by_id.get(eid, {}) or anchor_by_id.get(group_id, {})
            desc = anchor.get("description", "") or anchor.get("label", "")
            kind = p.get("kind", "landmark")
            tags = p.get("tags") or []
            add_entity(group_id, eid, kind, desc, tags, anchor.get("label", ""))

    return entities


def collect_npc_entities(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Collect NPCs from narrative_spec for character prompt generation (one GLB per NPC)."""
    npcs: List[Dict[str, Any]] = []
    for n in spec.get("npcs", []) or []:
        npc_id = n.get("id")
        if not npc_id:
            continue
        name = n.get("name", "").strip() or npc_id.replace("_", " ").title()
        role = n.get("role", "").strip()
        vibe = n.get("vibe", "").strip()
        desc = f"{name}"
        if role:
            desc += f", {role}"
        if vibe:
            desc += f", {vibe}"
        npcs.append({
            "id": npc_id,
            "kind": "npc",
            "description": desc,
            "label": name,
            "name": name,
            "role": role,
            "vibe": vibe,
        })
    return npcs


def build_world_style_context(spec: Dict[str, Any], world_plan: Dict[str, Any]) -> str:
    """Extract shared narrative/architectural style so all assets look consistent."""
    meta = spec.get("meta", {})
    genre = meta.get("genre", "")
    tone = meta.get("tone", "")
    premise = (meta.get("one_sentence_premise") or "")[:400]
    intro = (meta.get("intro_premise") or "")[:500]
    lock = (meta.get("visual_setting_lock") or "")[:1200]
    style_parts = [
        "ARCHITECTURE LOCK: Every asset must match this world's region, era, and building tradition. "
        "Do NOT default to European stone church, Gothic, or Victorian unless the setting is explicitly that. "
        "Name materials and forms (e.g. dark timber, tiled roof, vernacular Japanese farm building).",
    ]
    if genre:
        style_parts.append(f"genre: {genre}")
    if tone:
        style_parts.append(f"tone: {tone}")
    if premise:
        style_parts.append(f"setting (premise): {premise}")
    if intro and intro != premise:
        style_parts.append(f"story context: {intro}")
    if lock.strip():
        style_parts.append("plan / place brief (obey for every object and NPC):\n" + lock.strip())
    area_narratives = []
    for a in world_plan.get("areas", []) or []:
        nar = (a.get("narrative") or "").strip()
        if nar:
            area_narratives.append(nar[:220])
    if area_narratives:
        style_parts.append("areas (architecture + vibe): " + "; ".join(area_narratives[:6]))
    return "\n".join(style_parts)


def world_style_to_prefix(world_style: str, max_len: int = 45) -> str:
    """Extract a short style prefix for fallback prompts (e.g. 'traditional Japanese village')."""
    if not world_style or not world_style.strip():
        return ""
    for line in world_style.strip().split("\n"):
        line = line.strip()
        if line.startswith("setting (premise):"):
            s = line.replace("setting (premise):", "").strip()
            words = s.split()[:6]
            prefix = " ".join(words).strip()[:max_len]
            return prefix if prefix else ""
        if line.startswith("setting:"):
            s = line.replace("setting:", "").strip()
            # First 5–6 words as style: "Ancient Japanese village" or "Medieval European town"
            words = s.split()[:6]
            prefix = " ".join(words).strip()[:max_len]
            return prefix if prefix else ""
        if line.startswith("architectural"):
            # "architectural / place style (from areas): ..."
            s = line.split(":", 1)[-1].strip()
            words = s.replace(";", " ").split()[:6]
            return " ".join(words).strip()[:max_len] or ""
    first = (world_style.strip().split("\n")[0] or "").strip()
    return " ".join(first.split()[:5]).strip()[:max_len] or ""


def build_prompts_llm_input(
    entities: List[Dict[str, Any]],
    world_style: str,
) -> str:
    """Build user prompt for LLM to generate image-to-3D prompts."""
    rules = (
        "CRITICAL RULES for each image prompt (for image-to-3D / 3D reconstruction):\n"
        "- Each entity is a solid, discrete object placed on a 2D grid cell—depict a standalone object with a clear footprint (e.g. shed, statue, gate, memorial tree).\n"
        "- Only MAJOR placeable objects. Do NOT depict small props: lanterns, lamps, signposts, barrels, crates, carts, debris.\n"
        "- NO hanging, floating, or elongated path-like subjects. Subject must have a grounded base.\n"
        "- The image MUST look like a stylized CARTOONISH 3D render (toy-like / clay / hand-painted PBR). It must have obvious depth and volume. Vibrant colors and cartoonish aesthetic; avoid dull or desaturated look.\n"
        "- ABSOLUTELY NO 2D illustration/painting/concept art. NO flat cutout/billboard. NO poster/sign, NO single-plane \"cardboard\" object.\n"
        "- Single subject only. Full subject visible, centered, three-quarter view.\n"
        "- Clean silhouette, coherent 3D form, high material detail.\n"
        "- Pure white background (#FFFFFF). NO environment (no ground, floor line, horizon).\n"
        "- NO shadows, even studio lighting, sharp focus.\n"
        "- NO text, logo, or watermark.\n"
        "- Output the COMPLETE prompt string for each entity (ready to send to image gen model)."
    )
    lines = [
        "Generate an image-generation prompt for each placeable 3D asset below.",
        "These briefs guide 3D asset creation or matching custom GLBs to entities.",
        "",
        "CONSISTENCY (CRITICAL): All assets belong to the SAME world. Apply the SAME architectural style, "
        "materials, and visual language to EVERY entity so they look coherent when placed together.",
        "",
    ]
    if world_style.strip():
        lines.extend([
            "SHARED WORLD STYLE (apply to ALL entities):",
            world_style.strip(),
            "",
        ])
    lines.extend([
        rules,
        "",
        "For each entity, produce a single, complete image prompt. The subject MUST reflect the shared world style above "
        "(e.g. if Japanese village: all use stone/wood, traditional forms, consistent materials). "
        "The prompt must start with: 'Image for image-to-3D (3D reconstruction) input. Single subject: ' "
        "and include all the required rules (white background, no environment, etc.).",
        "",
        "ENTITIES:",
    ])
    for e in entities:
        lines.append(
            f"  - entity_id=\"{e['id']}\" | kind={e['kind']} | label=\"{e.get('label', '')}\" | "
            f"description=\"{e.get('description', '')[:200]}\" | tags={e.get('tags', [])}"
        )
    lines.append("")
    lines.append("Output prompts: array of {entity_id, image_prompt} with one entry per entity.")
    return "\n".join(lines)


def build_npc_prompts_llm_input(
    npcs: List[Dict[str, Any]],
    world_style: str,
) -> str:
    """Build user prompt for LLM to generate NPC character image-to-3D prompts."""
    rules = (
        "CRITICAL RULES for each NPC character image prompt (for image-to-3D / 3D reconstruction):\n"
        "- Each NPC is a STANDING HUMANOID CHARACTER—depict a full-body standing figure, not an object or prop.\n"
        "- Standing pose, neutral stance, full body visible from head to feet.\n"
        "- The image MUST look like a stylized CARTOONISH 3D character render (toy-like / clay / hand-painted PBR). Obvious depth and volume. Vibrant colors and cartoonish aesthetic.\n"
        "- ABSOLUTELY NO 2D illustration/painting/concept art. NO flat cutout/billboard.\n"
        "- Single subject only. Full subject visible, centered, three-quarter view.\n"
        "- Clean silhouette, coherent 3D form, high material detail.\n"
        "- Pure white background (#FFFFFF). NO environment (no ground, floor line, horizon).\n"
        "- NO shadows, even studio lighting, sharp focus.\n"
        "- NO text, logo, or watermark.\n"
        "- Output the COMPLETE prompt string for each NPC (ready to send to image gen model)."
    )
    lines = [
        "Generate an image-generation prompt for each NPC character below.",
        "These briefs guide 3D asset creation or matching custom GLBs to entities.",
        "",
        "CONSISTENCY (CRITICAL): All NPCs belong to the SAME narrative world. Apply the SAME character style, "
        "materials, and visual language so they look coherent together.",
        "",
    ]
    if world_style.strip():
        lines.extend([
            "SHARED WORLD STYLE (apply to ALL NPCs):",
            world_style.strip(),
            "",
        ])
    lines.extend([
        rules,
        "",
        "For each NPC, produce a single, complete image prompt describing a standing character that matches their role and vibe. "
        "The prompt must start with: 'Image for image-to-3D (3D reconstruction) input. Single subject: ' "
        "and include all the required rules (white background, no environment, etc.).",
        "",
        "NPCs:",
    ])
    for n in npcs:
        lines.append(
            f"  - entity_id=\"{n['id']}\" | name=\"{n.get('name', '')}\" | role=\"{n.get('role', '')}\" | "
            f"vibe=\"{n.get('vibe', '')}\" | description=\"{n.get('description', '')[:200]}\""
        )
    lines.append("")
    lines.append("Output prompts: array of {entity_id, image_prompt} with one entry per NPC.")
    return "\n".join(lines)


def call_npc_prompts_llm(
    npcs: List[Dict[str, Any]],
    model: str,
    world_style: str = "",
) -> Dict[str, str]:
    """Call LLM to generate NPC character image prompts. Returns {npc_id: image_prompt}."""
    if not npcs:
        return {}
    system = (
        "You generate image prompts for a text-to-image model. "
        "These images feed an image-to-3D reconstruction pipeline. Each entity is an NPC CHARACTER—a standing humanoid figure. "
        "Depict full-body standing characters with neutral pose—NOT objects, NOT props, NOT buildings. "
        "SETTING LOCK: Clothing, hair, age cues, and accessories MUST match the SHARED WORLD STYLE (region + era). "
        "Never dress everyone in generic Western fantasy or Victorian unless the world style says so—e.g. Japanese village → kimono/work clothes/period-appropriate dress, not frock coats or nun habits unless story-appropriate. "
        "CRITICAL STYLE: The image must look like a stylized cartoonish 3D character render (toy-like / clay / hand-painted PBR) with obvious depth and volume. Vibrant colors and cartoonish aesthetic. "
        "DO NOT generate 2D illustrations/paintings/concept art. DO NOT create flat cutouts/billboards. "
        "Each prompt MUST follow strict rules: single subject (standing character), full body visible, centered, three-quarter view, clean silhouette, "
        "pure white background (#FFFFFF), no environment/ground/horizon, no shadows, even studio lighting, sharp focus, no text/logo/watermark. "
        "CRITICAL: All NPCs belong to the same narrative world. Use the SAME character style and visual language so they look coherent together. "
        "Output the complete prompt string for each NPC, including the prefix 'Image for image-to-3D (3D reconstruction) input. Single subject: ' "
        "and the character description (with consistent style), then the rules (white background, no environment, etc.)."
    )
    user = build_npc_prompts_llm_input(npcs, world_style)
    user += "\n\nJSON shape: " + json.dumps(ASSET_PROMPTS_SCHEMA)[:4000]

    try:
        out = gc.generate_json(system, user, model=model, temperature=0.3)
    except Exception as e:
        print(f"[warn] NPC asset prompts LLM failed: {e}")
        return {}

    result: Dict[str, str] = {}
    for item in out.get("prompts", []):
        eid = item.get("entity_id")
        prompt = item.get("image_prompt", "").strip()
        if eid and prompt:
            if "Image for image-to-3D" not in prompt and "image-to-3D" not in prompt:
                prompt = NPC_IMAGE_TO_3D_TEMPLATE.format(subject=prompt)
            result[eid] = prompt
    return result


def fallback_npc_prompt(npc: Dict[str, Any], world_style_prefix: str = "") -> str:
    """Generate a fallback prompt for NPC without LLM."""
    subject = npc.get("description") or npc.get("label") or npc.get("id", "").replace("_", " ")
    if not subject:
        subject = "standing character"
    else:
        subject = f"standing {subject}"
    if world_style_prefix and world_style_prefix.strip():
        subject = f"{world_style_prefix.strip()}, {subject}"
    return NPC_IMAGE_TO_3D_TEMPLATE.format(subject=subject[:250])


def call_prompts_llm(
    entities: List[Dict[str, Any]],
    model: str,
    world_style: str = "",
) -> Dict[str, str]:
    """Call LLM to generate image prompts. Returns {entity_id: image_prompt}."""
    if not entities:
        return {}
    system = (
        "You generate image prompts for a text-to-image model. "
        "These images feed an image-to-3D reconstruction pipeline. Each entity is a solid, grid-placeable object (gate, statue, storehouse, shrine platform, well, etc.). "
        "Depict standalone objects with a grounded base—NO hanging, floating, or path-like elongated subjects. "
        "ARCHITECTURE LOCK: Every object MUST match the SHARED WORLD STYLE—correct region, materials, roof shape, and ornament. "
        "Forbidden wrong defaults: European Gothic church, stone cathedral façade, Victorian shopfront, generic Western cottage—unless the world style explicitly is European. "
        "If the world is Japanese (or any non-Western place), use that vernacular in EVERY prompt (timber, tile, local gate/shrine forms). "
        "CRITICAL STYLE: The image must look like a stylized cartoonish 3D render (toy-like / clay / hand-painted PBR) with obvious depth and volume. Vibrant colors and cartoonish aesthetic; avoid dull or desaturated look. "
        "DO NOT generate 2D illustrations/paintings/concept art. DO NOT create flat cutouts/billboards or poster/sign-like images. "
        "Each prompt MUST follow strict rules: single subject, full visibility, centered, three-quarter view, clean silhouette, realistic proportions, "
        "pure white background (#FFFFFF), no environment/ground/horizon, no shadows, even studio lighting, sharp focus, no text/logo/watermark. "
        "CRITICAL: All entities belong to the same narrative world. Use the SAME architectural style, materials, and visual language "
        "in every subject description so assets look coherent together. "
        "Output the complete prompt string for each entity, including the prefix 'Image for image-to-3D (3D reconstruction) input. Single subject: ' "
        "and the subject description (with consistent style), then the rules (white background, no environment, etc.)."
    )
    user = build_prompts_llm_input(entities, world_style)
    user += "\n\nJSON shape: " + json.dumps(ASSET_PROMPTS_SCHEMA)[:4000]

    try:
        out = gc.generate_json(system, user, model=model, temperature=0.3)
    except Exception as e:
        print(f"[warn] Asset prompts LLM failed: {e}")
        return {}

    result: Dict[str, str] = {}
    for item in out.get("prompts", []):
        eid = item.get("entity_id")
        prompt = item.get("image_prompt", "").strip()
        if eid and prompt:
            # Ensure prompt includes the image-to-3D rules
            if "Image for image-to-3D" not in prompt and "image-to-3D" not in prompt:
                # LLM omitted prefix; wrap subject in template
                prompt = IMAGE_TO_3D_PROMPT_TEMPLATE.format(subject=prompt)
            result[eid] = prompt
    return result


def fallback_prompt(entity: Dict[str, Any], world_style_prefix: str = "") -> str:
    """Generate a fallback prompt without LLM when entity has no LLM-generated prompt."""
    subject = entity.get("description") or entity.get("label") or entity.get("id", "").replace("_", " ")
    if not subject:
        subject = "3D asset"
    if world_style_prefix and world_style_prefix.strip():
        subject = f"{world_style_prefix.strip()}, {subject}"
    return IMAGE_TO_3D_PROMPT_TEMPLATE.format(subject=subject[:250])


def main() -> None:
    wp_path = WORLD_PLAN_PATH or os.path.join(OUTPUT_DIR, "world_plan.json")
    wel_path = (
        WORLD_ENTITY_LAYOUT_PATH
        if WORLD_ENTITY_LAYOUT_PATH
        else os.path.join(OUTPUT_DIR, "world_entity_layout_out.json")
    )

    if not os.path.exists(NARRATIVE_SPEC_PATH):
        print(f"Error: {NARRATIVE_SPEC_PATH} not found")
        return
    if not os.path.exists(wp_path):
        print(f"Error: {wp_path} not found")
        return
    if not os.path.exists(wel_path):
        print(f"Error: {wel_path} not found")
        return

    spec = load_json(NARRATIVE_SPEC_PATH)
    world_plan = load_json(wp_path)
    entity_layout = load_json(wel_path)

    entities = collect_placeable_entities(spec, world_plan, entity_layout)
    npcs = collect_npc_entities(spec)
    if not entities and not npcs:
        print("No placeable entities or NPCs found. Skipping prompt generation.")
        return

    world_style = build_world_style_context(spec, world_plan)
    style_prefix = world_style_to_prefix(world_style)
    if world_style:
        print(f"  Shared world style: {style_prefix or world_style[:80]}...")

    prompts_map: Dict[str, str] = {}

    if entities:
        print(f"Generating image-to-3D prompts for {len(entities)} entities via LLM...")
        prompts_map = call_prompts_llm(entities, GEMINI_MODEL, world_style)
        for e in entities:
            if e["id"] not in prompts_map:
                prompts_map[e["id"]] = fallback_prompt(e, style_prefix)

    if npcs:
        print(f"Generating image-to-3D prompts for {len(npcs)} NPCs via LLM...")
        npc_prompts = call_npc_prompts_llm(npcs, GEMINI_MODEL, world_style)
        for n in npcs:
            if n["id"] not in npc_prompts:
                npc_prompts[n["id"]] = fallback_npc_prompt(n, style_prefix)
        prompts_map.update(npc_prompts)

    def get_entity_prompt(e: Dict[str, Any]) -> str:
        return prompts_map.get(e["id"], fallback_prompt(e, style_prefix))

    def get_npc_prompt(n: Dict[str, Any]) -> str:
        return prompts_map.get(n["id"], fallback_npc_prompt(n, style_prefix))

    # Output 3d_asset_prompts.txt (one line per entity brief)
    txt_path = os.path.join(OUTPUT_DIR, "3d_asset_prompts.txt")
    with open(txt_path, "w") as f:
        for e in entities:
            f.write(get_entity_prompt(e) + "\n")
        for n in npcs:
            f.write(get_npc_prompt(n) + "\n")
    print(f"Wrote {txt_path}")

    # Output 3d_asset_prompts.json (entity_id/npc_id → prompt mapping)
    json_path = os.path.join(OUTPUT_DIR, "3d_asset_prompts.json")
    with open(json_path, "w") as f:
        json.dump(prompts_map, f, indent=2)
    print(f"Wrote {json_path} ({len(prompts_map)} prompts: {len(entities)} entities, {len(npcs)} NPCs)")


if __name__ == "__main__":
    main()
