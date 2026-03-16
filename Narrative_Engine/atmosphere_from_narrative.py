#!/usr/bin/env python3
"""
atmosphere_from_narrative.py

Derives time_of_day (0-24) and fog_intensity (0-1) from the narrative spec.
Writes meta.atmosphere into the narrative spec (in-place or to OUTPUT_DIR copy).
Only weather variable is fog; no rain/snow.

Usage:
  NARRATIVE_SPEC_PATH=... OUTPUT_DIR=... python3 atmosphere_from_narrative.py

Uses Vertex Gemini (ADC) when available to infer atmosphere from genre/tone/premise.
Otherwise uses heuristics from meta.tone.
"""

import json
import os
import re
import sys
from typing import Any, Dict

# Config
NARRATIVE_SPEC_PATH = os.environ.get("NARRATIVE_SPEC_PATH", "narrative_spec.json")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")

# Default when missing
DEFAULT_TIME_OF_DAY = 12.0
DEFAULT_FOG_INTENSITY = 0.0


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)


def save_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def heuristic_atmosphere(spec: Dict[str, Any]) -> Dict[str, float]:
    """Derive time_of_day and fog_intensity from meta.tone and genre."""
    meta = spec.get("meta") or {}
    tone = (meta.get("tone") or "").lower()
    genre = (meta.get("genre") or "").lower()
    intro = (meta.get("intro_premise") or "")[:500].lower()

    # Time: night/dark/mystery/tense → evening/night; hopeful → dawn; default noon
    time_of_day = DEFAULT_TIME_OF_DAY
    if any(w in tone for w in ["dark", "noir", "night"]):
        time_of_day = 22.0
    elif any(w in genre for w in ["horror", "noir"]):
        time_of_day = 21.0
    elif any(w in tone for w in ["tense", "mystery", "eerie"]):
        time_of_day = 18.5  # dusk
    elif any(w in tone for w in ["hopeful", "dawn"]):
        time_of_day = 6.0
    elif any(w in intro for w in ["night", "midnight", "darkness"]):
        time_of_day = 23.0
    elif any(w in intro for w in ["dusk", "twilight", "evening"]):
        time_of_day = 18.0
    elif any(w in intro for w in ["dawn", "morning"]):
        time_of_day = 6.0

    # Fog: tense/mystery/dark → light to heavy; hopeful → clear
    fog_intensity = DEFAULT_FOG_INTENSITY
    if any(w in tone for w in ["dark", "noir", "eerie"]):
        fog_intensity = 0.6
    elif any(w in tone for w in ["tense", "mystery"]):
        fog_intensity = 0.4
    elif any(w in tone for w in ["melancholy", "somber"]):
        fog_intensity = 0.35
    elif any(w in intro for w in ["fog", "mist", "haze"]):
        fog_intensity = 0.5
    elif any(w in tone for w in ["hopeful", "bright"]):
        fog_intensity = 0.0

    return {
        "time_of_day": round(time_of_day, 1),
        "fog_intensity": round(min(1.0, max(0.0, fog_intensity)), 2),
    }


def llm_atmosphere(spec: Dict[str, Any]) -> Dict[str, float] | None:
    """Vertex Gemini: infer time_of_day and fog_intensity. Returns None on failure."""
    try:
        import gemini_client as gc
    except ImportError:
        return None

    meta = spec.get("meta") or {}
    genre = meta.get("genre", "")
    tone = meta.get("tone", "")
    premise = (meta.get("one_sentence_premise") or "")[:200]
    intro = (meta.get("intro_premise") or "")[:400]

    system = "Reply with JSON only: {\"time_of_day\": float 0-24, \"fog_intensity\": float 0-1}."
    user = f"""Given this story meta, output time of day and fog for the game world (fog only, no rain/snow).

Genre: {genre}
Tone: {tone}
Premise: {premise}
Intro (excerpt): {intro}"""

    try:
        raw = gc.generate_json(system, user, temperature=0.3)
        if not isinstance(raw, dict):
            return None
        time_val = float(raw.get("time_of_day", DEFAULT_TIME_OF_DAY))
        fog_val = float(raw.get("fog_intensity", DEFAULT_FOG_INTENSITY))
        return {
            "time_of_day": round(min(24.0, max(0.0, time_val)), 1),
            "fog_intensity": round(min(1.0, max(0.0, fog_val)), 2),
        }
    except Exception:
        return None


def main() -> None:
    in_path = NARRATIVE_SPEC_PATH
    if not os.path.isfile(in_path):
        print(f"Error: {in_path} not found.", file=sys.stderr)
        sys.exit(1)

    spec = load_json(in_path)
    meta = spec.get("meta") or {}

    # Use existing atmosphere if present and valid
    existing = meta.get("atmosphere")
    if isinstance(existing, dict):
        t = existing.get("time_of_day")
        f = existing.get("fog_intensity")
        if isinstance(t, (int, float)) and 0 <= t <= 24 and isinstance(f, (int, float)) and 0 <= f <= 1:
            print(f"Using existing atmosphere: time_of_day={t}, fog_intensity={f}")
            save_json(in_path, spec)
            return
        existing = None

    if not existing:
        atmosphere = llm_atmosphere(spec)
        if atmosphere is None:
            atmosphere = heuristic_atmosphere(spec)
            print(f"Using heuristic atmosphere: {atmosphere}")
        else:
            print(f"Using LLM atmosphere: {atmosphere}")
        meta["atmosphere"] = atmosphere
        spec["meta"] = meta

    save_json(in_path, spec)
    print(f"Wrote atmosphere to {in_path}")


if __name__ == "__main__":
    main()
