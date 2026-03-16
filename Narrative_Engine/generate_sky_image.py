#!/usr/bin/env python3
"""
generate_sky_image.py

Generates sky.png for Godot PanoramaSkyMaterial from narrative atmosphere.
Uses Vertex Imagen when GOOGLE_CLOUD_PROJECT + ADC are set; otherwise Pillow gradient.

Output: OUTPUT_DIR/sky.png
"""

import json
import os
import sys
from typing import Any, Dict, Tuple

NARRATIVE_SPEC_PATH = os.environ.get("NARRATIVE_SPEC_PATH", "narrative_spec.json")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
SKY_WIDTH = 2048
SKY_HEIGHT = 1024


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)


def get_atmosphere(spec: Dict[str, Any]) -> Tuple[float, float]:
    meta = spec.get("meta") or {}
    atm = meta.get("atmosphere") or {}
    t = float(atm.get("time_of_day", 12.0))
    f = float(atm.get("fog_intensity", 0.0))
    return max(0.0, min(24.0, t)), max(0.0, min(1.0, f))


def time_label(hours: float) -> str:
    if hours < 5:
        return "night"
    if hours < 8:
        return "dawn"
    if hours < 11:
        return "morning"
    if hours < 14:
        return "noon"
    if hours < 17:
        return "afternoon"
    if hours < 20:
        return "dusk"
    return "night"


def fog_label(intensity: float) -> str:
    if intensity <= 0.05:
        return "clear"
    if intensity <= 0.35:
        return "light fog"
    if intensity <= 0.65:
        return "moderate fog"
    return "heavy fog"


def build_prompt(time_of_day: float, fog_intensity: float, spec: Dict[str, Any]) -> str:
    meta = spec.get("meta") or {}
    place = (meta.get("one_sentence_premise") or meta.get("intro_premise") or "")[:180]
    return (
        "360 degree equirectangular sky panorama for a video game, "
        f"{time_label(time_of_day)} sky, {fog_label(fog_intensity)}, "
        f"genre: {meta.get('genre', '')}, tone: {meta.get('tone', '')}. "
        f"Atmosphere suited to setting: {place}. "
        "No characters, no buildings, only sky and distant horizon. "
        "Seamless horizontal wrap. Cartoonish vibrant palette."
    )


def generate_via_vertex(prompt: str, out_path: str) -> bool:
    try:
        import gemini_client as gc
        from PIL import Image
        import io

        raw = gc.generate_image_bytes(prompt, aspect_ratio="16:9")
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img = img.resize((SKY_WIDTH, SKY_HEIGHT), Image.Resampling.LANCZOS)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        img.save(out_path, "PNG")
        return True
    except Exception as e:
        print(f"Vertex Imagen sky: {e}", file=sys.stderr)
        return False


def generate_placeholder(time_of_day: float, fog_intensity: float, out_path: str) -> bool:
    try:
        from PIL import Image
    except ImportError:
        return False
    img = Image.new("RGB", (SKY_WIDTH, SKY_HEIGHT))
    pixels = img.load()
    t = time_of_day / 24.0
    if t < 0.25 or t >= 0.83:
        r_t, g_t, b_t = 0.08, 0.1, 0.18
        r_b, g_b, b_b = 0.05, 0.06, 0.12
    elif t < 0.33:
        r_t, g_t, b_t = 0.4, 0.25, 0.5
        r_b, g_b, b_b = 0.6, 0.4, 0.5
    elif t < 0.75:
        r_t, g_t, b_t = 0.25, 0.45, 0.85
        r_b, g_b, b_b = 0.7, 0.78, 0.9
    else:
        r_t, g_t, b_t = 0.3, 0.2, 0.4
        r_b, g_b, b_b = 0.8, 0.5, 0.4
    gray = 0.5 + 0.4 * fog_intensity
    for y in range(SKY_HEIGHT):
        frac = y / max(SKY_HEIGHT - 1, 1)
        r = int(255 * ((r_t * (1 - frac) + r_b * frac) * (1 - fog_intensity) + gray * fog_intensity))
        g = int(255 * ((g_t * (1 - frac) + g_b * frac) * (1 - fog_intensity) + gray * fog_intensity))
        b = int(255 * ((b_t * (1 - frac) + b_b * frac) * (1 - fog_intensity) + gray * fog_intensity))
        for x in range(SKY_WIDTH):
            pixels[x, y] = (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG")
    return True


def main() -> None:
    if not os.path.isfile(NARRATIVE_SPEC_PATH):
        print(f"Error: {NARRATIVE_SPEC_PATH} not found.", file=sys.stderr)
        sys.exit(1)
    spec = load_json(NARRATIVE_SPEC_PATH)
    time_of_day, fog_intensity = get_atmosphere(spec)
    prompt = build_prompt(time_of_day, fog_intensity, spec)
    out_path = os.path.join(OUTPUT_DIR, "sky.png")
    print(f"Atmosphere: time_of_day={time_of_day}, fog_intensity={fog_intensity}")
    if generate_via_vertex(prompt, out_path):
        print(f"Generated sky via Vertex Imagen: {out_path}")
    elif generate_placeholder(time_of_day, fog_intensity, out_path):
        print(f"Generated placeholder sky: {out_path}")
    else:
        print("Failed to write sky", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
