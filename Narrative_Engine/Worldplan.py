from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
import gemini_client as gc

# -------------------------
# 1) JSON Schemas (strict)
# -------------------------
WORLDPLAN_SCHEMA: Dict[str, Any] = {
    "name": "world_plan_v2",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "areas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                        "scale_hint": {"type": "string", "enum": ["tiny", "small", "medium", "large", "huge"]},
                        "narrative": {"type": "string", "description": "Architectural vibe and building styles for 3D asset generation"},
                        "entities": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                                    "kind": {"type": "string", "enum": ["building", "landmark"]},
                                    "type": {"type": "string"},
                                    "tags": {"type": "array", "items": {"type": "string"}},
                                    "count": {"anyOf": [{"type": "integer"}, {"type": "null"}]}
                                },
                                "required": ["id", "kind", "type", "tags", "count"]
                            }
                        }
                    },
                    "required": ["id", "scale_hint", "narrative", "entities"]
                }
            }
        },
        "required": ["areas"]
    }
}

# New Schema for Step 1: Area Narratives
AREA_NARRATIVE_SCHEMA: Dict[str, Any] = {
    "name": "area_narratives",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "areas": {
                "type": "array",
                "minItems": 3,
                "maxItems": 7,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                        "scale_hint": {
                            "type": "string",
                            "enum": ["tiny", "small", "medium", "large", "huge"]
                        },
                        "narrative": {
                            "type": "string",
                            "description": "Architectural vibe, building materials, construction styles, and structural elements for 3D asset generation."
                        }
                    },
                    "required": ["id", "scale_hint", "narrative"]
                }
            }
        },
        "required": ["areas"]
    }
}

# New Schema for Step 2: Specific Entities per Area
AREA_ENTITIES_SCHEMA: Dict[str, Any] = {
    "name": "area_entities",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "entities": {
                "type": "array",
                "minItems": 3,
                "maxItems": 60,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {
                            "type": "string",
                            "pattern": "^[a-z0-9_]+$",
                            "description": "Unique snake_case ID for this entity group (e.g. 'sweet_shop', 'banyan_tree')"
                        },
                        "kind": {
                            "type": "string",
                            "enum": ["building", "landmark"]
                        },
                        "type": {
                            "type": "string",
                            "description": "Specific type (e.g. 'bangle_shop', 'haveli', 'shrine')"
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 10,
                            "description": "Architectural tags: materials, construction style, structural elements"
                        },
                        "count": {
                            "anyOf": [
                                {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 500
                                },
                                {"type": "null"}
                            ]
                        }
                    },
                    "required": ["id", "kind", "type", "tags", "count"]
                }
            }
        },
        "required": ["entities"]
    }
}

# NPC anchor planning: 4-8 NPCs, each with exactly one anchor entity in an existing outdoor area
NPC_PLAN_SCHEMA: Dict[str, Any] = {
    "name": "npc_plan",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "npcs": {
                "type": "array",
                "minItems": 4,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "npc_id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                        "display_name": {"type": "string"},
                        "area_id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                        "anchor_entity": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                                "kind": {"type": "string", "enum": ["building", "landmark"]},
                                "type": {"type": "string"},
                                "tags": {"type": "array", "items": {"type": "string"}}
                            },
                            "required": ["id", "kind", "type", "tags"]
                        },
                        "dialogue_seed": {"type": "string"},
                        "description": {"type": "string"}
                    },
                    "required": ["npc_id", "display_name", "area_id", "anchor_entity", "dialogue_seed", "description"]
                }
            }
        },
        "required": ["npcs"]
    }
}

AREALAYOUT_SCHEMA: Dict[str, Any] = {
    "name": "area_layout_v2",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "area_id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
            "anchor": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                    "at": {"type": "string", "enum": ["center"]},
                },
                "required": ["id", "at"],
            },
            "placements": {
                "type": "array",
                "minItems": 0,
                "maxItems": 500,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                        "relative_to": {"type": "string", "pattern": "^[a-z0-9_]+$|^center$"},
                        "dir": {"type": "string", "enum": ["N","NE","E","SE","S","SW","W","NW"]},
                        "dist_bucket": {"type": "string", "enum": ["near","medium","far"]},
                        "priority": {"type": "integer", "minimum": 0, "maximum": 10},
                        "kind": {
                            "type": "string",
                            "enum": ["building", "landmark", "nature", "water", "prop"]
                        },
                        "district": {
                            "type": "string",
                            "enum": ["residential", "market", "industrial", "religious", "civic", "wild", "waterfront"]
                        },
                        "size_hint": {
                            "type": "string",
                            "enum": ["tiny", "small", "medium", "large", "huge"]
                        },
                        "needs_frontage": {"type": "boolean"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 10
                        }
                    },
                    "required": ["id", "relative_to", "dir", "dist_bucket", "priority", "kind", "district", "size_hint", "needs_frontage", "tags"],
                },
            },
            "gates": {
                "type": "array",
                "minItems": 0,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                        "edge": {"type": "string", "enum": ["N","S","E","W"]},
                    },
                    "required": ["id", "edge"],
                },
            },
            "paths": {
                "type": "array",
                "minItems": 0,
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "from": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                        "to": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                        "kind": {"type": "string", "enum": ["footpath", "road"]},
                    },
                    "required": ["from", "to", "kind"],
                },
            },
            "meta": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "area_type": {
                        "type": "string",
                        "enum": ["town", "village", "forest", "marsh", "ruins", "dungeon", "lake", "coast", "mountain", "cave"]
                    },
                    "road_style": {
                        "type": "string",
                        "enum": ["grid", "organic", "trails", "none"]
                    },
                    "map_size_hint": {
                        "type": "string",
                        "enum": ["tiny", "small", "medium", "large", "huge"]
                    },
                    "mood": {"type": "string"}
                },
                "required": ["area_type", "road_style", "map_size_hint", "mood"],
            },
            "road_plan": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "center_id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                    "center": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                            "type": {"type": "string"},
                            "relative_to": {"type": "string", "pattern": "^[a-z0-9_]+$|^anchor$"},
                            "radius_hint": {"type": "string", "enum": ["tiny", "small", "medium", "large"]}
                        },
                        "required": ["id", "type", "relative_to", "radius_hint"],
                    },
                    "main_connectivity": {
                        "type": "array",
                        "minItems": 0,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "from": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                                "to": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                                "kind": {"type": "string", "enum": ["trunk_road", "road", "footpath"]}
                            },
                            "required": ["from", "to", "kind"],
                        },
                    },
                    "branching": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "count_hint": {"type": "string", "enum": ["low", "medium", "high"]},
                            "length_hint": {"type": "string", "enum": ["low", "medium", "high"]}
                        },
                        "required": ["count_hint", "length_hint"],
                    },
                },
                "required": ["center_id", "center", "main_connectivity", "branching"],
            },
            "poi_plan": {
                "type": "array",
                "minItems": 0,
                "maxItems": 30,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                        "category": {
                            "type": "string",
                            "enum": ["structure", "landmark", "npc", "prop"]
                        },
                        "kind": {
                            "type": "string",
                            "enum": ["building", "landmark", "nature", "water", "prop"]
                        },
                        "district": {
                            "type": "string",
                            "enum": ["residential", "market", "industrial", "religious", "civic", "wild", "waterfront"]
                        },
                        "size_hint": {
                            "type": "string",
                            "enum": ["tiny", "small", "medium", "large", "huge"]
                        },
                        "needs_frontage": {"type": "boolean"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 10
                        },
                        "story_role": {"type": "string"},
                        "must_place": {"type": "boolean"},
                        "must_connect": {"type": "boolean"},
                        "near": {
                            "anyOf": [
                                {"type": "array", "items": {"type": "string", "pattern": "^[a-z0-9_]+$"}},
                                {"type": "null"}
                            ]
                        },
                        "far_from": {
                            "anyOf": [
                                {"type": "array", "items": {"type": "string", "pattern": "^[a-z0-9_]+$"}},
                                {"type": "null"}
                            ]
                        },
                        "zone_preference": {
                            "anyOf": [
                                {"type": "string", "enum": ["center", "edge", "waterfront", "high_ground"]},
                                {"type": "null"}
                            ]
                        },
                        "reachable_from": {
                            "anyOf": [
                                {"type": "array", "items": {"type": "string", "pattern": "^[a-z0-9_]+$"}},
                                {"type": "null"}
                            ]
                        }
                    },
                    # IMPORTANT: required must include ALL properties
                    "required": ["id", "category", "kind", "district", "size_hint", "needs_frontage", "tags", "story_role", "must_place", "must_connect", "near", "far_from", "zone_preference", "reachable_from"],
                },
            },
        },
        "required": ["area_id", "anchor", "placements", "gates", "paths", "meta", "road_plan", "poi_plan"],
    },
}

WORLD_GRAPH_SCHEMA: Dict[str, Any] = {
    "name": "world_graph_v1",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "center_area_id": {
                "type": "string",
                "pattern": "^[a-z0-9_]+$"
            },
            "placements": {
                "type": "array",
                "minItems": 0,
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "area_id": {
                            "type": "string",
                            "pattern": "^[a-z0-9_]+$"
                        },
                        "relative_to": {
                            "type": "string",
                            "pattern": "^[a-z0-9_]+$|^center$"
                        },
                        "dir": {
                            "type": "string",
                            "enum": ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
                        },
                        "dist_bucket": {
                            "type": "string",
                            "enum": ["near", "medium", "far"]
                        }
                    },
                    "required": ["area_id", "relative_to", "dir", "dist_bucket"]
                }
            },
            "connections": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "from_area_id": {
                            "type": "string",
                            "pattern": "^[a-z0-9_]+$"
                        },
                        "to_area_id": {
                            "type": "string",
                            "pattern": "^[a-z0-9_]+$"
                        },
                        "kind": {
                            "type": "string",
                            "enum": ["trunk_road", "road", "footpath"]
                        },
                        "distance": {
                            "type": "string",
                            "enum": ["near", "medium", "far"],
                            "description": "Distance between the connected areas"
                        }
                    },
                    "required": ["from_area_id", "to_area_id", "kind", "distance"]
                }
            }
        },
        "required": ["center_area_id", "placements", "connections"]
    }
}

# -------------------------
# 2) Prompts
# -------------------------

AREA_NARRATIVE_INSTRUCTIONS = """\
You are a creative world planner for a procedural map generator.

Step 1: Plan the areas.
Based on the story, identify 3-7 distinct areas.
- Treat areas as abstract locations, not specific moments in time.
- Do NOT create separate areas that are only distinguished by time-of-day, weather, or other transient state (e.g. "town_square_day" vs "town_square_night").
- Instead, describe such changes in the area's narrative and tags as possible states of the SAME area.

CRITICAL: ALL AREAS ARE OUTDOOR SPACES ONLY
- Every area represents an EXTERIOR/OUTDOOR location on the game map
- Do NOT create indoor areas like "cathedral_interior", "shop_interior", "throne_room", "bedroom", etc.
- Focus on outdoor spaces: village centers, market squares, courtyards, forests, fields, streets, plazas, etc.
- Buildings should be described from the OUTSIDE only (their exterior architecture)

For each area:
- Provide a unique ID (snake_case).
- Assign a scale.
- Write a `narrative`: Focus on ARCHITECTURAL VIBE and BUILDING STYLES to help 3D asset generators create appropriate structures.
  - CRITICAL: Describe the architectural style, building materials, construction methods, and structural elements.
  - Examples of good architectural descriptions:
    * "Tightly packed stone cottages with steep thatched roofs and timber-framed walls"
    * "Gothic cathedral with flying buttresses, pointed arches, and carved stonework"
    * "Traditional Japanese wooden buildings with curved tile roofs and paper screen doors"
    * "Adobe structures with flat roofs and wooden vigas in Southwestern style"
  - Describe building EXTERIORS: facades, roof styles, materials (stone, wood, brick, adobe, etc.)
  - Mention architectural details: arches, columns, windows, doors, decorative elements
  - If it's a market, describe the stall construction (wooden frames, canvas awnings, etc.)
  - If it's a forest, describe natural structures (tree types, stone formations, ruins architecture)
  - Include atmosphere and story context, but PRIORITIZE architectural descriptions
  - Remember: You're describing what players see from OUTSIDE, walking through the area

Goal: Create narratives that give 3D asset generators clear guidance on what architectural styles and building types to create for each OUTDOOR area, adaptable to any cultural setting (Indian, Japanese, Western, Medieval, Futuristic, etc.).
"""

AREA_ENTITIES_INSTRUCTIONS  = """\
You are a detail-oriented level designer populating an area for a tile/grid-based map compiler.

Step 2: Generate ONLY "solid footprint" entities for this area.

AREA-NARRATIVE CONSTRAINT (CRITICAL):
- Generate ONLY buildings and landmarks that belong to THIS area's narrative.
- Do NOT include buildings or landmarks that are specific to OTHER areas (e.g. do not put a school building in the village center, or a bakery in the old man's area).
- If the story mentions a school, bakery, or other named location, that building type should appear only in the area that corresponds to that location.
- You MAY include generic filler buildings that match THIS area's architectural style and scale.

CRITICAL HARD CONSTRAINTS (MUST FOLLOW):
1) NO SCATTER AT ALL.
   - Do NOT output kind="scatter".
   - Do NOT output small props like barrels, crates, carts, lanterns, benches, signposts, debris, etc.
   - Every entity must be a major placeable object.

2) EVERY ENTITY MUST BE A SINGLE RECTANGULAR GRID FOOTPRINT OBJECT.
   - The engine will assign a solid square/rect grid area to each entity.
   - Therefore each entity must make sense as one solid footprint (like a building exterior or a single landmark).
   - No “patches”, “fields”, “lines”, “segments”, “rows”, “clusters”, or “areas”.

3) NOTHING MAY BE A ROAD/PATH FEATURE OR PLACED “ON THE ROAD”.
   - FORBIDDEN entity types include: road, street, path, alley, bridge, wall, fence_line, canal, river, stream, ditch, staircase, sidewalk, plaza_floor, market_street, boulevard, lane.
   - Do NOT create “gate tile” obstacles. Gates are handled by the compiler at area boundaries.
   - Roads are generated separately and must remain unobstructed.

4) OUTDOOR ONLY.
   - No indoor objects, no furniture, no interior decorations.
   - No NPCs, animals, vehicles, weather/sound effects.

WHAT YOU MAY OUTPUT:
- kind="building": exterior-only structures with solid footprints
  Examples: stone_house, timber_shop, warehouse, inn_exterior, temple_exterior, chapel_exterior, gatehouse_exterior
- kind="landmark": a single large landmark object with a solid footprint
  Examples: fountain, statue, obelisk, shrine, well, monument, large_tree_as_landmark (ONLY if it’s a single landmark object)

ENTITY GUIDELINES:
- BE SPECIFIC: do not say "shop" — say "tea_shop_exterior", "bangle_shop_exterior", "blacksmith_forge_exterior".
- Use `count` for repeated buildings/landmarks.
- Prefer buildings that create frontage naturally (shops, homes, warehouses) and a few landmarks for identity.

ARCHITECTURAL TAG REQUIREMENTS:
- Each entity.tags MUST describe materials + construction + exterior features.
- For buildings, include tags like: stone_walls, brick, timber_frame, plaster, carved_doorway, arched_windows, thatched_roof, tile_roof, slate_roof, buttresses, columns, weathered, chinese style, medivial style, indian style, japanese style, etc
- For buildings, in the tags also include style_profile: gothic, baroque, medieval_european_village, feudal_japanese_village, islamic_medieval_city, hindu_temple_traditional etc.
- For landmarks: carved_stone, stone_pedestal, bronze, ornate, cracked, mossy, etc.

Return ONLY JSON matching the schema.
"""

NPC_PLAN_INSTRUCTIONS = """\
You are an NPC anchor planner for a procedural world. Output ONLY valid JSON matching the provided schema (no commentary).

Input: (1) An enhanced story overview (string). (2) A list of areas, each with id (snake_case), narrative, and scale_hint.

Constraints:
- Produce 4 to 8 NPCs. Each NPC has exactly one anchor_entity.
- area_id must be one of the given area IDs. Do NOT create new areas.
- anchor_entity must be a placeable exterior: a building or landmark that can exist in an outdoor area (exterior structure, landmark, or outdoor prop). Use kind "building" or "landmark" only.
- All areas are OUTDOOR only. If the story includes interior scenes, describe them only as "seen through windows/doors" or leave for dialogue/NARRATOR later. Do not introduce interior areas or indoor-only anchors.

For each NPC provide: npc_id (snake_case), display_name, area_id (matching an area from the list), anchor_entity (id, kind, type, tags), dialogue_seed (short narrative seed for later dialogue), and description.

DESCRIPTION (for 3D assets): Visual, concrete brief for character meshes / GLBs (modeling or staging). Must read like an art direction line, not plot summary.
- Must match the story's region and era: clothing and grooming appropriate to THAT setting (e.g. Japanese village → period-appropriate work clothes or kimono; do NOT default to Victorian frock coats or European peasant dress unless the area narrative is European).
- Always include the character's role or type as a clear keyword so the 3D model generates the right archetype: e.g. village elder, shopkeeper, child, shrine attendant, etc.
- In 2–4 sentences describe: (1) role/type keyword, (2) clothing and key visual traits tied to the setting, (3) age/build if relevant. Pose must always be standing only.
- Examples (setting-specific): "Elderly woman, rice farmer; indigo work clothes, straw hat; weathered hands, standing." "Young shrine attendant; simple hakama-style work wear; solemn, standing." "Shopkeeper, middle-aged; layered kimono-style merchant dress; standing."

Return ONLY JSON that matches the provided JSON schema (strict).
"""

AREALAYOUT_INSTRUCTIONS = """\
You are a spatial layout planner for ONE area that will be compiled into a tilemap.

Return ONLY JSON that matches the provided JSON schema (strict).
Do NOT output absolute coordinates. Output high-level intent that a deterministic compiler can convert to a playable map.

Core Layout Rules:
- CRITICAL: Only place individual, concrete entities that can be positioned on a tilemap. Do NOT place abstract concepts like "street", "noise", "atmosphere", or clusters. Every placement must represent a single physical object that can be rendered.
- Choose one anchor entity (prefer a central landmark if present); anchor.at must be "center".
- Create one placement entry for EACH instance of each entity.
- IMPORTANT: Generate one placement entry for EACH building instance
- A town with 15 houses needs 15 separate placement entries
- Do NOT consolidate buildings - each one needs its own position
- Instance naming: Use the EXACT entity group ID from the entity list + _N for numbered instances.
  - Examples: if entity id is "desks", use "desks_1", "desks_2", not "desk_1"
  - For entities with count > 1: use entity_id_1, entity_id_2, etc. where entity_id is the exact group ID
  - For entities with count = 1 or count = null: use the entity_id directly (no _1 suffix)
- Each placement must specify:
  - id (instance ID)
  - relative_to (anchor or another instance)
  - dir (N/NE/E/SE/S/SW/W/NW)
  - dist_bucket (near/medium/far)
  - priority (0-10)
  - kind (building/landmark/nature/water/prop)
  - district (residential/market/industrial/religious/civic/wild/waterfront)
  - size_hint (tiny/small/medium/large/huge)
  - needs_frontage (true/false)
  - tags (list of strings)
- SIZE GUIDELINES:
  - Castle/Fortress/Cathedral: size_hint = "huge"
  - Manor/Temple/Market Hall: size_hint = "large"
  - House/Shop/Barn: size_hint = "small" or "medium"
  - Shack/Stall/Shrine: size_hint = "tiny"
- CRITICAL: Only generate OUTDOOR entities. Do NOT generate indoor items such as desks, chairs, tables, school furniture, classroom items, indoor decorations, or any furniture/props that belong inside buildings. All entities must be suitable for placement in an outdoor tilemap environment (streets, plazas, courtyards, forests, etc.).
- IMPORTANT: Exclude indoor props. Only place outdoor items (fountains, benches, streetlamps, carts, debris, outdoor shrines, outdoor statues, trees, rocks, outdoor seating).
- STRICTLY FORBIDDEN: Do NOT generate NPCs, characters, animals, weather effects, lighting effects, sounds, or indoor furniture/props.
- Self-referential placements are forbidden: a placement's id must NOT equal its relative_to.
- Ensure the relative_to graph is a DAG rooted at anchor/center; do not create cycles. Prefer anchoring buildings to anchor/center.
- Paths must reference ONLY entity instance IDs from this area's placements.
- Gates are no longer explicitly defined or placed on edges here; the compiler will automatically determine entry/exit points (gates) at the nearest boundaries between connected areas.
- The area remains a "geometric island" that expects roads to enter/exit from its boundary.
- Do NOT output "gates" array or "edge" specifications.

Roadside Props and Frontage Rules:
- Any placement that is a roadside prop (identified by id/type/tags containing "lamp", "lantern", "streetlamp", "signpost", "street_light", "streetlight", "bench", "signboard") MUST have `needs_frontage = true`.
- Roadside props' `relative_to` must point to an entity with `needs_frontage = true` (a building facade, plaza/center, or explicit road-front node), not to a random tree or back-of-lot prop.
- Suggest placement patterns like flanking both sides of a shop entrance or lining short segments of road between center and gates.

Anti‑clustering and diversity rules (important for later road generation):
- CRITICAL: Entities must be SPATIALLY DISTRIBUTED. Do NOT place multiple entities at the same or nearly identical positions. Each entity must have distinct spatial coordinates with meaningful separation.
- Avoid placing many instances of the same building group (e.g. all spice stalls, all sweet shops) in a single tight cluster.
- Distribute repeated shops/stalls around the anchor/center and along different radii/directions so the town feels mixed and varied.
- Do NOT create long `relative_to` chains of the same entity group (e.g. `cloth_shop_2` relative_to `cloth_shop_1`, `cloth_shop_3` relative_to `cloth_shop_2`, etc.). Mix their parents: some should be relative_to the anchor/center, others to different nearby frontage buildings.
- When multiple instances of the same group exist (e.g. several cloth shops or sweet shops), fan them OUT around the anchor/center using different `dir` values (N, NE, E, SE, S, SW, W, NW) and varied `dist_bucket` (near/medium/far) rather than keeping them on one side.
- Interleave different building types next to each other instead of long runs of the same type; aim for small mixed “blocks” of varied uses.
- Leave reasonable gaps between instances of the same group so roads and paths can naturally thread between them.
- Use diverse `dir` values (N, NE, E, SE, S, SW, W, NW) and `dist_bucket` values (near, medium, far) to ensure spatial spread, especially when multiple props reference the same `relative_to` entity.

Meta Field (Required):
- Set area_type from: town, village, forest, marsh, ruins, dungeon, lake, coast, mountain, cave
- Set road_style from: grid (towns), organic (villages), trails (forest/marsh), none (ruins/dungeon)
- Set map_size_hint based on scale_hint (tiny/small/medium/large/huge)
- Set mood as a brief descriptive string capturing the area's atmosphere

Road Plan (Required):
- Output exactly ONE center with a stable ID (e.g., "town_center", "{area_id}_center").
- road_plan.center_id must be a string ID (not "center" as a special string).
- road_plan.center must include: id (matching center_id), type (plaza/clearing/courtyard/shore), relative_to ("anchor"), radius_hint (tiny/small/medium/large).
- road_plan.main_connectivity MUST include ALL gates - each gate must connect to the center_id.
- Use appropriate connection kinds: trunk_road (major routes), road (standard routes), footpath (minor paths).
- Set road_plan.branching.count_hint and length_hint (low/medium/high) based on area size and gate count.

POI Plan (Required):
- Include only 2-6 story-critical POIs (NOT every building/crate/tree).
- Each POI must have:
  - id (matching an anchor or placement ID)
  - category (structure/landmark/npc/prop)
  - kind (building/landmark/nature/water/prop)
  - district (residential/market/industrial/religious/civic/wild/waterfront)
  - size_hint (tiny/small/medium/large)
  - needs_frontage (true if it should face a road, false otherwise)
  - tags (list of descriptive strings)
  - story_role (descriptive)
  - must_place (true for critical)
  - must_connect (true when must_place is true).
- Use constraints: near (array of IDs), far_from (array of IDs), zone_preference (center/edge/waterfront/high_ground), reachable_from (array of gate/POI IDs).
- Ensure all must_place POIs are reachable from gates via road_plan.main_connectivity.

Goal: Preserve the narrative structure while providing tilemap compiler hints. POIs are where the story stays anchored.
"""

WORLD_GRAPH_INSTRUCTIONS = """\
You are a world topology planner for a procedural map generator.

Return ONLY JSON that matches the provided JSON schema (strict).
Rules:
- DO NOT output coordinates, positions, or meters.
- Choose one center_area_id (typically a settlement area if present, otherwise a central/natural area).
- Create a placements[] array for ALL areas except the center (center is implicitly at "center").
- Each placement must specify: area_id, relative_to (another area_id or "center"), dir (N/NE/E/SE/S/SW/W/NW), dist_bucket (near/medium/far).
- Create a connections[] array that forms a CONNECTED graph (all areas must be reachable from any other area).
- Aim for a tree-like structure (N areas → N-1 connections minimum) or tree + 1 loop for interest.
- Ensure the graph is fully connected: you can reach any area from any other area via the connections.
- Use appropriate connection kinds: trunk_road for major routes, road for standard routes, footpath for minor paths.
- For each connection, specify distance (near/medium/far) indicating how far apart the connected areas are. Use the placements data to infer appropriate distances between areas.
- DO NOT specify edges (N/S/E/W) or connection IDs. The compiler will choose the best entry/exit points automatically.
Goal: produce a connected, traversable world topology.
"""

# -------------------------
# 3) API calls
# -------------------------

def connect(a: str, b: str, distance: str = "medium", kind: str = "road") -> Dict[str, Any]:
    """Helper for abstract connectivity graph."""
    return {
        "from_area_id": a,
        "to_area_id": b,
        "distance": distance,
        "kind": kind
    }

def get_required_entities_for_area(npc_plan: List[Dict[str, Any]], area_id: str) -> List[Dict[str, Any]]:
    """Return anchor_entity objects for the given area_id, with count: None for schema compliance."""
    out: List[Dict[str, Any]] = []
    for npc in npc_plan:
        if npc.get("area_id") != area_id:
            continue
        anchor = npc.get("anchor_entity")
        if not anchor:
            continue
        out.append({
            "id": anchor["id"],
            "kind": anchor["kind"],
            "type": anchor["type"],
            "tags": list(anchor.get("tags", [])),
            "count": None,
        })
    return out

def _call_structured(model: str, instructions: str, user_text: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    inner = schema.get("schema", schema)
    user = user_text + "\n\nOutput JSON matching: " + json.dumps(inner)[:12000]
    return gc.generate_json(instructions, user, model=model, temperature=0.3)

def make_world_plan(story_text: str, model: str = "gemini-2.5-pro") -> Dict[str, Any]:
    print(f"Step 1: Generating Area Narratives from story...")
    
    # 1. Generate Areas + Narratives
    narratives_data = _call_structured(
        model=model,
        instructions=AREA_NARRATIVE_INSTRUCTIONS,
        user_text=f"STORY:\n{story_text}",
        schema=AREA_NARRATIVE_SCHEMA,
    )
    
    areas_list = narratives_data.get("areas", [])
    print(f"  -> Generated {len(areas_list)} areas.")

    # 1b. NPC anchor plan (4-8 NPCs, each with exactly one anchor entity in an existing area)
    print(f"Step 1b: Generating NPC anchor plan...")
    npc_user_lines = ["STORY OVERVIEW:", story_text, "", "AREAS (id, narrative, scale_hint):"]
    for a in areas_list:
        npc_user_lines.append(f"- id: {a['id']}, scale_hint: {a.get('scale_hint', '')}, narrative: {a.get('narrative', '')[:200]}...")
    npc_plan_result = _call_structured(
        model=model,
        instructions=NPC_PLAN_INSTRUCTIONS,
        user_text="\n".join(npc_user_lines),
        schema=NPC_PLAN_SCHEMA,
    )
    npc_plan = npc_plan_result["npcs"]
    print(f"  -> Generated {len(npc_plan)} NPCs with anchor entities.")

    # 2. Generate Entities for each area
    final_areas = []
    
    for area in areas_list:
        area_id = area["id"]
        narrative = area.get("narrative", "")
        print(f"Step 2: Generating entities for '{area_id}'...")
        
        required_anchors = get_required_entities_for_area(npc_plan, area_id)
        other_anchors = sorted(
            set(
                npc["anchor_entity"]["id"]
                for npc in npc_plan
                if npc.get("area_id") != area_id
            )
        )
        user_lines = [
            f"AREA ID: {area_id}",
            f"NARRATIVE: {narrative}",
            "",
            "STORY CONTEXT:",
            story_text,
        ]
        if other_anchors:
            user_lines.extend([
                "",
                "DO NOT include these entity IDs (they are narrative buildings for other areas): " + ", ".join(other_anchors),
            ])
        if required_anchors:
            user_lines.extend([
                "",
                "MUST INCLUDE (anchor entities for NPCs in this area — include these exactly):",
            ])
            for anc in required_anchors:
                user_lines.append(f"- id={anc['id']}, kind={anc['kind']}, type={anc['type']}, tags={anc['tags']}")
        
        entities_data = _call_structured(
            model=model,
            instructions=AREA_ENTITIES_INSTRUCTIONS,
            user_text="\n".join(user_lines),
            schema=AREA_ENTITIES_SCHEMA,
        )
        
        entities = entities_data.get("entities", [])
        anchor_by_id = {a["id"]: a for a in required_anchors}
        # Enforce anchors: overwrite existing or append missing
        seen_ids = set()
        result_entities: List[Dict[str, Any]] = []
        for e in entities:
            eid = e.get("id")
            if eid in anchor_by_id:
                result_entities.append(dict(anchor_by_id[eid]))
                seen_ids.add(eid)
            else:
                result_entities.append(e)
        for aid, anc in anchor_by_id.items():
            if aid not in seen_ids:
                result_entities.append(dict(anc))
        
        area["entities"] = result_entities
        final_areas.append(area)
        
    return {"areas": final_areas, "npc_plan": npc_plan}

def generate_dialogue_json(world_plan: Dict[str, Any], model: str) -> Dict[str, Any]:
    """Placeholder. Will be implemented in DialogueGen.py later."""
    raise NotImplementedError

def make_area_layout(
    *,
    area_id: str,
    scale_hint: str,
    narrative: str,
    entity_groups: List[Dict[str, Any]],
    connections_out: List[Dict[str, Any]],
    model: str,
) -> Dict[str, Any]:
    # Build a compact per-area context (no sizes/coords).
    lines = [
        f"AREA_ID: {area_id}",
        f"SCALE_HINT: {scale_hint}",
        f"NARRATIVE: {narrative}",
        "",
        "ENTITY_GROUPS (in this area):",
    ]
    for eg in entity_groups:
        count = eg.get("count")
        extra = []
        if count is not None:
            extra.append(f"count={count}")
        extra_s = (", " + ", ".join(extra)) if extra else ""
        lines.append(f"- {eg['id']}: kind={eg['kind']}, type={eg['type']}{extra_s}, tags={eg.get('tags', [])}")

    lines += ["", "AREA CONNECTIONS:"]
    for c in connections_out:
        # Compiler now handles edges automatically
        if c['from_area_id'] == area_id:
            other = c['to_area_id']
        else:
            other = c['from_area_id']
        lines.append(f"- {c['kind']} to {other}")

    return _call_structured(
        model=model,
        instructions=AREALAYOUT_INSTRUCTIONS,
        user_text="\n".join(lines),
        schema=AREALAYOUT_SCHEMA,
    )

def make_world_graph(
    *,
    areas: List[Dict[str, Any]],
    model: str = "gpt-4o",
) -> Dict[str, Any]:
    # Build context from areas (id, scale_hint, narrative excerpt)
    lines = [
        "AREAS (to be connected into a traversable world graph):",
        ""
    ]
    for area in areas:
        # Include a brief narrative excerpt to help with connections
        narrative_excerpt = area.get('narrative', '')[:100] + "..." if len(area.get('narrative', '')) > 100 else area.get('narrative', '')
        lines.append(f"- {area['id']}: scale={area.get('scale_hint', 'unknown')}, vibe={narrative_excerpt}")
    
    return _call_structured(
        model=model,
        instructions=WORLD_GRAPH_INSTRUCTIONS,
        user_text="\n".join(lines),
        schema=WORLD_GRAPH_SCHEMA,
    )

# -------------------------
# 4) Minimal validation helpers
# -------------------------

def finalize_placement_metadata(layout: dict) -> None:
    """
    Ensures every placement in layout['placements'] has required metadata.
    Uses safe defaults if missing (kind=prop, district=wild, needs_frontage=False).
    """
    # Ensure placements exists
    if "placements" not in layout:
        layout["placements"] = []

    for p in layout.get("placements", []) or []:
        # Safe defaults if missing
        if "kind" not in p:
            p["kind"] = "prop"
        if "district" not in p:
            p["district"] = "wild"
        if "size_hint" not in p:
            p["size_hint"] = "small"
        if "needs_frontage" not in p:
            p["needs_frontage"] = False
def validate_placement_metadata(layout: dict) -> None:
    """
    Strictly validates that every placement has required metadata fields with valid values.
    Raises ValueError if any check fails.
    """
    placements = layout.get("placements", [])
    
    valid_kinds = {"building", "landmark", "nature", "water", "prop"}
    valid_districts = {"residential", "market", "industrial", "religious", "civic", "wild", "waterfront"}
    valid_sizes = {"tiny", "small", "medium", "large", "huge"}

    # Check for strict mode
    import os
    strict_mode = os.environ.get("STRICT_METADATA", "0") == "1"

    for i, p in enumerate(placements):
        pid = p.get("id", f"index_{i}")
        
        # Check presence
        required = ["kind", "district", "size_hint", "needs_frontage", "tags"]
        missing = [f for f in required if f not in p]
        if missing:
            msg = f"Placement '{pid}' missing metadata fields: {missing}"
            if strict_mode:
                raise ValueError(msg)
            else:
                print(f"WARNING: {msg}")
                continue # Skip further checks for this item if missing fields

        # Check enums
        if p["kind"] not in valid_kinds:
            msg = f"Placement '{pid}' has invalid kind: '{p['kind']}'"
            if strict_mode: raise ValueError(msg)
            else: print(f"WARNING: {msg}")

        if p["district"] not in valid_districts:
            msg = f"Placement '{pid}' has invalid district: '{p['district']}'"
            if strict_mode: raise ValueError(msg)
            else: print(f"WARNING: {msg}")

        if p["size_hint"] not in valid_sizes:
            msg = f"Placement '{pid}' has invalid size_hint: '{p['size_hint']}'"
            if strict_mode: raise ValueError(msg)
            else: print(f"WARNING: {msg}")
        
        # Check types
        if not isinstance(p["needs_frontage"], bool):
            msg = f"Placement '{pid}' needs_frontage must be boolean, got {type(p['needs_frontage'])}"
            if strict_mode: raise ValueError(msg)
            else: print(f"WARNING: {msg}")

        if not isinstance(p["tags"], list):
            msg = f"Placement '{pid}' tags must be a list, got {type(p['tags'])}"
            if strict_mode: raise ValueError(msg)
            else: print(f"WARNING: {msg}")

        if len(p["tags"]) > 10:
            msg = f"Placement '{pid}' has too many tags ({len(p['tags'])} > 10)"
            if strict_mode: raise ValueError(msg)
            else: print(f"WARNING: {msg}")

def validate_world_plan_ids(plan: Dict[str, Any]) -> None:
    area_ids = [a["id"] for a in plan["areas"]]
    if len(area_ids) != len(set(area_ids)):
        raise ValueError("Duplicate area ids found.")

    # Ensure entity ids unique within area (group ids)
    for a in plan["areas"]:
        eids = [e["id"] for e in a["entities"]]
        if len(eids) != len(set(eids)):
            raise ValueError(f"Duplicate entity group ids in area {a['id']}.")

def validate_world_graph_connectivity(graph: Dict[str, Any], area_ids: List[str]) -> None:
    """Validate that the graph is connected (all areas reachable)."""
    area_set = set(area_ids)
    
    # Build adjacency list (undirected graph)
    adj = {area_id: set() for area_id in area_ids}
    for conn in graph["connections"]:
        from_id = conn["from_area_id"]
        to_id = conn["to_area_id"]
        if from_id not in area_set or to_id not in area_set:
            raise ValueError(f"Connection references unknown area: {conn}")
        adj[from_id].add(to_id)
        adj[to_id].add(from_id)
    
    # BFS to check connectivity
    if not area_ids:
        return
    
    visited = set()
    queue = [area_ids[0]]
    visited.add(area_ids[0])
    
    while queue:
        current = queue.pop(0)
        for neighbor in adj[current]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    
    if len(visited) != len(area_ids):
        unreachable = set(area_ids) - visited
        raise ValueError(f"Graph is not connected. Unreachable areas: {unreachable}")

def validate_world_graph(graph: Dict[str, Any]) -> None:
    """
    Strictly validates world_graph.json structure.
    Must contain EXACT keys: center_area_id, placements, connections.
    """
    required_keys = {"center_area_id", "placements", "connections"}
    actual_keys = set(graph.keys())
    
    missing = required_keys - actual_keys
    if missing:
        raise ValueError(f"world_graph.json missing required keys: {missing}")
        
    # Check types
    if not isinstance(graph["center_area_id"], str):
        raise ValueError("center_area_id must be a string")
    if not isinstance(graph["placements"], list):
        raise ValueError("placements must be a list")
    if not isinstance(graph["connections"], list):
        raise ValueError("connections must be a list")


def repair_self_referential_placements(layout: Dict[str, Any]) -> bool:
    """Fix placements where id == relative_to. Returns True if any change was made."""
    changed = False
    anchor_id = layout.get("anchor", {}).get("id")

    for p in layout.get("placements", []):
        pid = p.get("id")
        rel = p.get("relative_to")
        if pid and rel and pid == rel:
            # Prefer anchoring to the area anchor if available; otherwise to string "anchor"
            p["relative_to"] = anchor_id or "center"
            # Optional: force a reasonable distance if it was "far" (self-reference doesn't make sense)
            if p.get("dist_bucket") == "far":
                p["dist_bucket"] = "medium"
            changed = True

    return changed

def repair_missing_gate_connectivity(layout: Dict[str, Any]) -> bool:
    """
    Ensure every gate has a road_plan.main_connectivity edge to center_id.
    Returns True if changes were made.
    """
    changed = False
    area_id = layout.get("area_id", "unknown")

    road_plan = layout.get("road_plan") or {}
    center_id = road_plan.get("center_id")
    if not center_id:
        return False  # let your existing validator handle missing center_id

    gates = layout.get("gates", [])
    main = road_plan.get("main_connectivity")
    if main is None:
        main = []
        road_plan["main_connectivity"] = main
        changed = True

    # Check which gates already have connections TO the center (matching validation logic)
    gate_to_center = {e.get("from") for e in main if isinstance(e, dict) and e.get("to") == center_id}

    # choose default kind
    meta = layout.get("meta") or {}
    road_style = meta.get("road_style", "organic")
    default_kind = "road"
    if road_style in ("trails", "none"):
        default_kind = "footpath"

    # for towns, optionally make the first missing gate trunk_road
    make_first_trunk = (meta.get("area_type") == "town")

    for gate in gates:
        gid = gate.get("id")
        if not gid or gid in gate_to_center:
            continue

        kind = "trunk_road" if (make_first_trunk and "trunk_road" not in [e.get("kind") for e in main if isinstance(e, dict)]) else default_kind

        main.append({"from": gid, "to": center_id, "kind": kind})
        gate_to_center.add(gid)
        changed = True

    if changed:
        layout["road_plan"] = road_plan
        print(f"↻ Repaired missing gate connectivity in {area_id}")

    return changed

def repair_circular_relative_to(layout: Dict[str, Any]) -> bool:
    """
    Break cycles in placements[].relative_to by re-rooting one node in each cycle
    to the anchor (preferred) or to "center".
    Returns True if changes were made.
    """
    changed = False
    area_id = layout.get("area_id", "unknown")
    anchor_id = layout.get("anchor", {}).get("id")  # anchor is always present in schema

    placement_map = {p["id"]: p for p in layout.get("placements", []) if p.get("id")}
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def break_cycle(cycle_nodes: list[str]) -> None:
        nonlocal changed

        def prio(pid: str) -> int:
            return int(placement_map.get(pid, {}).get("priority", 0))

        victim = min(cycle_nodes, key=prio) if cycle_nodes else None
        if not victim:
            return

        # If anchor participates in the cycle, do NOT re-root to it.
        # Use "center" as the guaranteed root.
        if anchor_id and anchor_id not in cycle_nodes and victim != anchor_id:
            new_relative_to = anchor_id
        else:
            new_relative_to = "center"

        placement_map[victim]["relative_to"] = new_relative_to

        if placement_map[victim].get("dist_bucket") == "far":
            placement_map[victim]["dist_bucket"] = "medium"

        changed = True
        print(f"↻ Broke relative_to cycle in {area_id}: re-rooted '{victim}' -> '{new_relative_to}'")


    def dfs(pid: str) -> None:
        nonlocal changed
        if pid in visited:
            return
        if pid in visiting:
            # Found a cycle: extract it from stack
            if pid in stack:
                i = stack.index(pid)
                cycle_nodes = stack[i:]  # nodes in the loop
                break_cycle(cycle_nodes)
            return

        visiting.add(pid)
        stack.append(pid)

        rel_to = placement_map.get(pid, {}).get("relative_to")
        if rel_to and rel_to != "center" and rel_to in placement_map:
            dfs(rel_to)

        stack.pop()
        visiting.remove(pid)
        visited.add(pid)

    for pid in list(placement_map.keys()):
        dfs(pid)

    return changed

def repair_center_id_mismatch(layout: Dict[str, Any]) -> bool:
    """
    Fix mismatch between road_plan.center_id and road_plan.center.id.
    Updates center_id and all references to match the actual center object's id.
    Returns True if changes were made.
    """
    changed = False
    area_id = layout.get("area_id", "unknown")
    road_plan = layout.get("road_plan")
    
    if not road_plan:
        return False
    
    center_id = road_plan.get("center_id")
    center_obj = road_plan.get("center", {})
    actual_center_id = center_obj.get("id")
    
    if not center_id or not actual_center_id:
        return False
    
    if center_id != actual_center_id:
        # Update center_id to match the actual center object
        old_center_id = center_id
        road_plan["center_id"] = actual_center_id
        
        # Update all references in main_connectivity
        main_connectivity = road_plan.get("main_connectivity", [])
        for conn in main_connectivity:
            if conn.get("to") == old_center_id:
                conn["to"] = actual_center_id
            if conn.get("from") == old_center_id:
                conn["from"] = actual_center_id
        
        # Update references in paths (if they exist)
        paths = layout.get("paths", [])
        for path in paths:
            if path.get("to") == old_center_id:
                path["to"] = actual_center_id
            if path.get("from") == old_center_id:
                path["from"] = actual_center_id
        
        # Update references in poi_plan
        poi_plan = layout.get("poi_plan", [])
        for poi in poi_plan:
            # Update reachable_from
            reachable_from = poi.get("reachable_from", [])
            if old_center_id in reachable_from:
                idx = reachable_from.index(old_center_id)
                reachable_from[idx] = actual_center_id
            
            # Update near
            near = poi.get("near", [])
            if near and old_center_id in near:
                idx = near.index(old_center_id)
                near[idx] = actual_center_id
            
            # Update far_from
            far_from = poi.get("far_from", [])
            if far_from and old_center_id in far_from:
                idx = far_from.index(old_center_id)
                far_from[idx] = actual_center_id
        
        changed = True
        print(f"↻ Repaired center_id mismatch in {area_id}: '{old_center_id}' -> '{actual_center_id}'")
    
    return changed

def repair_frontage_props(layout: Dict[str, Any]) -> bool:
    """
    Repair roadside props to ensure they have needs_frontage=true and are placed
    relative_to entities with needs_frontage=true.
    Returns True if any changes were made.
    """
    changed = False
    area_id = layout.get("area_id", "unknown")
    placements = layout.get("placements", []) or []
    anchor_id = layout.get("anchor", {}).get("id")
    road_plan = layout.get("road_plan", {})
    center_id = road_plan.get("center_id")
    
    # Build a map of placement_id -> placement for quick lookup
    placement_map = {p.get("id"): p for p in placements if p.get("id")}
    
    # Build set of entities with needs_frontage=True (including anchor and center if applicable)
    frontage_entities = set()
    if anchor_id:
        # Check if anchor has frontage (it might not be in placements)
        anchor_obj = layout.get("anchor", {})
        if anchor_obj.get("needs_frontage") is True:
            frontage_entities.add(anchor_id)
    if center_id:
        frontage_entities.add(center_id)
    
    for pid, p in placement_map.items():
        if p.get("needs_frontage") is True:
            frontage_entities.add(pid)
    
    # Heuristics to identify roadside props
    roadside_keywords = ["lamp", "lantern", "streetlamp", "signpost", "street_light", 
                        "streetlight", "bench", "signboard", "street_lamp", "roadside"]
    
    def is_roadside_prop(placement: Dict[str, Any]) -> bool:
        """Check if a placement is likely a roadside prop."""
        pid = placement.get("id", "").lower()
        tags = [t.lower() for t in placement.get("tags", [])]
        kind = placement.get("kind", "").lower()
        
        # Check id and tags for roadside keywords
        for keyword in roadside_keywords:
            if keyword in pid or any(keyword in tag for tag in tags):
                return True
        
        # Props near roads are likely roadside props
        if kind == "prop" and any("road" in tag or "street" in tag for tag in tags):
            return True
        
        return False
    
    # Process each placement
    for p in placements:
        pid = p.get("id")
        if not pid:
            continue
        
        if not is_roadside_prop(p):
            continue
        
        # Force needs_frontage = True for roadside props
        if p.get("needs_frontage") is not True:
            p["needs_frontage"] = True
            changed = True
        
        # Ensure relative_to points to a frontage entity
        rel_to = p.get("relative_to")
        if rel_to and rel_to not in frontage_entities:
            # Try to find a nearby frontage entity
            # Prefer buildings in the same district, then anchor, then center
            target_district = p.get("district")
            best_target = None
            
            # First, try to find a frontage building in the same district
            if target_district:
                for fid, fp in placement_map.items():
                    if (fid in frontage_entities and 
                        fp.get("district") == target_district and
                        fp.get("kind") in ("building", "landmark")):
                        best_target = fid
                        break
            
            # If no district match, prefer anchor, then center
            if not best_target:
                if anchor_id and anchor_id in frontage_entities:
                    best_target = anchor_id
                elif center_id:
                    best_target = center_id
                else:
                    # Fallback: find any frontage entity
                    for fid in frontage_entities:
                        if fid in placement_map:
                            best_target = fid
                            break
            
            if best_target and rel_to != best_target:
                old_rel = rel_to
                p["relative_to"] = best_target
                changed = True
                # Avoid creating self-reference
                if pid == best_target:
                    # Fallback to anchor or center
                    if anchor_id and anchor_id != pid:
                        p["relative_to"] = anchor_id
                    elif center_id and center_id != pid:
                        p["relative_to"] = center_id
                    else:
                        # Last resort: keep original but log warning
                        p["relative_to"] = old_rel
                        print(f"⚠ Warning: Could not find valid frontage target for {pid} in {area_id}")
    
    if changed:
        print(f"↻ Repaired frontage props in {area_id}")
    
    return changed

def validate_area_layout_connectivity(layout: Dict[str, Any]) -> None:
    """Validate area layout connectivity: IDs exist, no cycles, gates connect to center."""
    area_id = layout.get("area_id", "unknown")
    
    # Collect all valid IDs
    valid_ids = set()
    
    # Add anchor ID
    anchor_id = layout["anchor"]["id"]
    valid_ids.add(anchor_id)
    
    # Add gate IDs
    gate_ids = {gate["id"] for gate in layout["gates"]}
    valid_ids.update(gate_ids)
    
    # Add placement IDs
    placement_ids = {p["id"] for p in layout["placements"]}
    valid_ids.update(placement_ids)
    
    # Add center_id from road_plan
    road_plan = layout.get("road_plan", {})
    center_id = road_plan.get("center_id")
    if center_id:
        valid_ids.add(center_id)
    
    # Check all main_connectivity endpoints exist
    main_connectivity = road_plan.get("main_connectivity", [])
    for conn in main_connectivity:
        from_id = conn["from"]
        to_id = conn["to"]
        if from_id not in valid_ids:
            raise ValueError(f"Area {area_id}: main_connectivity references unknown 'from' ID: {from_id}")
        if to_id not in valid_ids:
            raise ValueError(f"Area {area_id}: main_connectivity references unknown 'to' ID: {to_id}")
    
    # Check center_id matches center.id
    center_obj = road_plan.get("center", {})
    if center_id and center_obj.get("id") != center_id:
        raise ValueError(f"Area {area_id}: road_plan.center_id '{center_id}' does not match center.id '{center_obj.get('id')}'")
    
    # Check no self-referential placements first
    placement_map = {p["id"]: p for p in layout["placements"]}
    for pid, placement in placement_map.items():
        rel_to = placement.get("relative_to")
        if rel_to == pid:
            raise ValueError(f"Area {area_id}: Self-referential placement detected: '{pid}' references itself in relative_to")
    
    # Check no circular relative_to dependencies
    visited = set()
    
    def check_cycle(pid: str, path: List[str]) -> None:
        if pid in path:
            raise ValueError(f"Area {area_id}: Circular relative_to dependency detected: {' -> '.join(path + [pid])}")
        if pid in visited:
            return
        visited.add(pid)
        if pid in placement_map:
            rel_to = placement_map[pid].get("relative_to")
            if rel_to and rel_to != "center" and rel_to in placement_map:
                check_cycle(rel_to, path + [pid])
    
    for pid in placement_map:
        if pid not in visited:
            check_cycle(pid, [])
    
    # Verify at least one path from each gate to center exists in main_connectivity
    if center_id:
        gate_to_center = {conn["from"] for conn in main_connectivity if conn["to"] == center_id}
        missing_gates = gate_ids - gate_to_center
        if missing_gates:
            raise ValueError(f"Area {area_id}: Gates {missing_gates} have no connection to center '{center_id}' in road_plan.main_connectivity")

def validate_poi_plan(layout: Dict[str, Any]) -> None:
    """Validate poi_plan: must_connect defaults, POI IDs exist, no duplicates."""
    area_id = layout.get("area_id", "unknown")
    poi_plan = layout.get("poi_plan", [])
    
    # Collect all valid IDs (anchor, placements, gates, center_id)
    valid_ids = {layout["anchor"]["id"]}
    valid_ids.update(p["id"] for p in layout["placements"])
    valid_ids.update(g["id"] for g in layout["gates"])
    road_plan = layout.get("road_plan", {})
    center_id = road_plan.get("center_id")
    if center_id:
        valid_ids.add(center_id)
    
    # Check for duplicate POI IDs
    poi_ids = [poi["id"] for poi in poi_plan]
    if len(poi_ids) != len(set(poi_ids)):
        duplicates = [pid for pid in poi_ids if poi_ids.count(pid) > 1]
        raise ValueError(f"Area {area_id}: Duplicate POI IDs in poi_plan: {set(duplicates)}")
    
    # Validate each POI
    for poi in poi_plan:
        poi_id = poi["id"]
        
        # Ensure POI ID exists (must match anchor, placement, or center_id)
        if poi_id not in valid_ids:
            # Auto-repair common mismatch: poi_plan may reference an entity-group id
            # (e.g. "breakfast_stall") while placements are instantiated as
            # "breakfast_stall_1", "breakfast_stall_2", ...
            placements = layout.get("placements", []) or []
            candidates = [p for p in placements if isinstance(p.get("id"), str) and p["id"].startswith(f"{poi_id}_")]
            if candidates:
                # Prefer highest priority placement, then stable sort by id.
                candidates.sort(key=lambda p: (p.get("priority", 0), p.get("id", "")), reverse=True)
                new_id = candidates[0]["id"]
                old_id = poi_id
                poi["id"] = new_id
                poi_id = new_id
                print(f"↻ Repaired poi_plan id in {area_id}: '{old_id}' -> '{new_id}'")
            else:
                raise ValueError(f"Area {area_id}: POI '{poi_id}' in poi_plan does not match any anchor, placement, gate, or center_id")
        
        # Auto-fix: if must_place is true and must_connect is missing, default to true
        if poi.get("must_place") is True and "must_connect" not in poi:
            poi["must_connect"] = True
        
        # Check reachable_from endpoints exist (handle null)
        reachable_from = poi.get("reachable_from") or []
        for endpoint in reachable_from:
            if endpoint not in valid_ids:
                raise ValueError(f"Area {area_id}: POI '{poi_id}' has reachable_from endpoint '{endpoint}' that does not exist")
        
        # Check near endpoints exist (handle null)
        near = poi.get("near") or []
        for endpoint in near:
            if endpoint not in valid_ids and endpoint != "center":
                raise ValueError(f"Area {area_id}: POI '{poi_id}' has near endpoint '{endpoint}' that does not exist")
        
        # Check far_from endpoints exist (handle null)
        far_from = poi.get("far_from") or []
        for endpoint in far_from:
            if endpoint not in valid_ids and endpoint != "center":
                raise ValueError(f"Area {area_id}: POI '{poi_id}' has far_from endpoint '{endpoint}' that does not exist")

def migrate_area_layout(layout: Dict[str, Any], area_role: str, area_tags: List[str]) -> Dict[str, Any]:
    """Migrate existing area layout to include meta, road_plan, and poi_plan."""
    area_id = layout.get("area_id", "unknown")
    
    # Infer area_type from role and tags
    area_type = "town"  # default
    if area_role == "settlement":
        if "village" in " ".join(area_tags).lower() or area_id.endswith("_village"):
            area_type = "village"
        else:
            area_type = "town"
    elif area_role == "natural":
        if "lake" in " ".join(area_tags).lower() or "water" in " ".join(area_tags).lower():
            area_type = "lake"
        elif "marsh" in " ".join(area_tags).lower() or "wetland" in " ".join(area_tags).lower():
            area_type = "marsh"
        elif "coast" in " ".join(area_tags).lower() or "beach" in " ".join(area_tags).lower():
            area_type = "coast"
        elif "mountain" in " ".join(area_tags).lower():
            area_type = "mountain"
        elif "cave" in " ".join(area_tags).lower():
            area_type = "cave"
        else:
            area_type = "forest"
    elif area_role == "industrial":
        if "ruins" in " ".join(area_tags).lower() or "abandoned" in " ".join(area_tags).lower():
            area_type = "ruins"
        else:
            area_type = "dungeon"
    elif area_role == "agriculture":
        area_type = "forest"  # default for agriculture
    
    # Set road_style based on area_type
    road_style = "organic"  # default
    if area_type == "town":
        road_style = "grid"
    elif area_type == "village":
        road_style = "organic"
    elif area_type in ["forest", "marsh"]:
        road_style = "trails"
    elif area_type in ["ruins", "dungeon"]:
        road_style = "none"  # or could be "organic" for partial roads
    elif area_type in ["lake", "coast"]:
        road_style = "trails"
    else:
        road_style = "organic"
    
    # Get scale_hint from layout or default to medium
    scale_hint = layout.get("scale_hint", "medium")
    if scale_hint not in ["tiny", "small", "medium", "large", "huge"]:
        scale_hint = "medium"
    
    # Create mood from tags
    mood = ", ".join(area_tags) if area_tags else f"{area_type} area"
    
    # Create meta
    meta = {
        "area_type": area_type,
        "road_style": road_style,
        "map_size_hint": scale_hint,
        "mood": mood
    }
    
    # Create road_plan
    anchor_id = layout["anchor"]["id"]
    center_id = f"{area_id}_center" if not anchor_id.endswith("_center") else anchor_id
    
    # Determine center type based on area_type
    center_type = "plaza"
    if area_type in ["forest", "marsh"]:
        center_type = "clearing"
    elif area_type in ["ruins", "dungeon"]:
        center_type = "courtyard"
    elif area_type == "lake":
        center_type = "shore"
    else:
        center_type = "plaza"
    
    # Determine road kind based on area_type (default for gates after first)
    road_kind = "road"
    if area_type in ["forest", "marsh"]:
        road_kind = "footpath"
    elif area_type in ["ruins", "dungeon"]:
        road_kind = "footpath"
    
    # Create main_connectivity connecting all gates to center
    gates = layout.get("gates", [])
    main_connectivity = []
    for i, gate in enumerate(gates):
        gate_id = gate["id"]
        # Use trunk_road for first gate in towns, road/footpath for others
        if area_type == "town" and i == 0:
            kind = "trunk_road"
        else:
            kind = road_kind
        main_connectivity.append({
            "from": gate_id,
            "to": center_id,
            "kind": kind
        })
    
    # Create center object
    center = {
        "id": center_id,
        "type": center_type,
        "relative_to": "anchor",
        "radius_hint": "medium"  # could infer from scale_hint, but medium is safe default
    }
    
    # Determine branching hints based on area_type and number of gates
    count_hint = "medium"
    if len(gates) <= 1:
        count_hint = "low"
    elif len(gates) >= 3:
        count_hint = "high"
    
    length_hint = "medium"
    if scale_hint in ["tiny", "small"]:
        length_hint = "low"
    elif scale_hint in ["large", "huge"]:
        length_hint = "high"
    
    road_plan = {
        "center_id": center_id,
        "center": center,
        "main_connectivity": main_connectivity,
        "branching": {
            "count_hint": count_hint,
            "length_hint": length_hint
        }
    }
    
    # Create poi_plan with anchor and top 1-3 priority placements
    poi_plan = []
    
    # Add anchor as must_place POI
    anchor_poi = {
        "id": anchor_id,
        "category": "landmark",
        "size_hint": "medium",
        "story_role": "area_anchor",
        "must_place": True,
        "must_connect": True,
        "reachable_from": [gate["id"] for gate in gates] + [center_id]
    }
    poi_plan.append(anchor_poi)
    
    # Add top 1-3 priority placements (excluding anchor)
    placements = layout.get("placements", [])
    placements_sorted = sorted([p for p in placements if p["id"] != anchor_id], 
                               key=lambda x: x.get("priority", 0), reverse=True)
    
    top_placements = placements_sorted[:3]  # Top 3 by priority
    
    for placement in top_placements:
        placement_id = placement["id"]
        # Determine category based on naming patterns (simple heuristic)
        category = "structure"
        if any(word in placement_id for word in ["tree", "rock", "flower", "grass"]):
            category = "prop"
        elif any(word in placement_id for word in ["reflection", "footprint", "shadow"]):
            category = "prop"
        
        # Determine size_hint from dist_bucket or default
        dist_bucket = placement.get("dist_bucket", "medium")
        size_hint = "medium"
        if dist_bucket == "near":
            size_hint = "small"
        elif dist_bucket == "far":
            size_hint = "large"
        
        poi = {
            "id": placement_id,
            "category": category,
            "size_hint": size_hint,
            "story_role": "important_feature",
            "must_place": True,
            "must_connect": True,
            "near": [center_id],
            "reachable_from": [center_id]
        }
        poi_plan.append(poi)
    
    # Add new fields to layout
    layout["meta"] = meta
    layout["road_plan"] = road_plan
    layout["poi_plan"] = poi_plan
    
    return layout

# Example usage
if __name__ == "__main__":
    story = """
Phase 1: The Warm Welcome (0–5 Minutes)
Everyone treats you like a local hero. The dialogue options are simple, but the NPCs' responses are slightly "off."
* NPC: Old Man Miller (The Gatekeeper)
* Dialogue: "Back so soon, Elias? The garden hasn't been the same since you... tidied it up."
* Your Options: [Who are you?] / [I don't live here.] / [Where is my house?]
* The Twist: If you say you don't live here, he laughs. "Always the joker. Just like your father before the accident."
* NPC: Sarah (The Baker)
* Dialogue: "I have your favorite loaf ready. No poppy seeds this time. We know how you get when you see small black dots."
* The Horror: She hands you a "loaf," but in the game asset, it's just a grey, pulsating brick.
Phase 2: The Cracks in the Mask (5–12 Minutes)
As you walk deeper into the town, the environment starts to subtly change. Buildings look like they are made of cardboard. People begin to repeat your own thoughts.
* NPC: The Schoolteacher
* Dialogue: "Class is waiting, Elias. Why are you late?"
* Your Options: [I'm not a student.] / [What class?]
* The Reveal: She turns around. Her face is a mirror. You see your own character's face. "The class on Forgetting," she whispers.
* Environmental Shift:
The music transitions from a soft piano to a low, rhythmic thumping—like a heartbeat. Posters on the walls change from "Missing Person" to "Found: Elias" with a photo of a coffin.
Phase 3: The Truth (12–18 Minutes)
You finally reach "Home." It’s the only building that looks "real." An NPC is standing at the door—The Doctor.
* The Doctor:
* Dialogue: "You’ve done a full lap of the town, Elias. Do you remember why we built this place for you?"
* The Choice: [I killed them, didn't I?] / [This is a prison.] / [I want to wake up.]
* The Truth: The "town" is a memory palace constructed in your mind. You are in a psychiatric ward. The "walking" is you pacing in your cell. The NPCs are the ghosts of the people you couldn't save in a tragedy (a fire or a crash).
Phase 4: The Ending (18–20 Minutes)
You enter your "house." It’s just a white room with a single chair.
* Final NPC (A Child): "Don't leave again, Elias. It's cold when you forget us."
* The Mechanic: The screen starts to fade to white. The "Walk" speed slows down until you can't move at all."""
    wp = make_world_plan(story, model="gpt-4o")
    validate_world_plan_ids(wp)

    # Generate world graph (connections and topology)
    area_ids = [a["id"] for a in wp["areas"]]
    wg = make_world_graph(areas=wp["areas"], model="gpt-4o")
    
    # Validate graph connectivity
    validate_world_graph(wg)
    validate_world_graph_connectivity(wg, area_ids)

    # Build adjacency for area layout contexts from graph connections
    outgoing = {a["id"]: [] for a in wp["areas"]}
    for c in wg["connections"]:
        outgoing[c["from_area_id"]].append(c)



    # Save LLM outputs to separate JSON files
    with open("world_plan.json", "w") as f:
        json.dump(wp, f, indent=2)
    
    with open("world_graph.json", "w") as f:
        json.dump(wg, f, indent=2)
    
        #    with open("area_layouts.json", "w") as f:
        #        json.dump(layouts, f, indent=2)
        #