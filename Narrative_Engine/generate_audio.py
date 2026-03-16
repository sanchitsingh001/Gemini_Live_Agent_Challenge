#!/usr/bin/env python3
"""
generate_audio.py

Generates voiceover (Gemini-TTS) and BGM (Lyria) for narrative segments,
then merges audio paths into game_bundle.json.

Usage:
  OUTPUT_DIR=output/20260218_223200 python3 generate_audio.py
  GENERATE_AUDIO=0 to skip (e.g. if running without GCP / for quick iteration)

Env:
  OUTPUT_DIR, GAME_OUTPUT — output folder containing game_bundle.json
  SKIP_TTS — skip voiceover generation
  SKIP_BGM — skip BGM generation
"""

import json
import logging
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.environ.get("GAME_OUTPUT", "output/20260218_223200"))


def main() -> None:
    base = Path(OUTPUT_DIR).resolve()
    bundle_path = base / "game_bundle.json"
    if not bundle_path.exists():
        logger.warning("game_bundle.json not found at %s — skipping audio generation", bundle_path)
        return

    with open(bundle_path) as f:
        bundle = json.load(f)

    narrative = bundle.get("narrative", {})
    spec = {
        "meta": narrative.get("meta", {}),
        "chapters": narrative.get("chapters", []),
        "ending": narrative.get("ending", {}),
    }

    skip_tts = os.environ.get("SKIP_TTS", "").lower() in ("1", "true", "yes")
    skip_bgm = os.environ.get("SKIP_BGM", "").lower() in ("1", "true", "yes")

    try:
        from audio_generation import generate_narrative_audio_for_bundle
    except ImportError as e:
        logger.warning("audio_generation not available: %s — skipping", e)
        return

    audio_result = generate_narrative_audio_for_bundle(
        spec,
        output_dir=base,
        skip_tts=skip_tts,
        skip_bgm=skip_bgm,
    )

    # Merge audio paths into bundle
    meta = narrative.get("meta", {})
    if "meta" in audio_result:
        for k, v in audio_result["meta"].items():
            meta[k] = v
    narrative["meta"] = meta

    chapters = narrative.get("chapters", [])
    ch_map = audio_result.get("chapters", {})
    for ch in chapters:
        if not isinstance(ch, dict):
            continue
        ch_id = str(ch.get("id", ""))
        if ch_id in ch_map:
            for k, v in ch_map[ch_id].items():
                ch[k] = v
    narrative["chapters"] = chapters

    ending = narrative.get("ending", {})
    if "ending" in audio_result:
        for k, v in audio_result["ending"].items():
            ending[k] = v
    narrative["ending"] = ending

    bundle["narrative"] = narrative

    # Per-area exploration BGM (optional, if we have areas)
    areas = bundle.get("areas", {})
    if areas and not skip_bgm:
        try:
            from audio_generation import generate_bgm, make_ambient_bgm_prompt

            meta_n = narrative.get("meta", {})
            genre = meta_n.get("genre", "mystery")
            tone = meta_n.get("tone", "tense")
            audio_dir = base / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            area_bgm = {}
            for aid, adata in areas.items():
                name = adata.get("name", aid)
                prompt = make_ambient_bgm_prompt(name, genre, tone)
                out_path = audio_dir / f"bgm_area_{aid}.wav"
                try:
                    generate_bgm(prompt, out_path)
                    area_bgm[aid] = f"audio/bgm_area_{aid}.wav"
                except Exception as e:
                    logger.warning("Area BGM %s failed: %s", aid, e)
            if area_bgm:
                bundle["audio"] = bundle.get("audio", {})
                bundle["audio"]["area_bgm"] = area_bgm
        except Exception as e:
            logger.warning("Per-area BGM failed: %s", e)

    with open(bundle_path, "w") as f:
        json.dump(bundle, f, indent=2)
    logger.info("Updated game_bundle.json with audio paths")


if __name__ == "__main__":
    main()
