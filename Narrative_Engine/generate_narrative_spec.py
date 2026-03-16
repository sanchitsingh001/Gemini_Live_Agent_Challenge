#!/usr/bin/env python3
"""
generate_narrative_spec.py

Input:  vague story text
Output: narrative_spec.json

Design constraints:
- Outdoors only. Talk-only. No combat. No interiors.
- Static world: anchors/buildings/landmarks are placed once and never move.
- All anchors must be *placeable outdoors without dependencies* (NO bridge that requires a river, no dock that requires water, etc.).
- NPCs are always standing next to their chosen anchor.
- Clues are discovered ONLY by talking to NPCs. No environmental clues.
- 6–7 NPCs. 3–4 chapters max. Chapters gated by collected clues.
- Ending: when the player collects the final chapter's exit clues, show a "black screen" narrator cutscene.

This version:
- Generates chunk-by-chunk
- Repairs chunk-by-chunk (NO full-spec reprint repair)
- Runs model evaluation + deterministic validation
"""

import os, json, time, argparse, logging, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Set, Optional, Tuple
from difflib import get_close_matches

import gemini_client as gc

# Optional: strict schema validation in Python (nice-to-have)
try:
    import jsonschema  # type: ignore
except Exception:
    jsonschema = None


# ---------------- logging ----------------
def setup_logger(level="INFO"):
    lg = logging.getLogger("narrative")
    lg.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not lg.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        lg.addHandler(h)
    return lg


# ---------------- Vertex Gemini helpers ----------------
RATE_LIMIT_MAX_RETRIES = 10
RATE_LIMIT_DEFAULT_WAIT = 2.0


def _call_with_retry_gemini(fn, lg: logging.Logger, label: str):
    for attempt in range(RATE_LIMIT_MAX_RETRIES):
        try:
            return fn()
        except Exception as e:
            if attempt >= RATE_LIMIT_MAX_RETRIES - 1:
                raise
            msg = str(e).lower()
            wait = RATE_LIMIT_DEFAULT_WAIT * (attempt + 1)
            if "429" in msg or "quota" in msg or "resource exhausted" in msg:
                wait = min(90.0, 10.0 * (attempt + 1))
            lg.warning(f"{label} retry {attempt + 2}/{RATE_LIMIT_MAX_RETRIES} after {wait:.1f}s: {e}")
            time.sleep(wait)


def call_text(
    _client_none, model: str, system: str, user: str, temp: float,
    label: str, lg: logging.Logger, max_output_tokens: int | None = None
) -> str:
    lg.info(f"{label} -> request (text)")
    t0 = time.time()

    def _run():
        return gc.generate_text(system, user, model=model, temperature=temp)

    out = _call_with_retry_gemini(_run, lg, label)
    lg.info(f"{label} <- {time.time()-t0:.1f}s chars={len(out)}")
    return out


def call_json(
    _client_none,
    model: str,
    system: str,
    user: str,
    schema: Dict[str, Any],
    temp: float,
    label: str,
    lg: logging.Logger,
    max_output_tokens: int | None = None
) -> Dict[str, Any]:
    lg.info(f"{label} -> request (json)")
    t0 = time.time()
    u = user + "\n\nJSON must match schema: " + json.dumps(schema)[:14000]

    def _run():
        return gc.generate_json(system, u, model=model, temperature=temp)

    try:
        raw = _call_with_retry_gemini(_run, lg, label)
        lg.info(f"{label} <- {time.time()-t0:.1f}s")
        return raw if isinstance(raw, dict) else {}
    except Exception as e:
        lg.warning(f"{label} failed: {e}; repair pass")
        repair = (
            "Reconstruct VALID JSON matching the schema. Output ONLY JSON.\n\n"
            "CONTEXT:\n" + user[:6000]
        )
        out = gc.generate_json(system + " Repair malformed output.", repair, model=model, temperature=0.0)
        return out if isinstance(out, dict) else {}


def _json_array_ok(v: Any, min_items: int, max_items: int) -> bool:
    return isinstance(v, list) and min_items <= len(v) <= max_items


def ensure_json_array(
    obj: Dict[str, Any],
    key: str,
    min_items: int,
    max_items: int,
    lg: logging.Logger,
    label: str,
    fallback: Optional[List[Any]],
) -> Optional[List[Any]]:
    """
    Safe extract of a top-level array from LLM JSON. Models sometimes return {} or wrong keys
    despite schema (especially long REPAIR CHAPTERS calls). Returns fallback if invalid.
    """
    v = obj.get(key) if isinstance(obj, dict) else None
    if _json_array_ok(v, min_items, max_items):
        return v
    keys = list(obj.keys()) if isinstance(obj, dict) else []
    lg.warning(
        f"{label} invalid '{key}': type={type(v).__name__} "
        f"len={len(v) if isinstance(v, list) else 'n/a'} top_keys={keys[:15]}"
    )
    return fallback


_DEFAULT_EVAL_SUBSCORES = {
    "coherence": 0, "pacing": 0, "clue_fairness": 0, "npc_distinctness": 0,
    "solvability": 0, "player_agency": 0, "tension": 0, "voice_distinctness": 0,
    "anomaly_over_exposition": 0, "engagement": 0,
}


def normalize_quality_report(
    ev: Any,
    prev: Optional[Dict[str, Any]] = None,
    lg: Optional[logging.Logger] = None,
    label: str = "",
) -> Dict[str, Any]:
    """EVAL calls sometimes return {}; avoid KeyError on overall_score / subscores."""
    prev = prev or {}
    if not isinstance(ev, dict):
        ev = {}
    try:
        overall = int(ev.get("overall_score", prev.get("overall_score", 0)))
    except Exception:
        overall = int(prev.get("overall_score", 0))
    overall = max(0, min(100, overall))
    sub = dict(_DEFAULT_EVAL_SUBSCORES)
    src = ev.get("subscores") if isinstance(ev.get("subscores"), dict) else prev.get("subscores")
    if isinstance(src, dict):
        for k in _DEFAULT_EVAL_SUBSCORES:
            try:
                sub[k] = max(0, min(10, int(src.get(k, 0))))
            except Exception:
                pass
    strengths = ev.get("strengths")
    if not isinstance(strengths, list) or len(strengths) < 2:
        strengths = prev.get("strengths") if isinstance(prev.get("strengths"), list) and len(prev["strengths"]) >= 2 else [
            "Evaluation partial",
            "Re-run or inspect validation_report",
        ]
    problems = ev.get("problems") if isinstance(ev.get("problems"), list) else (prev.get("problems") or [])
    if lg and label and not ev.get("overall_score") and not ev.get("subscores"):
        lg.warning(f"{label} EVAL returned incomplete JSON; filled defaults")
    return {
        "overall_score": overall,
        "subscores": sub,
        "strengths": strengths,
        "problems": problems,
    }


# ---------------- Schema primitives ----------------
ID_REF = {"type": "string", "pattern": "^[a-z0-9_]+$"}
CH_REF = {"type": "string", "pattern": "^chapter_[1-4]$"}


def nullable_array(items_schema: Dict[str, Any], max_items: int):
    return {"anyOf": [{"type": "array", "items": items_schema, "minItems": 0, "maxItems": max_items}, {"type": "null"}]}


# ---------------- Placeability guardrails ----------------
FORBIDDEN_DEPENDENCY_WORDS = [
    # things that usually imply environmental dependencies you said you cannot guarantee
    "bridge", "river", "creek", "stream", "dock", "pier", "wharf",
    "lake", "ocean", "sea", "harbor", "marina", "shore",
    "cliff", "canyon", "ravine", "waterfall",
    "cave", "tunnel",  # often implies interior/underground traversal
    # non-grid-placeable: hanging, floating, or path-like entities
    "hanging", "floating", "suspended", "aerial", "pathway", "walkway", "corridor",
]

# Small props that must not be used as anchors (major placeable objects only)
FORBIDDEN_SMALL_PROP_WORDS = [
    "lantern", "lamp", "streetlamp", "street_lamp", "streetlight", "street_light",
    "signpost", "sign_post", "barrel", "crate", "cart", "debris",
    "chandelier", "hanging_lantern", "bench",
]

_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(map(re.escape, FORBIDDEN_DEPENDENCY_WORDS)) + r")\b", re.IGNORECASE)
_SMALL_PROP_RE = re.compile(r"\b(" + "|".join(map(re.escape, FORBIDDEN_SMALL_PROP_WORDS)) + r")\b", re.IGNORECASE)


def anchor_has_forbidden_dependency(anchor: Dict[str, Any]) -> Optional[str]:
    text = " ".join([
        str(anchor.get("label", "")),
        str(anchor.get("type", "")),
        str(anchor.get("description", "")),
        str(anchor.get("placement_notes", "")),
    ]).strip()
    m = _FORBIDDEN_RE.search(text)
    return m.group(1).lower() if m else None


def anchor_has_small_prop(anchor: Dict[str, Any]) -> Optional[str]:
    """Return the matched small-prop word if this anchor looks like a small prop (not a major placeable object)."""
    text = " ".join([
        str(anchor.get("id", "")),
        str(anchor.get("label", "")),
        str(anchor.get("type", "")),
        str(anchor.get("description", "")),
        str(anchor.get("placement_notes", "")),
    ]).strip()
    m = _SMALL_PROP_RE.search(text)
    return m.group(1).lower() if m else None


# ---------------- Schemas ----------------
ANCHORS_SCHEMA = {
    "type": "object",
    "properties": {
        "anchors": {
            "type": "array",
            "minItems": 6,
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "id": ID_REF,
                    "label": {"type": "string", "minLength": 3, "maxLength": 60},
                    "type": {"type": "string", "minLength": 3, "maxLength": 40},
                    "description": {"type": "string", "minLength": 12, "maxLength": 200},
                    "placement_notes": {
                        "type": "string",
                        "minLength": 10,
                        "maxLength": 180,
                        "description": "How to place this outdoors in a static world. Solid entity occupying grid cell(s). No water/river/hanging/floating."
                    },
                },
                "required": ["id", "label", "type", "description", "placement_notes"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["anchors"],
    "additionalProperties": False,
}

CLUES_SCHEMA = {
    "type": "object",
    "properties": {
        "clues": {
            "type": "array",
            "minItems": 10,
            "maxItems": 14,
            "items": {
                "type": "object",
                "properties": {
                    "id": ID_REF,
                    "label": {"type": "string", "minLength": 3, "maxLength": 60},
                    "anchor_id": ID_REF,
                    "interaction": {"type": "string", "minLength": 6, "maxLength": 120},
                    "description": {"type": "string", "minLength": 12, "maxLength": 220},
                    "what_it_implies": {"type": "string", "minLength": 10, "maxLength": 200},
                    "key_for_progress": {"type": "boolean"},
                },
                "required": ["id", "label", "anchor_id", "interaction", "description", "what_it_implies", "key_for_progress"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clues"],
    "additionalProperties": False,
}

TENSION_STATE_ENUM = [
    "Concealing", "Negotiating", "Desperate", "Testing the player",
    "Buying time", "Misdirecting", "Protecting someone"
]

NPCS_SCHEMA = {
    "type": "object",
    "properties": {
        "npcs": {
            "type": "array",
            "minItems": 6,
            "maxItems": 7,
            "items": {
                "type": "object",
                "properties": {
                    "id": ID_REF,
                    "name": {"type": "string", "minLength": 2, "maxLength": 40},
                    "role": {"type": "string", "minLength": 3, "maxLength": 60},
                    "anchor_id": ID_REF,
                    "pose": {"type": "string", "enum": ["standing"]},
                    "vibe": {"type": "string", "minLength": 8, "maxLength": 160},
                    "public_face": {"type": "string", "minLength": 8, "maxLength": 180},
                    "private_truth": {"type": "string", "minLength": 8, "maxLength": 220},
                    "protected_truth": {"type": "string", "minLength": 8, "maxLength": 220},
                    "misleading_claim": {"type": "string", "minLength": 8, "maxLength": 180},
                    "voice_style": {"type": "string", "minLength": 8, "maxLength": 120},
                    "lie_style": {"type": "string", "minLength": 8, "maxLength": 180},
                    "pressure_points": {"type": "string", "minLength": 8, "maxLength": 180},
                    "baseline": {
                        "type": "object",
                        "properties": {
                            "trust": {"type": "integer", "minimum": 0, "maximum": 3},
                            "pressure": {"type": "integer", "minimum": 0, "maximum": 3},
                        },
                        "required": ["trust", "pressure"],
                        "additionalProperties": False,
                    }
                },
                "required": ["id", "name", "role", "anchor_id", "pose", "vibe", "public_face", "private_truth", "protected_truth", "misleading_claim", "voice_style", "lie_style", "pressure_points", "baseline"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["npcs"],
    "additionalProperties": False,
}

CHAPTERS_SCHEMA = {
    "type": "object",
    "properties": {
        "chapters": {
            "type": "array",
            "minItems": 3,
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "id": CH_REF,
                    "title": {"type": "string", "minLength": 3, "maxLength": 60},
                    "narration": {"type": "string", "minLength": 60, "maxLength": 520},
                    "event_beats": {"type": "array", "minItems": 3, "maxItems": 6, "items": {"type": "string", "minLength": 10, "maxLength": 120}},
                    "spotlight_npc_ids": {"type": "array", "minItems": 1, "maxItems": 2, "items": ID_REF},
                    "available_anchor_ids": {"type": "array", "minItems": 3, "maxItems": 10, "items": ID_REF},
                    "available_clue_ids": {"type": "array", "minItems": 1, "maxItems": 2, "items": ID_REF},
                    "entry_require_all_clues": {"type": "array", "minItems": 0, "maxItems": 6, "items": ID_REF},
                    "entry_require_any_clues": nullable_array(ID_REF, 6),
                    "exit_require_all_clues": {"type": "array", "minItems": 1, "maxItems": 2, "items": ID_REF},
                    "transition_player_hook": {"type": "string", "minLength": 40, "maxLength": 400},
                },
                "required": [
                    "id", "title", "narration", "event_beats",
                    "spotlight_npc_ids", "available_anchor_ids",
                    "available_clue_ids",
                    "entry_require_all_clues", "entry_require_any_clues",
                    "exit_require_all_clues"
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["chapters"],
    "additionalProperties": False,
}

NPC_CHAPTER_STATES_SCHEMA = {
    "type": "object",
    "properties": {
        "npc_id": ID_REF,
        "chapter_states": {
            "type": "array",
            "minItems": 3,
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "chapter_id": CH_REF,
                    "stance": {"type": "string", "minLength": 6, "maxLength": 140},
                    "tension_state": {"type": "string", "enum": TENSION_STATE_ENUM},
                    "reveal_cost": {"anyOf": [{"type": "string", "minLength": 8, "maxLength": 120}, {"type": "null"}]},
                    "goal": {"type": "string", "minLength": 6, "maxLength": 140},
                    "how_they_treat_player": {"type": "string", "minLength": 8, "maxLength": 160},
                    "what_they_offer": {"type": "string", "minLength": 8, "maxLength": 180},
                    "what_they_refuse": {"type": "string", "minLength": 8, "maxLength": 180},
                    "reacts_to_clues_any": nullable_array(ID_REF, 8),
                    "reacts_to_clues_all": nullable_array(ID_REF, 8),
                    "sample_lines": {
                        "type": "object",
                        "properties": {
                            "greeting": {"type": "string", "minLength": 3, "maxLength": 120},
                            "evasive": {"type": "string", "minLength": 3, "maxLength": 120},
                            "pressured": {"type": "string", "minLength": 3, "maxLength": 120},
                            "reveal": {"type": "string", "minLength": 3, "maxLength": 140},
                        },
                        "required": ["greeting", "evasive", "pressured", "reveal"],
                        "additionalProperties": False,
                    }
                },
                "required": [
                    "chapter_id", "stance", "tension_state", "reveal_cost", "goal", "how_they_treat_player",
                    "what_they_offer", "what_they_refuse",
                    "reacts_to_clues_any", "reacts_to_clues_all",
                    "sample_lines"
                ],
                "additionalProperties": False,
            }
        }
    },
    "required": ["npc_id", "chapter_states"],
    "additionalProperties": False,
}

ENDING_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "minLength": 3, "maxLength": 80},
        "trigger": {
            "type": "object",
            "properties": {
                "chapter_id": CH_REF,
                "requires_all_clues": {"type": "array", "minItems": 0, "maxItems": 6, "items": ID_REF},
            },
            "required": ["chapter_id", "requires_all_clues"],
            "additionalProperties": False,
        },
        "black_screen_text": {"type": "string", "minLength": 120, "maxLength": 800},
        "open_thread": {"type": "string", "minLength": 20, "maxLength": 120},
    },
    "required": ["title", "trigger", "black_screen_text", "open_thread"],
    "additionalProperties": False,
}

EVAL_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "subscores": {
            "type": "object",
            "properties": {
                "coherence": {"type": "integer", "minimum": 0, "maximum": 10},
                "pacing": {"type": "integer", "minimum": 0, "maximum": 10},
                "clue_fairness": {"type": "integer", "minimum": 0, "maximum": 10},
                "npc_distinctness": {"type": "integer", "minimum": 0, "maximum": 10},
                "solvability": {"type": "integer", "minimum": 0, "maximum": 10},
                "player_agency": {"type": "integer", "minimum": 0, "maximum": 10},
                "tension": {"type": "integer", "minimum": 0, "maximum": 10},
                "voice_distinctness": {"type": "integer", "minimum": 0, "maximum": 10},
                "anomaly_over_exposition": {"type": "integer", "minimum": 0, "maximum": 10},
                "engagement": {"type": "integer", "minimum": 0, "maximum": 10},
            },
            "required": ["coherence", "pacing", "clue_fairness", "npc_distinctness", "solvability", "player_agency", "tension", "voice_distinctness", "anomaly_over_exposition", "engagement"],
            "additionalProperties": False,
        },
        "strengths": {"type": "array", "minItems": 2, "maxItems": 6, "items": {"type": "string", "minLength": 6, "maxLength": 140}},
        "problems": {
            "type": "array",
            "minItems": 0,
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "issue": {"type": "string", "minLength": 8, "maxLength": 220},
                    "fix": {"type": "string", "minLength": 8, "maxLength": 220},
                },
                "required": ["severity", "issue", "fix"],
                "additionalProperties": False,
            }
        }
    },
    "required": ["overall_score", "subscores", "strengths", "problems"],
    "additionalProperties": False,
}

# meta.experience: optional; Godot may use opening_image_path + first_objective_* (same dir as game_bundle).
EXPERIENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "opening_image_path": {"type": "string", "maxLength": 120},
        "opening_video_path": {"type": "string", "maxLength": 120},
        "first_objective_npc_id": {"type": "string", "maxLength": 64},
        "first_objective_text": {"type": "string", "maxLength": 320},
        "setup_screen_path": {"type": "string", "maxLength": 120},
        "ending_screen_path": {"type": "string", "maxLength": 120},
    },
    "additionalProperties": False,
}

FINAL_SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "meta": {
            "type": "object",
            "properties": {
                "genre": {"type": "string", "minLength": 3, "maxLength": 40},
                "tone": {"type": "string", "minLength": 3, "maxLength": 40},
                "player_role": {"type": "string", "minLength": 3, "maxLength": 60},
                "one_sentence_premise": {"type": "string", "minLength": 20, "maxLength": 140},
                "intro_premise": {"type": "string", "minLength": 20, "maxLength": 500},
                "atmosphere": {
                    "type": "object",
                    "properties": {
                        "time_of_day": {"type": "number", "minimum": 0, "maximum": 24},
                        "fog_intensity": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["time_of_day", "fog_intensity"],
                    "additionalProperties": False,
                },
                "experience": EXPERIENCE_SCHEMA,
                "narrator_setup": {"type": "string", "minLength": 20, "maxLength": 400},
                "title": {"type": "string", "minLength": 2, "maxLength": 80},
            },
            "required": ["genre", "tone", "player_role", "one_sentence_premise"],
            "additionalProperties": False,
        },
        "anchors": ANCHORS_SCHEMA["properties"]["anchors"],
        "clues": CLUES_SCHEMA["properties"]["clues"],
        "chapters": CHAPTERS_SCHEMA["properties"]["chapters"],
        "npcs": {
            "type": "array",
            "minItems": 6,
            "maxItems": 7,
            "items": {
                "type": "object",
                "properties": {
                    **NPCS_SCHEMA["properties"]["npcs"]["items"]["properties"],
                    "chapter_states": NPC_CHAPTER_STATES_SCHEMA["properties"]["chapter_states"],
                },
                "required": list(NPCS_SCHEMA["properties"]["npcs"]["items"]["required"]) + ["chapter_states"],
                "additionalProperties": False,
            }
        },
        "ending": ENDING_SCHEMA,
        "quality_report": EVAL_SCHEMA,
        "validation_report": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "issues": {"type": "array", "minItems": 0, "maxItems": 120, "items": {"type": "string", "minLength": 6, "maxLength": 260}},
            },
            "required": ["ok", "issues"],
            "additionalProperties": False,
        }
    },
    "required": ["meta", "anchors", "clues", "chapters", "npcs", "ending", "quality_report", "validation_report"],
    "additionalProperties": False,
}


# ---------------- Validation / fix helpers ----------------
def chapter_index(ch_id: str) -> int:
    try:
        return int(ch_id.split("_")[1])
    except Exception:
        return 999


def closest_id(x: str, allowed: List[str]) -> str:
    if x in allowed:
        return x
    m = get_close_matches(x, allowed, n=1, cutoff=0.65)
    return m[0] if m else x


def uniq_ids(items: List[Dict[str, Any]]) -> bool:
    ids = [it.get("id") for it in items]
    return len(ids) == len(set(ids))


def ensure_complete_sentence(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    end_chars = ".!?\"'\u201c\u201d\u2018\u2019"
    if t[-1] in end_chars:
        return t
    # truncate back to last end char
    last_end = -1
    for i in range(len(t) - 1, -1, -1):
        if t[i] in end_chars:
            last_end = i + 1
            break
    if last_end > 0:
        return t[:last_end].rstrip()
    return t.rstrip().rstrip(",") + "."


def validate_spec(spec: Dict[str, Any]) -> List[str]:
    """
    Cross-field checks:
    - counts, unique ids
    - references (npc->anchor, clue->anchor, chapter->npc/clue/anchor)
    - chapters sequential
    - clue partition across chapters
    - entry/exit gating correctness
    - npc chapter_states alignment and no future clue references
    - anchor placeability (no dependency-heavy entities)
    - ending trigger validity
    """
    issues: List[str] = []

    anchors = spec.get("anchors", [])
    clues = spec.get("clues", [])
    chapters = spec.get("chapters", [])
    npcs = spec.get("npcs", [])
    ending = spec.get("ending")

    # counts
    if not (6 <= len(anchors) <= 12):
        issues.append(f"anchors count must be 6–12 (got {len(anchors)})")
    if not (10 <= len(clues) <= 14):
        issues.append(f"clues count must be 10–14 (got {len(clues)})")
    if not (6 <= len(npcs) <= 7):
        issues.append(f"npcs count must be 6–7 (got {len(npcs)})")
    if not (3 <= len(chapters) <= 4):
        issues.append(f"chapters count must be 3–4 (got {len(chapters)})")

    # uniqueness
    if not uniq_ids(anchors):
        issues.append("anchors have duplicate ids")
    if not uniq_ids(clues):
        issues.append("clues have duplicate ids")
    if not uniq_ids(npcs):
        issues.append("npcs have duplicate ids")

    anchor_ids = [a["id"] for a in anchors if "id" in a]
    clue_ids = [c["id"] for c in clues if "id" in c]
    npc_ids = [n["id"] for n in npcs if "id" in n]
    anchor_set, clue_set, npc_set = set(anchor_ids), set(clue_ids), set(npc_ids)

    meta = spec.get("meta") or {}
    exp = meta.get("experience") if isinstance(meta.get("experience"), dict) else {}
    if exp.get("first_objective_npc_id") and exp["first_objective_npc_id"] not in npc_set:
        issues.append(
            f"meta.experience.first_objective_npc_id must be a valid npc id (got {exp['first_objective_npc_id']})"
        )

    # anchor placeability
    bad_anchors: List[str] = []
    for a in anchors:
        w = anchor_has_forbidden_dependency(a)
        if w:
            bad_anchors.append(f"{a.get('id')}({w})")
    if bad_anchors:
        issues.append(f"anchor_placeability_forbidden: {bad_anchors}")

    # anchor small-prop: must be major placeable objects only
    small_prop_anchors: List[str] = []
    for a in anchors:
        w = anchor_has_small_prop(a)
        if w:
            small_prop_anchors.append(f"{a.get('id')}({w})")
    if small_prop_anchors:
        issues.append(f"anchor_small_prop_forbidden: {small_prop_anchors}")

    # references
    for c in clues:
        if c.get("anchor_id") not in anchor_set:
            issues.append(f"clue {c.get('id')} references unknown anchor_id {c.get('anchor_id')}")
    for n in npcs:
        if n.get("anchor_id") not in anchor_set:
            issues.append(f"npc {n.get('id')} references unknown anchor_id {n.get('anchor_id')}")
        if n.get("pose") != "standing":
            issues.append(f"npc {n.get('id')} pose must be standing")

    # chapters sequential
    chapters_sorted = sorted(chapters, key=lambda ch: chapter_index(ch.get("id", "")))
    expected = [f"chapter_{i}" for i in range(1, len(chapters_sorted) + 1)]
    got = [ch.get("id") for ch in chapters_sorted]
    if got != expected:
        issues.append(f"chapter ids must be sequential {expected} (got {got})")

    # clue usage across chapters: no duplicate (each clue at most one chapter); allow unused clues
    seen: List[str] = []
    for ch in chapters:
        seen.extend([cid for cid in ch.get("available_clue_ids", []) if isinstance(cid, str)])
    seen_set = set(seen)
    dups = sorted([x for x in seen_set if seen.count(x) > 1])
    if dups:
        issues.append(f"available_clue_ids duplicates across chapters: {dups}")
    invalid = sorted([cid for cid in seen_set if cid not in clue_set])
    if invalid:
        issues.append(f"available_clue_ids invalid clue ids: {invalid}")

    # chapter gates
    clue_anchor = {c["id"]: c.get("anchor_id") for c in clues if "id" in c}
    npc_to_anchor = {n["id"]: n.get("anchor_id") for n in npcs if "id" in n}
    cumulative: Set[str] = set()
    cumulative_by_ch: Dict[str, Set[str]] = {}
    spotlighted: Set[str] = set()

    for ch in chapters_sorted:
        ch_id = ch["id"]
        avail = set(ch.get("available_clue_ids", []))
        exit_req = set(ch.get("exit_require_all_clues", []))
        exit_list = ch.get("exit_require_all_clues", [])
        entry_all = set(ch.get("entry_require_all_clues", []))
        entry_any = set(ch.get("entry_require_any_clues") or [])
        spotlight_ids = ch.get("spotlight_npc_ids", [])

        if ch_id == "chapter_1":
            if entry_all or entry_any:
                issues.append("chapter_1 entry requirements must be empty")
        else:
            if not entry_all.issubset(cumulative):
                issues.append(f"{ch_id}: entry_require_all_clues must come from earlier chapters")
            if not entry_any.issubset(cumulative):
                issues.append(f"{ch_id}: entry_require_any_clues must come from earlier chapters")

        if not exit_req.issubset(avail):
            issues.append(f"{ch_id}: exit_require_all_clues must be subset of available_clue_ids")
        # One exit clue per spotlight NPC (exit tag): clear progression
        if len(exit_list) != len(spotlight_ids):
            issues.append(
                f"{ch_id}: exit_require_all_clues must have exactly one clue per spotlight NPC "
                f"(got {len(exit_list)} exit clues for {len(spotlight_ids)} spotlight NPCs)"
            )
        else:
            # Each exit clue must be at a different spotlight NPC's anchor
            exit_anchors = [clue_anchor.get(cid) for cid in exit_list]
            spotlight_anchors = [npc_to_anchor.get(nid) for nid in spotlight_ids]
            if sorted(exit_anchors) != sorted(spotlight_anchors):
                issues.append(
                    f"{ch_id}: each exit_require_all_clues clue must be at a spotlight NPC's anchor; "
                    f"exit clue anchors {exit_anchors} vs spotlight NPC anchors {spotlight_anchors}"
                )

        # available_clue_ids must equal exit_require_all_clues (only exit clues per chapter)
        if set(ch.get("available_clue_ids", [])) != set(exit_list):
            issues.append(
                f"{ch_id}: available_clue_ids must equal exit_require_all_clues (only exit clues in this chapter)"
            )
        if len(ch.get("available_clue_ids", [])) != len(spotlight_ids):
            issues.append(
                f"{ch_id}: len(available_clue_ids) must equal len(spotlight_npc_ids) (got {len(ch.get('available_clue_ids', []))} vs {len(spotlight_ids)})"
            )

        for nid in spotlight_ids:
            if nid not in npc_set:
                issues.append(f"{ch_id}: spotlight_npc_ids contains unknown npc_id {nid}")
            spotlighted.add(nid)
        for aid in ch.get("available_anchor_ids", []):
            if aid not in anchor_set:
                issues.append(f"{ch_id}: available_anchor_ids contains unknown anchor_id {aid}")

        # anchors should include the anchors that host this chapter's clues
        ch_anchor_set = set(ch.get("available_anchor_ids", []))
        for cid in ch.get("available_clue_ids", []):
            a = clue_anchor.get(cid)
            if a and a not in ch_anchor_set:
                issues.append(f"{ch_id}: available_anchor_ids should include anchor {a} (hosts clue {cid})")

        cumulative |= avail
        cumulative_by_ch[ch_id] = set(cumulative)

    never_spotlight = npc_set - spotlighted
    if never_spotlight:
        issues.append(
            f"Each NPC must be spotlight in at least one chapter; never spotlighted: {sorted(never_spotlight)}"
        )

    # npc chapter_states alignment and no future clue references
    for n in npcs:
        states = n.get("chapter_states", [])
        if len(states) != len(chapters_sorted):
            issues.append(f"npc {n.get('id')}: chapter_states length must match chapters length")
            continue
        by = {st.get("chapter_id"): st for st in states if isinstance(st, dict)}
        for ch in chapters_sorted:
            ch_id = ch["id"]
            st = by.get(ch_id)
            if not st:
                issues.append(f"npc {n.get('id')}: missing chapter_state for {ch_id}")
                continue
            allowed = cumulative_by_ch.get(ch_id, set())
            any_req = set(st.get("reacts_to_clues_any") or [])
            all_req = set(st.get("reacts_to_clues_all") or [])
            if not any_req.issubset(allowed):
                issues.append(f"npc {n.get('id')} {ch_id}: reacts_to_clues_any references future/unknown clues")
            if not all_req.issubset(allowed):
                issues.append(f"npc {n.get('id')} {ch_id}: reacts_to_clues_all references future/unknown clues")

    # ending validation
    if not isinstance(ending, dict):
        issues.append("ending missing or invalid")
    else:
        last = chapters_sorted[-1] if chapters_sorted else None
        if last:
            trig = ending.get("trigger", {})
            if trig.get("chapter_id") != last.get("id"):
                issues.append("ending.trigger.chapter_id must equal final chapter id")
            # Must match the final chapter exit requirements exactly (so engine can trigger reliably)
            if sorted(trig.get("requires_all_clues", [])) != sorted(last.get("exit_require_all_clues", [])):
                issues.append("ending.trigger.requires_all_clues must equal final chapter exit_require_all_clues")
        txt = ensure_complete_sentence(str(ending.get("black_screen_text", "")))
        if len(txt) < 120:
            issues.append("ending.black_screen_text too short")
        if txt != ending.get("black_screen_text", ""):
            issues.append("ending.black_screen_text must end with a complete sentence")

    return issues


def local_fix_spec(spec: Dict[str, Any], lg: logging.Logger) -> Dict[str, Any]:
    """
    Conservative local repairs:
    - rewrite invalid anchor/npc/clue references to closest matches
    - enforce clue partition uniqueness + assign missing clues to earliest chapter
    - clamp entry requirements to earlier chapters
    - ensure chapter anchors include anchors hosting its clues
    - clamp npc chapter-state clue references to <= current chapter
    - enforce npc pose=standing
    - ensure ending punctuation
    """
    anchors = spec.get("anchors", [])
    clues = spec.get("clues", [])
    chapters = spec.get("chapters", [])
    npcs = spec.get("npcs", [])
    ending = spec.get("ending") or {}

    anchor_ids = [a["id"] for a in anchors if "id" in a]
    clue_ids = [c["id"] for c in clues if "id" in c]
    npc_ids = [n["id"] for n in npcs if "id" in n]

    anchor_set, clue_set = set(anchor_ids), set(clue_ids)

    # Fix clue->anchor
    for c in clues:
        if c.get("anchor_id") not in anchor_set and anchor_ids:
            c["anchor_id"] = closest_id(c.get("anchor_id", ""), anchor_ids)

    # Fix npc->anchor + pose + Infocom fields (backward compat)
    for n in npcs:
        if n.get("anchor_id") not in anchor_set and anchor_ids:
            n["anchor_id"] = closest_id(n.get("anchor_id", ""), anchor_ids)
        n["pose"] = "standing"
        if not n.get("protected_truth"):
            n["protected_truth"] = n.get("private_truth", "Something they keep hidden.")[:220]
        if not n.get("misleading_claim"):
            n["misleading_claim"] = n.get("lie_style", "A deflection they use.")[:180]
        if not n.get("voice_style"):
            n["voice_style"] = "Guarded, evasive when pressed."

    # Fix chapter_states tension_state (backward compat)
    for n in npcs:
        for st in n.get("chapter_states", []):
            if not st.get("tension_state"):
                st["tension_state"] = "Concealing"

    # Fix ending open_thread (backward compat)
    if isinstance(ending, dict) and not ending.get("open_thread"):
        ending["open_thread"] = "Something remains unexplained."

    # Fix chapter references
    for ch in chapters:
        if npc_ids:
            ch["spotlight_npc_ids"] = [closest_id(x, npc_ids) for x in ch.get("spotlight_npc_ids", [])]
        if anchor_ids:
            ch["available_anchor_ids"] = [closest_id(x, anchor_ids) for x in ch.get("available_anchor_ids", [])]
        if clue_ids:
            ch["available_clue_ids"] = [closest_id(x, clue_ids) for x in ch.get("available_clue_ids", [])]
            ch["entry_require_all_clues"] = [closest_id(x, clue_ids) for x in ch.get("entry_require_all_clues", [])]
            if ch.get("entry_require_any_clues") is None:
                pass
            else:
                ch["entry_require_any_clues"] = [closest_id(x, clue_ids) for x in (ch.get("entry_require_any_clues") or [])]
            ch["exit_require_all_clues"] = [closest_id(x, clue_ids) for x in ch.get("exit_require_all_clues", [])]

    # Enforce clue partition
    chapters_sorted = sorted(chapters, key=lambda c: chapter_index(c.get("id", "")))
    assigned: Set[str] = set()
    for ch in chapters_sorted:
        fixed = []
        for cid in ch.get("available_clue_ids", []):
            if cid in clue_set and cid not in assigned:
                fixed.append(cid)
                assigned.add(cid)
        ch["available_clue_ids"] = fixed

    # Do not assign unused clues to chapter_1; each chapter keeps only exit clues (set below)

    # Clamp entry/exit gates and enforce one exit clue per spotlight NPC
    clue_anchor = {c["id"]: c.get("anchor_id") for c in clues if "id" in c}
    npc_to_anchor = {n["id"]: n.get("anchor_id") for n in npcs if "id" in n}
    cumulative: Set[str] = set()
    for ch in chapters_sorted:
        ch_id = ch.get("id", "")
        avail = set(ch.get("available_clue_ids", []))
        avail_list = ch.get("available_clue_ids", [])

        if ch_id == "chapter_1":
            ch["entry_require_all_clues"] = []
            ch["entry_require_any_clues"] = []
        else:
            ch["entry_require_all_clues"] = [cid for cid in ch.get("entry_require_all_clues", []) if cid in cumulative]
            if ch.get("entry_require_any_clues") is None:
                pass
            else:
                ch["entry_require_any_clues"] = [cid for cid in (ch.get("entry_require_any_clues") or []) if cid in cumulative]

        # Enforce one exit clue per spotlight NPC (exit tag)
        spotlight_ids = ch.get("spotlight_npc_ids", [])
        exit_fixed: List[str] = []
        for nid in spotlight_ids:
            want_anchor = npc_to_anchor.get(nid)
            if not want_anchor:
                continue
            # First clue in this chapter at this NPC's anchor
            for cid in avail_list:
                if clue_anchor.get(cid) == want_anchor:
                    exit_fixed.append(cid)
                    break
        if len(exit_fixed) == len(spotlight_ids):
            ch["exit_require_all_clues"] = exit_fixed
        else:
            # Keep existing if subset of avail, but trim to one per spotlight if we have extra
            current = [cid for cid in ch.get("exit_require_all_clues", []) if cid in avail]
            if len(current) > len(spotlight_ids):
                ch["exit_require_all_clues"] = exit_fixed if exit_fixed else current[: len(spotlight_ids)]
            else:
                ch["exit_require_all_clues"] = exit_fixed if exit_fixed else current

        # Each chapter has only exit clues (one per spotlight NPC)
        ch["available_clue_ids"] = list(ch.get("exit_require_all_clues", []))
        cumulative |= set(ch["available_clue_ids"])

    # Reassign exit clues' anchor_id to spotlight NPCs' anchors so exit clue i is at spotlight i's anchor
    clue_by_id = {c["id"]: c for c in clues if "id" in c}
    for ch in chapters_sorted:
        exit_list = ch.get("exit_require_all_clues", [])
        spotlight_ids = ch.get("spotlight_npc_ids", [])
        for i in range(min(len(exit_list), len(spotlight_ids))):
            cid = exit_list[i]
            nid = spotlight_ids[i]
            want_anchor = npc_to_anchor.get(nid)
            if want_anchor and cid in clue_by_id:
                clue_by_id[cid]["anchor_id"] = want_anchor
    clue_anchor = {c["id"]: c.get("anchor_id") for c in clues if "id" in c}

    # Ensure chapter anchors include anchors that host its clues
    for ch in chapters_sorted:
        ch_anchors = list(dict.fromkeys(ch.get("available_anchor_ids", [])))
        ch_anchor_set = set(ch_anchors)
        for cid in ch.get("available_clue_ids", []):
            aid = clue_anchor.get(cid)
            if aid and aid not in ch_anchor_set:
                ch_anchors.append(aid)
                ch_anchor_set.add(aid)
        ch["available_anchor_ids"] = ch_anchors[:10]

    # Clamp npc chapter-state clue references
    cumulative = set()
    cumulative_by_ch: Dict[str, Set[str]] = {}
    for ch in chapters_sorted:
        cumulative |= set(ch.get("available_clue_ids", []))
        cumulative_by_ch[ch["id"]] = set(cumulative)

    for n in npcs:
        states = n.get("chapter_states", [])
        by = {st.get("chapter_id"): st for st in states if isinstance(st, dict)}
        for ch in chapters_sorted:
            ch_id = ch["id"]
            st = by.get(ch_id)
            if not st:
                continue
            allowed = cumulative_by_ch.get(ch_id, set())
            if st.get("reacts_to_clues_any") is None:
                pass
            else:
                st["reacts_to_clues_any"] = [cid for cid in (st.get("reacts_to_clues_any") or []) if cid in allowed]
            if st.get("reacts_to_clues_all") is None:
                pass
            else:
                st["reacts_to_clues_all"] = [cid for cid in (st.get("reacts_to_clues_all") or []) if cid in allowed]

    # Ending punctuation
    if isinstance(ending, dict) and "black_screen_text" in ending:
        ending["black_screen_text"] = ensure_complete_sentence(str(ending.get("black_screen_text", "")))
    spec["ending"] = ending

    spec["chapters"] = chapters_sorted
    return spec


def rule_based_quality_signals(spec: Dict[str, Any]) -> List[str]:
    chapters = spec.get("chapters", [])
    clues = spec.get("clues", [])
    npcs = spec.get("npcs", [])
    key = [c for c in clues if c.get("key_for_progress") is True]
    exit_total = sum(len(ch.get("exit_require_all_clues", [])) for ch in chapters)
    signals: List[str] = []
    if len(key) < 3:
        signals.append("Few key_for_progress clues; chapter gates may feel arbitrary.")
    if exit_total < max(2, len(chapters) - 1):
        signals.append("Very weak exit requirements; chapters may not feel earned.")
    if len({n.get("anchor_id") for n in npcs}) < min(4, len(npcs)):
        signals.append("Many NPCs share the same anchor; the world may feel cramped.")
    if not isinstance(spec.get("ending"), dict) or len(str(spec.get("ending", {}).get("black_screen_text", ""))) < 120:
        signals.append("Ending cutscene is missing or too short.")
    return signals


def categorize_issues(issues: List[str]) -> Set[str]:
    """
    Decide which component(s) to repair based on validation messages.
    """
    cats: Set[str] = set()
    for s in issues:
        if "anchor_placeability_forbidden" in s or "anchor_small_prop_forbidden" in s or "anchors count" in s or "anchors have duplicate" in s:
            cats.add("anchors")
        if "clue " in s and "anchor_id" in s:
            cats.add("clues")
        if "npc " in s and ("anchor_id" in s or "pose" in s):
            cats.add("npcs")
        if "chapter" in s or "available_clue_ids" in s or "entry_require" in s or "exit_require" in s or "spotlight_npc_ids" in s or "available_anchor_ids" in s:
            cats.add("chapters")
        if "chapter_states" in s or "reacts_to_clues" in s or "missing chapter_state" in s:
            cats.add("npc_states")
        if s.startswith("ending.") or "ending " in s:
            cats.add("ending")
    return cats


def quality_problems_to_issues(quality_report: Dict[str, Any]) -> List[str]:
    """Convert quality_report.problems into issue strings for repair prompts."""
    problems = quality_report.get("problems") or []
    issues: List[str] = []
    for p in problems:
        if isinstance(p, dict) and "issue" in p and "fix" in p:
            sev = p.get("severity", "medium")
            issues.append(f"QUALITY ({sev}): {p['issue']} | Fix: {p['fix']}")
    return issues


def categorize_quality_problems(problems: List[Dict[str, Any]]) -> Set[str]:
    """Infer which repair categories might address these quality problems."""
    cats: Set[str] = set()
    for p in problems:
        if not isinstance(p, dict) or "issue" not in p:
            continue
        issue = str(p.get("issue", "")).lower()
        # NPC-related: voice, helpful, distinctness, tension
        if any(w in issue for w in ["npc", "voice", "helpful", "generic", "distinct", "tension", "conceal", "negotiat"]):
            cats.add("npcs")
            cats.add("npc_states")
        # Clue-related: exposition, anomaly
        if any(w in issue for w in ["clue", "exposition", "anomaly", "environmental"]):
            cats.add("clues")
        # Story/arc/ending: twist, premise, engagement, fun, dull
        if any(w in issue for w in ["ending", "twist", "premise", "arc", "engagement", "fun", "dull", "predictable", "flat"]):
            cats.add("chapters")
            cats.add("ending")
    if not cats:
        cats = {"npcs", "npc_states", "clues", "chapters", "ending"}
    return cats


# ---------------- Prompts ----------------
SYSTEM = """You are a narrative designer for an Infocom-style, talk-only, outdoor mystery game.

Infocom design philosophy: Design for tension, curiosity, momentum—not geography. Every important NPC is in a situation (Concealing, Negotiating, Desperate, Testing the player, Buying time, Misdirecting, Protecting someone), never neutral. Show anomalies, not exposition: a ruined statue beats "The kingdom fell because of corruption." Resist making NPCs helpful. Complicated NPCs are gripping; helpful NPCs kill immersion.

Hard constraints:
- Outdoors only. No interiors. No combat.
- The world is static: anchors/buildings/landmarks are placed once and never move.
- EVERY anchor must be a solid, discrete entity that occupies one or more 2D grid cells.
  NO hanging objects (e.g. hanging lantern, chandelier), NO paths/trails/roads as anchors, NO floating/suspended structures.
  DO NOT use bridges, rivers, docks, piers, lakes, oceans, cliffs, canyons, caves, tunnels, etc.
  Every anchor must be a MAJOR placeable object matching the STORY'S region and architecture (e.g. Japanese village: village gate, shrine steps, wooden storehouse, stone lantern base as landmark—not European chapel unless the story is European). Examples by setting: torii or wooden gate, shed, statue, well, memorial tree, fountain, bulletin board, compound wall. Do NOT use small props: lanterns, lamps, streetlamps, signposts, barrels, crates, carts, debris.
- NPCs are ALWAYS standing next to their anchor.
- Clues are discovered ONLY by talking to NPCs. No environmental clues—every clue is revealed through conversation.
- 6–7 NPCs. 3–4 chapters max. Escalating tension.
- Ending: once final chapter exit clues are collected, show a BLACK SCREEN narrator cutscene.
"""

OPENING_IMAGE_PROMPT_SYSTEM = """You write ONE Imagen prompt: a single cinematic outdoor establishing shot for a mystery game. No text in the image.

SETTING LOCK (mandatory): The shot MUST match the story's exact geography, era, and ARCHITECTURE. Name the region/culture in the prompt (e.g. rural Japan, Edo-period village, Mediterranean coast). Every building and landmark must fit that place—do NOT default to European stone church, Gothic cathedral, Victorian street, or generic Western village unless the story explicitly is that. If the story is Japanese (or any non-Western setting), show appropriate roofs, materials, and forms (wood, tile, local vernacular)—never substitute a European church or castle.

Output plain text, one or two sentences, max 420 characters."""

# Injected after plan exists so all UI Imagen calls share the same lock.
IMAGEN_SETTING_LOCK_USER = """SETTING LOCK: Architecture and vibe MUST match the story and plan below. Use only buildings, materials, and landscape appropriate to that place and era. Forbidden unless the story says so: European Gothic church, stone cathedral, Western medieval town square, Victorian terrace. Name the culture/region in your prompt (e.g. "traditional Japanese mountain village, wooden farmhouses")."""

PLAN_PROMPT = """Given the vague story, write a compact plan (plain text):
- setting + player role: include EXPLICIT geography, era, and architectural vernacular (e.g. "Japanese mountain village, Edo-period timber farmhouses" not just "village")
- 6–12 outdoor anchors: each a major placeable object that fits THAT setting (same architecture as above—no generic "chapel" if the story is Japan; use shrine steps, village gate, storehouse, etc.). Do NOT use small props: lanterns, lamps, signposts, barrels, crates, carts, debris. NO hanging/floating objects, NO paths/trails; no environment dependencies (bridges/rivers)
- 6–7 NPCs each tied to an anchor (standing there). For each NPC, define their situation per chapter (what they're trying to do/hide/achieve), not just where they stand.
- 3–4 chapters with escalation and a clear final twist
- 10–14 clues revealed by NPCs during conversation. Every clue must be at an anchor where an NPC stands.
Keep it tight and specific.

STORY:
"""

ANCHORS_PROMPT = """From the plan, output ANCHORS JSON.

Rules:
- 6–12 anchors
- ids snake_case
- Each anchor must be a solid, discrete entity that occupies 1+ grid cells on a 2D square grid.
- Every anchor must be a major placeable object whose type fits the plan's setting (no European chapel in a Japanese village—use shrine platform, wooden gate, storehouse, etc.). Do NOT use small props: barrels, crates, carts, lanterns, lamps, streetlamps, signposts, debris.
- NO hanging objects (hanging lantern, chandelier), NO paths/trails/roads as anchors, NO floating/suspended structures.
- anchors must be outdoors, standalone, and placeable without dependencies
- DO NOT include: bridge/river/dock/pier/lake/ocean/cliff/cave/tunnel etc.
- placement_notes must explain how to place it in a flat outdoor scene (path edge, near fence, under tree, beside wall, etc.)
Return JSON only.

PLAN:
"""

CLUES_PROMPT = """From the plan and anchors, output CLUES JSON.

Rules:
- 10–14 clues
- Each clue MUST reference a valid anchor_id
- Each clue MUST be at an anchor that has an NPC. No environmental-only clues. The player discovers clues only by talking to NPCs at those anchors.
- Spread clues across NPC anchors so that no anchor has an overwhelming share of clues; this helps each NPC have something to give in conversation.
- interaction field: how the NPC might describe or reference this clue in conversation
- key_for_progress=true for some clues used to gate chapter progression
Return JSON only.

ANCHOR IDS:
{anchor_ids}

PLAN:
{plan}
"""

NPCS_PROMPT = """From the plan and anchors, output NPC JSON.

Rules:
- 6–7 NPCs
- Each NPC MUST reference a valid anchor_id where they stand
- pose MUST be "standing"
- Names, roles, dress, and speech flavor MUST fit the plan's setting (era + culture)—not generic fantasy/Western unless the story is that
- Distinct voices, motives, contradictions
- Each NPC needs: protected_truth (what they will resist revealing; distinct from private_truth which is what they know), misleading_claim (something they confidently say that isn't fully true), voice_style (conversational rhythm: short vs winding, concrete vs abstract, direct vs evasive—e.g. "Short, concrete. Evasive when pressed.")
- Every anchor with a clue MUST have an NPC. All clues are conversation-gated. Distribute NPCs so every clue anchor has an NPC to talk to.
Return JSON only.

ANCHOR IDS:
{anchor_ids}

PLAN:
{plan}
"""

CHAPTERS_PROMPT = """Create 3–4 chapters and set up clue-gated progression.

Rules:
- chapter ids must be chapter_1 .. chapter_N (sequential)
- event_beats: write as anomalies and behavioral shifts—"Guard avoids saying the mayor's name" not "The mayor is corrupt."
- narration: evocative, second-person-appropriate. Avoid generic summaries.
- available_clue_ids must contain EXACTLY the exit clues for this chapter—no other clues. So available_clue_ids MUST equal exit_require_all_clues and have length = len(spotlight_npc_ids). Do not add any other clues to available_clue_ids. (Some clues in the global list may be unused in any chapter.)
- Every clue in available_clue_ids must be at an anchor with an NPC. All clues are obtained by talking to NPCs.
- spotlight_npc_ids: exactly 1–2 NPCs per chapter whose anchors hold this chapter's "exit" clues. Each NPC must appear in at least one chapter.
- exit_require_all_clues = ONE clue per spotlight NPC (the "exit tag" for that chapter). So len(exit_require_all_clues) MUST equal len(spotlight_npc_ids). Use the CLUE→ANCHOR and NPC→ANCHOR mappings below: for each chapter, after choosing spotlight_npc_ids, set exit_require_all_clues to exactly those clues that are at those NPCs' anchors (one clue per spotlight NPC; order by spotlight order). Only list as exit clues clues whose anchor_id equals the anchor of a chosen spotlight NPC.
- entry_require_all_clues / entry_require_any_clues gate entering a chapter:
  * chapter_1 entry requirements MUST be empty
  * later chapters can only require clues from earlier chapters
- available_anchor_ids should include anchors that host the chapter's clues
- Each NPC must be spotlight in at least one chapter. The same NPC may be spotlight in multiple chapters (e.g. a key character in chapters 1 and 3).
Return JSON only.

CLUE TO ANCHOR (each clue is at exactly one anchor):
{clue_anchor_map}

NPC TO ANCHOR (each NPC stands at one anchor):
{npc_anchor_map}

NPC IDS:
{npc_ids}

ANCHOR IDS:
{anchor_ids}

CLUE IDS:
{clue_ids}

PLAN:
{plan}
"""

NPC_CHAPTER_STATES_PROMPT = """For this NPC, define how they behave in EACH chapter.

Rules:
- Return chapter_states length MUST equal number of chapters
- For each chapter_state, set tension_state to one of: Concealing, Negotiating, Desperate, Testing the player, Buying time, Misdirecting, Protecting someone. Never neutral.
- reveal_cost (optional): what must happen for full reveal—high trust, risky player action, sacrificing another relationship, time pressure. Do not allow full reveal without cost.
- evasive and pressured sample_lines should use soft resistance: half-answers, deflected questions, emotional deflection. Make the player work socially.
- reacts_to_clues_any / reacts_to_clues_all can only mention clues available up through that chapter
- Keep it consistent with the NPC profile and the chapter events
Return JSON only.

NPC PROFILE:
{npc_profile}

CHAPTERS (ordered):
{chapters}

ALL CLUE IDS (ordered):
{clue_ids}
"""

ENDING_PROMPT = """Write the ending "black screen" narrator cutscene.

Rules:
- This is shown AFTER the player collects the final chapter's exit clues.
- Output JSON with fields:
  - title
  - trigger object with fields: chapter_id, requires_all_clues
    (must match final chapter id and its exit_require_all_clues exactly)
  - black_screen_text: 50–90 words, tense, clear resolution, ends with a complete sentence. Single paragraph. No multiple paragraphs.
  - open_thread: One lingering uncertainty after resolution—missing name, implication of larger force, doubt about motive. Mystery lives past resolution. 20–120 chars.
- Do not invent new locations. Use the existing anchors and characters.
Return JSON only.

PLAN:
{plan}

CHAPTERS (ordered):
{chapters}

FINAL CHAPTER EXIT CLUES (must match trigger.requires_all_clues):
{final_exit_clues}
"""


EVAL_PROMPT = """Evaluate the narrative spec.

You are grading playability and tension for a talk-only, clue-driven outdoor mystery.
The overall story is supposed to give a fun experience for the player.
Score 0–100 overall, plus subscores 0–10 (all required): coherence, pacing, clue_fairness, npc_distinctness, solvability, player_agency, tension, voice_distinctness, anomaly_over_exposition, engagement.

Focus on:
- coherence and escalation
- clue fairness and gating (no dead-ends; progress clues discoverable)
- NPC distinctness (voices, motives, contradictions)
- solvability (player can logically reach the twist)
- ending quality (black screen narrator cutscene feels earned and clear)
- tension: Are NPCs in active situations (Concealing, Negotiating, etc.), not neutral?
- voice_distinctness: Do NPCs sound different from each other?
- anomaly_over_exposition: Are clues/narration shown (anomalies) vs told (exposition)?
- engagement: Would players find this fun to play? Is the premise, twist, and arc compelling? Or does it feel predictable, flat, or dull?

In problems, flag: "NPC sounds too helpful or generic", "Exposition instead of anomaly", "All NPCs sound the same", "Story may not be fun: [reason]" (e.g. premise predictable, twist telegraphed, arc flat), "Overall experience feels dull or unengaging".

Return JSON only.

PLAN:
{plan}

SPEC JSON:
{spec_json}
"""

# Targeted repair prompts (small outputs)
REPAIR_ANCHORS_PROMPT = """Repair ONLY the anchors JSON to satisfy constraints and fix the listed issues.
QUALITY lines are evaluator critique—address them where your scope allows.

Rules:
- 6–12 anchors
- ids snake_case (keep stable if possible)
- Each anchor must be a solid, discrete entity that occupies 1+ grid cells on a 2D square grid.
- Every anchor must be a major placeable object. Do NOT use small props: barrels, crates, carts, lanterns, lamps, streetlamps, signposts, debris.
- NO hanging objects (hanging lantern), NO paths/trails/roads as anchors, NO floating/suspended structures.
- anchors must be outdoors, standalone, and placeable WITHOUT dependencies
- DO NOT include bridge/river/dock/pier/lake/ocean/cliff/cave/tunnel etc.
- placement_notes must describe simple placement in a flat outdoor scene
Return JSON only.

ISSUES:
{issues}

CURRENT ANCHORS JSON:
{current_anchors}
"""

REPAIR_CHAPTERS_PROMPT = """Repair ONLY the chapters JSON to satisfy constraints and fix the listed issues.
QUALITY lines are evaluator critique—address them where your scope allows.

Rules:
- chapter ids sequential chapter_1..chapter_N (3–4 chapters)
- available_clue_ids must contain EXACTLY the exit clues for that chapter (available_clue_ids = exit_require_all_clues; length = len(spotlight_npc_ids)). Do not add any other clues. Some clues may be unused in any chapter.
- Every clue in available_clue_ids must be at an anchor with an NPC (all clues from conversation)
- chapter_1 entry requirements empty
- later chapter entry requirements only use earlier chapter clues
- exit requirements subset of that chapter's available_clue_ids
- Use the CLUE→ANCHOR and NPC→ANCHOR mappings below: exit_require_all_clues must be exactly those clues that are at the chosen spotlight_npc_ids' anchors (one clue per spotlight NPC; order by spotlight order). Only list as exit clues clues whose anchor_id equals the anchor of a chosen spotlight NPC.
- available_anchor_ids must include anchors hosting the chapter's clues
- spotlight_npc_ids must be valid npc ids; each NPC must appear in at least one chapter's spotlight_npc_ids
Return JSON only.

CLUE TO ANCHOR (each clue is at exactly one anchor):
{clue_anchor_map}

NPC TO ANCHOR (each NPC stands at one anchor):
{npc_anchor_map}

ISSUES:
{issues}

NPC IDS:
{npc_ids}

ANCHOR IDS:
{anchor_ids}

CLUE IDS:
{clue_ids}

CURRENT CHAPTERS JSON:
{current_chapters}
"""

REPAIR_CLUES_PROMPT = """Repair ONLY the clues JSON to satisfy constraints and fix the listed issues.
QUALITY lines are evaluator critique—address them where your scope allows.

Rules:
- Keep clue ids stable if possible (do not rename unless absolutely necessary).
- 10–14 clues
- Each clue.anchor_id must be one of ANCHOR IDS
- Each clue must be discoverable by interacting with that anchor (interaction field)
- key_for_progress should be true for some clues used to gate progress
Return JSON only.

ISSUES:
{issues}

ANCHOR IDS:
{anchor_ids}

CURRENT CLUES JSON:
{current_clues}
"""

REPAIR_NPCS_PROMPT = """Repair ONLY the NPCs JSON to satisfy constraints and fix the listed issues.
QUALITY lines are evaluator critique—address them where your scope allows.

Rules:
- Keep npc ids stable if possible (do not rename unless absolutely necessary).
- 6–7 NPCs
- Each npc.anchor_id must be one of ANCHOR IDS
- pose MUST be "standing"
- NPCs must stay outdoors and talk-only
- Include protected_truth, misleading_claim, voice_style for each NPC
Return JSON only.

ISSUES:
{issues}

ANCHOR IDS:
{anchor_ids}

CURRENT NPCS JSON:
{current_npcs}
"""

REPAIR_NPC_STATES_PROMPT = """Repair ONLY this NPC's chapter_states to satisfy constraints and fix the listed issues.
QUALITY lines are evaluator critique—address them where your scope allows.

Rules:
- chapter_states length must match number of chapters
- chapter_id must match provided chapter ids
- tension_state required per chapter: one of Concealing, Negotiating, Desperate, Testing the player, Buying time, Misdirecting, Protecting someone
- reveal_cost (optional): what must happen for full reveal
- reacts_to_clues_any/all cannot reference future clues:
  * for chapter_k, it may reference clues from chapters 1..k only
Return JSON only.

ISSUES:
{issues}

NPC PROFILE:
{npc_profile}

CHAPTERS (ordered):
{chapters}

CLUE IDS:
{clue_ids}

CURRENT NPC STATES JSON:
{current_states}
"""

REPAIR_ENDING_PROMPT = """Repair ONLY the ending JSON to satisfy constraints and fix the listed issues.
QUALITY lines are evaluator critique—address them where your scope allows.

Rules:
- trigger.chapter_id must equal final chapter id
- trigger.requires_all_clues must equal final chapter exit_require_all_clues exactly
- black_screen_text 50–90 words, tense, clear, ends with a complete sentence. Single paragraph.
- open_thread: One lingering uncertainty after resolution (20–120 chars).
Return JSON only.

ISSUES:
{issues}

CHAPTERS (ordered):
{chapters}

FINAL CHAPTER EXIT CLUES:
{final_exit_clues}

CURRENT ENDING JSON:
{current_ending}
"""


# ---------------- Assembly helpers ----------------
def make_meta(
    story: str,
    plan: str,
    chapters: Optional[List[Dict[str, Any]]] = None,
    npcs: Optional[List[Dict[str, Any]]] = None,
    opening_image_filename: str = "",
) -> Dict[str, Any]:
    raw = story.strip().replace("\n", " ")
    short = (raw[:120] + "...") if len(raw) > 120 else raw
    short = short if len(short) >= 20 else (plan.strip().split("\n")[0][:140])
    intro = raw
    if len(intro) > 500:
        intro = intro[:497].rsplit(" ", 1)[0] + "..."
    intro = intro if len(intro) >= 20 else short
    meta: Dict[str, Any] = {
        "genre": "mystery",
        "tone": "tense",
        "player_role": "investigator",
        "one_sentence_premise": short,
        "intro_premise": intro,
        # Dialogue + art: keep LLM/imagen tied to same architecture (filled when plan known)
        "visual_setting_lock": (plan or "").strip()[:2200],
    }
    first_npc_id = ""
    first_obj_text = "Find someone to talk to and learn what happened here."
    if chapters and npcs:
        ch1 = next((c for c in chapters if c.get("id") == "chapter_1"), chapters[0] if chapters else None)
        if ch1:
            spot = ch1.get("spotlight_npc_ids") or []
            if spot:
                first_npc_id = str(spot[0])
                nmap = {n.get("id"): n for n in npcs}
                nm = nmap.get(first_npc_id, {})
                disp = nm.get("display_name") or first_npc_id
                first_obj_text = f"Speak with {disp} — they may know how to begin."
    exp: Dict[str, Any] = {}
    if opening_image_filename:
        exp["opening_image_path"] = opening_image_filename
    if first_npc_id:
        exp["first_objective_npc_id"] = first_npc_id
    exp["first_objective_text"] = first_obj_text[:320]
    if exp:
        meta["experience"] = exp
    return meta


def compact_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def spec_for_eval(spec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "meta": spec.get("meta"),
        "anchors": spec.get("anchors"),
        "clues": spec.get("clues"),
        "chapters": spec.get("chapters"),
        "npcs": spec.get("npcs"),
        "ending": spec.get("ending"),
    }


def compute_final_exit_clues(chapters: List[Dict[str, Any]]) -> List[str]:
    if not chapters:
        return []
    last = sorted(chapters, key=lambda c: chapter_index(c.get("id", "")))[-1]
    return list(last.get("exit_require_all_clues", []) or [])


# ---------------- Main pipeline ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", required=True, help="Vague story text or path to .txt/.json file containing story")
    ap.add_argument("--model", default=os.environ.get("GEMINI_MODEL", "gemini-2.5-pro"))
    ap.add_argument("--out", default="narrative_spec.json")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--log-level", default="INFO")
    ap.add_argument("--repair-iters", type=int, default=2)
    ap.add_argument("--max-output-tokens", type=int, default=2000)
    ap.add_argument("--quality-threshold", type=int, default=75, help="If eval overall_score < threshold, attempt targeted repairs.")
    ap.add_argument("--skip-opening-image", action="store_true", help="Skip Imagen opening still (opening.png).")
    ap.add_argument("--skip-ui-images", action="store_true", help="Skip narrator/hook text + setup/chapter/ending stills.")
    ap.add_argument("--parallel-npc-workers", type=int, default=3, help="Concurrent NPC chapter-state calls (rate-limit aware).")
    args = ap.parse_args()

    # Load story from file if path exists
    story = args.story
    if os.path.isfile(story):
        with open(story, "r", encoding="utf-8") as f:
            raw = f.read()
        if story.lower().endswith(".json"):
            try:
                data = json.loads(raw)
                story = data.get("story", data.get("content", data.get("main_mystery", raw))) or raw
            except json.JSONDecodeError:
                story = raw
        else:
            story = raw

    lg = setup_logger(args.log_level)
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "project-363d072c-3554-4f41-b1e")
    client = None
    out_dir = os.path.dirname(os.path.abspath(args.out)) or "."
    os.makedirs(out_dir, exist_ok=True)
    # 1) Plan (Vertex Gemini — single-shot pipeline, no multi-agent preflight)
    plan_user = PLAN_PROMPT + story
    plan = call_text(client, args.model, SYSTEM, plan_user, 0.7, "[PLAN]", lg, max_output_tokens=args.max_output_tokens)

    # Opening still: one text call for Imagen prompt, then Imagen (same dir as narrative_spec)
    opening_image_filename = ""
    if not args.skip_opening_image:
        try:
            lg.info("[OPENING_IMAGE] -> prompt (text) then Imagen")
            img_prompt = call_text(
                client,
                args.model,
                OPENING_IMAGE_PROMPT_SYSTEM,
                "STORY:\n" + story[:4000] + "\n\nPLAN:\n" + plan[:2500] + "\n\n" + IMAGEN_SETTING_LOCK_USER,
                0.5,
                "[OPENING_IMAGE prompt]",
                lg,
                max_output_tokens=256,
            ).strip()[:500]
            if len(img_prompt) >= 16:
                raw_img = gc.generate_image_bytes(img_prompt, aspect_ratio="16:9")
                open_path = os.path.join(out_dir, "opening.png")
                with open(open_path, "wb") as f:
                    f.write(raw_img)
                opening_image_filename = "opening.png"
                lg.info(f"[OPENING_IMAGE] <- wrote {open_path}")
        except Exception as e:
            lg.warning(f"[OPENING_IMAGE] skip: {e}")

    # 2) Anchors
    anchors_obj = call_json(client, args.model, SYSTEM, ANCHORS_PROMPT + plan, ANCHORS_SCHEMA, 0.4, "[ANCHORS]", lg, max_output_tokens=args.max_output_tokens)
    anchors = ensure_json_array(anchors_obj, "anchors", 6, 12, lg, "[ANCHORS]", None)
    if anchors is None:
        anchors_obj = call_json(
            client,
            args.model,
            SYSTEM,
            ANCHORS_PROMPT + plan + '\n\nCRITICAL: Output exactly {"anchors":[...]} with 6-12 anchors.',
            ANCHORS_SCHEMA,
            0.0,
            "[ANCHORS retry]",
            lg,
            max_output_tokens=args.max_output_tokens,
        )
        anchors = ensure_json_array(anchors_obj, "anchors", 6, 12, lg, "[ANCHORS retry]", None)
    if anchors is None:
        raise RuntimeError("ANCHORS: model returned no valid 'anchors' array after retry; check GEMINI_MODEL / quota.")
    anchor_ids = [a["id"] for a in anchors]

    # 3) Clues
    _clues_user = CLUES_PROMPT.format(anchor_ids=compact_json(anchor_ids), plan=plan)
    clues_obj = call_json(
        client, args.model, SYSTEM,
        _clues_user,
        CLUES_SCHEMA, 0.5, "[CLUES]", lg, max_output_tokens=args.max_output_tokens
    )
    clues = ensure_json_array(clues_obj, "clues", 10, 14, lg, "[CLUES]", None)
    if clues is None:
        clues_obj = call_json(
            client,
            args.model,
            SYSTEM,
            _clues_user + '\n\nCRITICAL: Output exactly {"clues":[...]} with 10-14 clues.',
            CLUES_SCHEMA,
            0.0,
            "[CLUES retry]",
            lg,
            max_output_tokens=args.max_output_tokens,
        )
        clues = ensure_json_array(clues_obj, "clues", 10, 14, lg, "[CLUES retry]", None)
    if clues is None:
        raise RuntimeError("CLUES: model returned no valid 'clues' array after retry.")
    clue_ids = [c["id"] for c in clues]

    # 4) NPCs
    _npcs_user = NPCS_PROMPT.format(anchor_ids=compact_json(anchor_ids), plan=plan)
    npcs_obj = call_json(
        client, args.model, SYSTEM,
        _npcs_user,
        NPCS_SCHEMA, 0.6, "[NPCS]", lg, max_output_tokens=args.max_output_tokens
    )
    npcs = ensure_json_array(npcs_obj, "npcs", 6, 7, lg, "[NPCS]", None)
    if npcs is None:
        npcs_obj = call_json(
            client,
            args.model,
            SYSTEM,
            _npcs_user + '\n\nCRITICAL: Output exactly {"npcs":[...]} with 6-7 NPCs.',
            NPCS_SCHEMA,
            0.0,
            "[NPCS retry]",
            lg,
            max_output_tokens=args.max_output_tokens,
        )
        npcs = ensure_json_array(npcs_obj, "npcs", 6, 7, lg, "[NPCS retry]", None)
    if npcs is None:
        raise RuntimeError("NPCS: model returned no valid 'npcs' array after retry.")
    npc_ids = [n["id"] for n in npcs]

    # 5) Chapters (pass clue→anchor and npc→anchor so LLM can pick exit clues at spotlight anchors)
    clue_anchor_map = ", ".join(f"{c.get('id', '')} at {c.get('anchor_id', '')}" for c in clues if c.get("id") and c.get("anchor_id"))
    npc_anchor_map = ", ".join(f"{n.get('id', '')} at {n.get('anchor_id', '')}" for n in npcs if n.get("id") and n.get("anchor_id"))
    _chapters_user = CHAPTERS_PROMPT.format(
        clue_anchor_map=clue_anchor_map,
        npc_anchor_map=npc_anchor_map,
        npc_ids=compact_json(npc_ids),
        anchor_ids=compact_json(anchor_ids),
        clue_ids=compact_json(clue_ids),
        plan=plan,
    )
    chapters_obj = call_json(
        client, args.model, SYSTEM,
        _chapters_user,
        CHAPTERS_SCHEMA, 0.4, "[CHAPTERS]", lg, max_output_tokens=args.max_output_tokens
    )
    chapters_list = ensure_json_array(chapters_obj, "chapters", 3, 4, lg, "[CHAPTERS]", None)
    if chapters_list is None:
        chapters_obj = call_json(
            client,
            args.model,
            SYSTEM,
            _chapters_user
            + '\n\nCRITICAL: Output a single JSON object with exactly one top-level key "chapters" whose value is an array of 3-4 chapter objects. Example: {"chapters":[{"id":"chapter_1",...},...]}',
            CHAPTERS_SCHEMA,
            0.0,
            "[CHAPTERS retry]",
            lg,
            max_output_tokens=args.max_output_tokens,
        )
        chapters_list = ensure_json_array(chapters_obj, "chapters", 3, 4, lg, "[CHAPTERS retry]", None)
    if chapters_list is None:
        raise RuntimeError("CHAPTERS: model returned no valid 'chapters' array after retry.")
    chapters = sorted(chapters_list, key=lambda c: chapter_index(c["id"]))

    # 6) NPC chapter states (parallel per NPC; retries inside call_json)
    workers = max(1, min(6, args.parallel_npc_workers))

    def _one_npc_states(npc_row: Dict[str, Any]) -> Tuple[str, List[Any]]:
        nid = npc_row["id"]
        _states_user = NPC_CHAPTER_STATES_PROMPT.format(
            npc_profile=compact_json({k: npc_row[k] for k in npc_row.keys() if k != "chapter_states"}),
            chapters=compact_json(chapters),
            clue_ids=compact_json(clue_ids),
        )
        states_obj = call_json(
            client, args.model, SYSTEM,
            _states_user,
            NPC_CHAPTER_STATES_SCHEMA, 0.6, f"[STATES {nid}]", lg, max_output_tokens=args.max_output_tokens
        )
        states = ensure_json_array(states_obj, "chapter_states", 3, 4, lg, f"[STATES {nid}]", npc_row.get("chapter_states") or [])
        if states is None:
            states_obj = call_json(
                client,
                args.model,
                SYSTEM,
                _states_user
                + '\n\nCRITICAL: Output {"npc_id":"'
                + str(npc_row.get("id", ""))
                + '","chapter_states":[...]} with 3-4 chapter_states entries.',
                NPC_CHAPTER_STATES_SCHEMA,
                0.0,
                f"[STATES {nid} retry]",
                lg,
                max_output_tokens=args.max_output_tokens,
            )
            states = ensure_json_array(
                states_obj, "chapter_states", 3, 4, lg, f"[STATES {nid} retry]", npc_row.get("chapter_states") or []
            )
        return nid, (states if states is not None else [])

    lg.info(f"[NPC_STATES] parallel workers={workers} npcs={len(npcs)}")
    id_to_states: Dict[str, List[Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_one_npc_states, dict(n)) for n in npcs]
        for fut in as_completed(futs):
            nid, st = fut.result()
            id_to_states[nid] = st
    for n in npcs:
        n["chapter_states"] = id_to_states.get(n["id"], [])

    # 7) Ending (black screen cutscene)
    final_exit = compute_final_exit_clues(chapters)
    ending_obj = call_json(
        client, args.model, SYSTEM,
        ENDING_PROMPT.format(
            plan=plan,
            chapters=compact_json(chapters),
            final_exit_clues=compact_json(final_exit),
        ),
        ENDING_SCHEMA, 0.4, "[ENDING]", lg, max_output_tokens=max(args.max_output_tokens, 1800)
    )
    ending_obj["black_screen_text"] = ensure_complete_sentence(str(ending_obj.get("black_screen_text", "")))
    if not ending_obj.get("open_thread"):
        ending_obj["open_thread"] = "Something remains unexplained, lingering at the edge of memory."

    # Assemble spec (meta.experience filled after chapters for first_objective_npc_id)
    spec: Dict[str, Any] = {
        "meta": make_meta(
            story,
            plan,
            chapters,
            npcs,
            opening_image_filename,
        ),
        "anchors": anchors,
        "clues": clues,
        "chapters": chapters,
        "npcs": npcs,
        "ending": ending_obj,
        "quality_report": {
            "overall_score": 0,
            "subscores": {"coherence": 0, "pacing": 0, "clue_fairness": 0, "npc_distinctness": 0, "solvability": 0, "player_agency": 0, "tension": 0, "voice_distinctness": 0, "anomaly_over_exposition": 0, "engagement": 0},
            "strengths": ["pending"],
            "problems": []
        },
        "validation_report": {"ok": False, "issues": ["pending"]}
    }

    # 8) Evaluate (model-based)
    eval_obj = call_json(
        client, args.model, SYSTEM,
        EVAL_PROMPT.format(plan=plan, spec_json=compact_json(spec_for_eval(spec))),
        EVAL_SCHEMA, 0.2, "[EVAL]", lg, max_output_tokens=min(args.max_output_tokens, 1200)
    )
    spec["quality_report"] = normalize_quality_report(eval_obj, spec["quality_report"], lg, "[EVAL]")

    # 9) Validate + chunked repair loop
    for r in range(args.repair_iters + 1):
        structural_issues = validate_spec(spec)
        signals = rule_based_quality_signals(spec)
        full_issues = structural_issues + [f"QUALITY_SIGNAL: {s}" for s in signals]

        too_low_quality = spec["quality_report"]["overall_score"] < args.quality_threshold
        spec["validation_report"] = {"ok": (len(structural_issues) == 0), "issues": full_issues}

        if spec["validation_report"]["ok"] and not too_low_quality:
            break

        lg.warning(f"[REPAIR LOOP] iter={r} ok={spec['validation_report']['ok']} quality={spec['quality_report']['overall_score']} structural_issues={len(structural_issues)}")

        # Local fixes first (cheap)
        spec = local_fix_spec(spec, lg)

        # Re-evaluate after local fix
        eval_obj = call_json(
            client, args.model, SYSTEM,
            EVAL_PROMPT.format(plan=plan, spec_json=compact_json(spec_for_eval(spec))),
            EVAL_SCHEMA, 0.2, f"[EVAL after local fix {r}]", lg, max_output_tokens=min(args.max_output_tokens, 1200)
        )
        spec["quality_report"] = normalize_quality_report(eval_obj, spec["quality_report"], lg, f"[EVAL after local fix {r}]")

        # If still failing structurally or quality is low with critique, do targeted repair
        structural_issues = validate_spec(spec)
        quality_issues = quality_problems_to_issues(spec.get("quality_report", {}))
        cats = categorize_issues(structural_issues)
        if quality_issues and not cats:
            cats = categorize_quality_problems(spec.get("quality_report", {}).get("problems") or [])

        should_repair = (structural_issues or quality_issues) and r < args.repair_iters
        all_issues = structural_issues + quality_issues

        if should_repair and all_issues:
            lg.warning(f"[TARGETED REPAIR] categories={sorted(list(cats))} structural={len(structural_issues)} quality={len(quality_issues)}")

            issues_txt = "\n".join(all_issues)

            anchors_changed = False

            # Repair anchors if needed
            if "anchors" in cats:
                old_anchor_ids = [a["id"] for a in spec["anchors"]]
                _ra_user = REPAIR_ANCHORS_PROMPT.format(
                    issues=issues_txt,
                    current_anchors=compact_json(spec["anchors"]),
                )
                anchors_obj = call_json(
                    client, args.model, SYSTEM,
                    _ra_user,
                    ANCHORS_SCHEMA, 0.0, f"[REPAIR ANCHORS {r}]", lg, max_output_tokens=args.max_output_tokens
                )
                al = ensure_json_array(anchors_obj, "anchors", 6, 12, lg, f"[REPAIR ANCHORS {r}]", spec["anchors"])
                if al is None or al is spec["anchors"]:
                    anchors_obj = call_json(
                        client,
                        args.model,
                        SYSTEM,
                        _ra_user
                        + '\n\nCRITICAL: Output exactly {"anchors":[...]} with 6-12 anchors only.',
                        ANCHORS_SCHEMA,
                        0.0,
                        f"[REPAIR ANCHORS {r} retry]",
                        lg,
                        max_output_tokens=args.max_output_tokens,
                    )
                    al = ensure_json_array(
                        anchors_obj, "anchors", 6, 12, lg, f"[REPAIR ANCHORS {r} retry]", spec["anchors"]
                    )
                if al is not None:
                    spec["anchors"] = al
                new_anchor_ids = [a["id"] for a in spec["anchors"]]
                anchors_changed = (old_anchor_ids != new_anchor_ids)

            # If anchors changed, clues and NPCs may now point to invalid anchors; repair them.
            if "clues" in cats or anchors_changed:
                _rc_user = REPAIR_CLUES_PROMPT.format(
                    issues=issues_txt,
                    anchor_ids=compact_json([a["id"] for a in spec["anchors"]]),
                    current_clues=compact_json(spec["clues"]),
                )
                clues_obj = call_json(
                    client, args.model, SYSTEM,
                    _rc_user,
                    CLUES_SCHEMA, 0.0, f"[REPAIR CLUES {r}]", lg, max_output_tokens=args.max_output_tokens
                )
                cl = ensure_json_array(clues_obj, "clues", 10, 14, lg, f"[REPAIR CLUES {r}]", spec["clues"])
                if cl is None or cl is spec["clues"]:
                    clues_obj = call_json(
                        client,
                        args.model,
                        SYSTEM,
                        _rc_user
                        + '\n\nCRITICAL: Output exactly {"clues":[...]} with 10-14 clues only.',
                        CLUES_SCHEMA,
                        0.0,
                        f"[REPAIR CLUES {r} retry]",
                        lg,
                        max_output_tokens=args.max_output_tokens,
                    )
                    cl = ensure_json_array(clues_obj, "clues", 10, 14, lg, f"[REPAIR CLUES {r} retry]", spec["clues"])
                if cl is not None:
                    spec["clues"] = cl

            if "npcs" in cats or anchors_changed:
                _npcs_user = REPAIR_NPCS_PROMPT.format(
                    issues=issues_txt,
                    anchor_ids=compact_json([a["id"] for a in spec["anchors"]]),
                    current_npcs=compact_json([{k: v for k, v in n.items() if k != "chapter_states"} for n in spec["npcs"]]),
                )
                npcs_obj = call_json(
                    client, args.model, SYSTEM,
                    _npcs_user,
                    NPCS_SCHEMA, 0.0, f"[REPAIR NPCS {r}]", lg, max_output_tokens=args.max_output_tokens
                )
                # Model sometimes returns {} or wrong shape → KeyError without this guard
                _nl = npcs_obj.get("npcs")
                if not isinstance(_nl, list) or len(_nl) < 6:
                    lg.warning(
                        f"[REPAIR NPCS {r}] missing/short 'npcs' (keys={list(npcs_obj.keys())}); retry once"
                    )
                    npcs_obj = call_json(
                        client,
                        args.model,
                        SYSTEM,
                        _npcs_user
                        + '\n\nCRITICAL: Output a single JSON object with exactly one top-level key "npcs" whose value is an array of 6-7 NPC objects. Example start: {"npcs":[{...',
                        NPCS_SCHEMA,
                        0.0,
                        f"[REPAIR NPCS {r} retry]",
                        lg,
                        max_output_tokens=args.max_output_tokens,
                    )
                old_states = {n["id"]: n.get("chapter_states") for n in spec["npcs"]}
                _nl2 = npcs_obj.get("npcs")
                if isinstance(_nl2, list) and len(_nl2) >= 6:
                    spec["npcs"] = _nl2
                    for n in spec["npcs"]:
                        if n["id"] in old_states and old_states[n["id"]]:
                            n["chapter_states"] = old_states[n["id"]]
                        n["pose"] = "standing"
                else:
                    lg.error(
                        f"[REPAIR NPCS {r}] still no valid npcs; keeping previous NPC list (pipeline may need re-run)"
                    )

            # Repair chapters if needed (always uses current clue/npc lists)
            if "chapters" in cats or anchors_changed:
                npc_ids_now = [n["id"] for n in spec["npcs"]]
                anchor_ids_now = [a["id"] for a in spec["anchors"]]
                clue_ids_now = [c["id"] for c in spec["clues"]]
                repair_clue_anchor_map = ", ".join(f"{c.get('id', '')} at {c.get('anchor_id', '')}" for c in spec["clues"] if c.get("id") and c.get("anchor_id"))
                repair_npc_anchor_map = ", ".join(f"{n.get('id', '')} at {n.get('anchor_id', '')}" for n in spec["npcs"] if n.get("id") and n.get("anchor_id"))
                _rch_user = REPAIR_CHAPTERS_PROMPT.format(
                    clue_anchor_map=repair_clue_anchor_map,
                    npc_anchor_map=repair_npc_anchor_map,
                    issues=issues_txt,
                    npc_ids=compact_json(npc_ids_now),
                    anchor_ids=compact_json(anchor_ids_now),
                    clue_ids=compact_json(clue_ids_now),
                    current_chapters=compact_json(spec["chapters"]),
                )
                chapters_obj = call_json(
                    client, args.model, SYSTEM,
                    _rch_user,
                    CHAPTERS_SCHEMA, 0.0, f"[REPAIR CHAPTERS {r}]", lg, max_output_tokens=args.max_output_tokens
                )
                prev_ch = spec["chapters"]
                ch_list = ensure_json_array(chapters_obj, "chapters", 3, 4, lg, f"[REPAIR CHAPTERS {r}]", None)
                if ch_list is None:
                    chapters_obj = call_json(
                        client,
                        args.model,
                        SYSTEM,
                        _rch_user
                        + '\n\nCRITICAL: Output ONLY {"chapters":[...]} with 3-4 chapters. No other top-level keys.',
                        CHAPTERS_SCHEMA,
                        0.0,
                        f"[REPAIR CHAPTERS {r} retry]",
                        lg,
                        max_output_tokens=args.max_output_tokens,
                    )
                    ch_list = ensure_json_array(
                        chapters_obj, "chapters", 3, 4, lg, f"[REPAIR CHAPTERS {r} retry]", None
                    )
                if ch_list is not None and _json_array_ok(ch_list, 3, 4):
                    spec["chapters"] = sorted(ch_list, key=lambda c: chapter_index(c["id"]))
                else:
                    lg.error(f"[REPAIR CHAPTERS {r}] keeping previous chapters (model output unusable)")

            # Repair NPC states if needed OR if chapters/clues changed
            if "npc_states" in cats or "chapters" in cats or "clues" in cats or anchors_changed:
                clue_ids_now = [c["id"] for c in spec["clues"]]
                chapters_now = spec["chapters"]
                for npc in spec["npcs"]:
                    current_states = npc.get("chapter_states", [])
                    _rs_user = REPAIR_NPC_STATES_PROMPT.format(
                        issues=issues_txt,
                        npc_profile=compact_json({k: npc[k] for k in npc.keys() if k != "chapter_states"}),
                        chapters=compact_json(chapters_now),
                        clue_ids=compact_json(clue_ids_now),
                        current_states=compact_json(current_states),
                    )
                    states_obj = call_json(
                        client, args.model, SYSTEM,
                        _rs_user,
                        NPC_CHAPTER_STATES_SCHEMA, 0.0, f"[REPAIR STATES {r}:{npc['id']}]", lg, max_output_tokens=args.max_output_tokens
                    )
                    st = ensure_json_array(
                        states_obj, "chapter_states", 3, 4, lg, f"[REPAIR STATES {r}:{npc['id']}]", current_states
                    )
                    if st is None or st is current_states:
                        states_obj = call_json(
                            client,
                            args.model,
                            SYSTEM,
                            _rs_user
                            + '\n\nCRITICAL: Include "chapter_states" array with 3-4 entries matching chapters.',
                            NPC_CHAPTER_STATES_SCHEMA,
                            0.0,
                            f"[REPAIR STATES {r}:{npc['id']} retry]",
                            lg,
                            max_output_tokens=args.max_output_tokens,
                        )
                        st = ensure_json_array(
                            states_obj,
                            "chapter_states",
                            3,
                            4,
                            lg,
                            f"[REPAIR STATES {r}:{npc['id']} retry]",
                            current_states,
                        )
                    npc["chapter_states"] = st if st is not None else current_states

            # Repair ending if needed OR if chapters changed
            if "ending" in cats or "chapters" in cats or anchors_changed:
                final_exit = compute_final_exit_clues(spec["chapters"])
                ending_obj = call_json(
                    client, args.model, SYSTEM,
                    REPAIR_ENDING_PROMPT.format(
                        issues=issues_txt,
                        chapters=compact_json(spec["chapters"]),
                        final_exit_clues=compact_json(final_exit),
                        current_ending=compact_json(spec.get("ending", {})),
                    ),
                    ENDING_SCHEMA, 0.0, f"[REPAIR ENDING {r}]", lg, max_output_tokens=max(args.max_output_tokens, 1800)
                )
                if not isinstance(ending_obj, dict):
                    ending_obj = {}
                merged = dict(spec.get("ending") or {})
                merged.update(ending_obj)
                ending_obj = merged
                ending_obj["black_screen_text"] = ensure_complete_sentence(
                    str(ending_obj.get("black_screen_text") or spec.get("ending", {}).get("black_screen_text") or "")
                )
                if not ending_obj.get("open_thread"):
                    ending_obj["open_thread"] = spec.get("ending", {}).get("open_thread") or "Something remains unexplained."
                if not ending_obj.get("trigger") and spec.get("ending", {}).get("trigger"):
                    ending_obj["trigger"] = spec["ending"]["trigger"]
                if not ending_obj.get("title"):
                    ending_obj["title"] = spec.get("ending", {}).get("title") or "Ending"
                spec["ending"] = ending_obj

            # One more local fix pass after targeted repairs
            spec = local_fix_spec(spec, lg)

            # Re-evaluate after targeted repair
            eval_obj = call_json(
                client, args.model, SYSTEM,
                EVAL_PROMPT.format(plan=plan, spec_json=compact_json(spec_for_eval(spec))),
                EVAL_SCHEMA, 0.2, f"[EVAL after targeted repair {r}]", lg, max_output_tokens=min(args.max_output_tokens, 1200)
            )
            spec["quality_report"] = normalize_quality_report(
                eval_obj, spec["quality_report"], lg, f"[EVAL after targeted repair {r}]"
            )

    # Final validation report
    final_structural = validate_spec(spec)
    signals = rule_based_quality_signals(spec)
    spec["validation_report"] = {"ok": (len(final_structural) == 0), "issues": final_structural + [f"QUALITY_SIGNAL: {s}" for s in signals]}

    # Optional: jsonschema structural validation (if installed)
    if jsonschema is not None:
        try:
            jsonschema.validate(instance=spec, schema=FINAL_SPEC_SCHEMA)
        except Exception as e:
            spec["validation_report"]["ok"] = False
            spec["validation_report"]["issues"].append(f"jsonschema_validation_failed: {str(e)[:220]}")

    if not spec["validation_report"]["ok"]:
        lg.error(f"[FINAL] Validation failed with issues={len(spec['validation_report']['issues'])}")
    else:
        lg.info("[FINAL] Validation OK")

    # UI copy + stills (narrator setup, chapter hooks, optional Imagen)
    if spec["validation_report"]["ok"] and not getattr(args, "skip_ui_images", False):
        try:
            meta = spec.setdefault("meta", {})
            if not meta.get("title"):
                meta["title"] = (meta.get("one_sentence_premise") or "Story")[:80]
            ns = call_text(
                client,
                args.model,
                SYSTEM,
                "Write narrator_setup: 25-50 words, second person (you). Who the player is and how this investigation starts. "
                "Single paragraph. No multiple paragraphs. Do not repeat the full premise verbatim. Story context:\n"
                + (story[:3500] + "\n" + plan[:1500]),
                0.6,
                "[narrator_setup]",
                lg,
                max_output_tokens=400,
            ).strip()
            if len(ns) >= 20:
                # Post-process to ensure we only keep the clean narrator
                # paragraph (no markdown headings, no NPC lists, etc.).
                # 1) Cut off anything after a blank line (first paragraph only).
                # 2) Drop leading markdown-style headings or labels like **narrator_setup**.
                raw = ns[:400]
                # Take only text before the first double newline to avoid stray sections.
                para = raw.split("\n\n", 1)[0]
                # Split into lines so we can strip heading-like lines.
                kept_lines = []
                for line in para.splitlines():
                    stripped = line.strip()
                    # Skip obvious heading/label lines.
                    if not kept_lines and (
                        stripped.startswith("**") and stripped.endswith("**")
                        or stripped.lower().startswith("narrator_setup")
                        or stripped.lower().startswith("**narrator_setup")
                    ):
                        continue
                    kept_lines.append(stripped)
                clean = " ".join(kept_lines).strip()
                if len(clean) >= 20:
                    meta["narrator_setup"] = clean
                else:
                    meta["narrator_setup"] = raw
            chapters_sorted = sorted(spec.get("chapters") or [], key=lambda c: chapter_index(c.get("id", "")))
            npcs = spec.get("npcs") or []
            clues = spec.get("clues") or []
            nid_to_name = {n.get("id"): n.get("name", n.get("id")) for n in npcs if n.get("id")}
            for idx, ch in enumerate(chapters_sorted):
                cid = ch.get("id", "")
                prev_exit = []
                if idx > 0:
                    prev_exit = chapters_sorted[idx - 1].get("exit_require_all_clues") or []
                exit_clue_desc = []
                for clue_id in prev_exit:
                    for c in clues:
                        if c.get("id") == clue_id:
                            exit_clue_desc.append(f"{c.get('label')} — {c.get('description', '')[:200]}")
                            break
                spot = ch.get("spotlight_npc_ids") or []
                spot_names = [nid_to_name.get(s, s) for s in spot]
                hook_user = (
                    f"CHAPTER ENTERING: {cid} title={ch.get('title')}\n"
                    f"Spotlight NPCs to talk to: {spot_names}\n"
                )
                if exit_clue_desc:
                    hook_user += "Player just learned (previous chapter): " + " | ".join(exit_clue_desc) + "\n"
                hook_user += (
                    "Write transition_player_hook: 25-50 words, second person, thrilling, actionable. "
                    "Single paragraph. Connect clues to where to go and who to talk to next. No dry summary."
                )
                hook = call_text(client, args.model, SYSTEM, hook_user, 0.65, f"[hook {cid}]", lg, max_output_tokens=500).strip()
                if len(hook) >= 40:
                    ch["transition_player_hook"] = hook[:400]
            out_dir = os.path.dirname(os.path.abspath(args.out)) or "."
            genre = meta.get("genre", "mystery")
            if not args.skip_opening_image:
                try:
                    sp = call_text(
                        client,
                        args.model,
                        OPENING_IMAGE_PROMPT_SYSTEM,
                        "SETUP SCREEN (menu backdrop), 16:9, moody but readable.\n"
                        + "STORY:\n"
                        + story[:3000]
                        + "\n\nPLAN:\n"
                        + plan[:2000]
                        + "\n\n"
                        + IMAGEN_SETTING_LOCK_USER,
                        0.5,
                        "[setup_screen prompt]",
                        lg,
                        max_output_tokens=220,
                    ).strip()[:500]
                    if len(sp) >= 12:
                        with open(os.path.join(out_dir, "setup_screen.png"), "wb") as f:
                            f.write(gc.generate_image_bytes(sp, aspect_ratio="16:9"))
                        meta.setdefault("experience", {})["setup_screen_path"] = "setup_screen.png"
                except Exception as e:
                    lg.warning(f"[setup_screen image] {e}")
                for ch in chapters_sorted:
                    cid = ch.get("id", "")
                    try:
                        cp = call_text(
                            client,
                            args.model,
                            OPENING_IMAGE_PROMPT_SYSTEM,
                            f"Chapter transition still: {cid} title={ch.get('title', '')}. Genre: {genre}.\n"
                            + "STORY:\n"
                            + story[:2500]
                            + "\n\nPLAN:\n"
                            + plan[:1800]
                            + "\n\n"
                            + IMAGEN_SETTING_LOCK_USER,
                            0.5,
                            f"[chapter img {cid}]",
                            lg,
                            max_output_tokens=220,
                        ).strip()[:500]
                        if len(cp) >= 12:
                            fn = f"chapter_transition_{cid}.png"
                            with open(os.path.join(out_dir, fn), "wb") as f:
                                f.write(gc.generate_image_bytes(cp, aspect_ratio="16:9"))
                    except Exception as e:
                        lg.warning(f"[chapter img {cid}] {e}")
                try:
                    ep = call_text(
                        client,
                        args.model,
                        OPENING_IMAGE_PROMPT_SYSTEM,
                        "Ending / resolution still, emotional closure, no text.\n"
                        + "STORY:\n"
                        + story[:2500]
                        + "\n\nPLAN:\n"
                        + plan[:1800]
                        + "\n\n"
                        + IMAGEN_SETTING_LOCK_USER,
                        0.5,
                        "[ending_screen prompt]",
                        lg,
                        max_output_tokens=220,
                    ).strip()[:500]
                    if len(ep) >= 12:
                        with open(os.path.join(out_dir, "ending_screen.png"), "wb") as f:
                            f.write(gc.generate_image_bytes(ep, aspect_ratio="16:9"))
                        meta.setdefault("experience", {})["ending_screen_path"] = "ending_screen.png"
                except Exception as e:
                    lg.warning(f"[ending_screen] {e}")
        except Exception as e:
            lg.warning(f"[UI enrichment] {e}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)

    lg.info(f"[DONE] wrote {args.out}")
    qr = spec.get("quality_report") or {}
    lg.info(f"[QUALITY] overall={qr.get('overall_score', 0)} subscores={qr.get('subscores', {})}")


if __name__ == "__main__":
    main()
