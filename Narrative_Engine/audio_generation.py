"""
Audio generation for Narrative Engine: voiceover (Gemini-TTS) and background music (Lyria).

Env:
  GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION — same as gemini_client
  GAME_OUTPUT / OUTPUT_DIR — where to write audio files (e.g. output/20260218_223200)
  LYRIA_MODEL — Lyria model ID (default lyria-002). Override when newer models ship.

Run once: gcloud auth application-default login
Enable: Vertex AI API, Cloud Text-to-Speech (for Gemini-TTS), Lyria on Vertex AI
"""

from __future__ import annotations

import base64
import logging
import os
import time
import wave
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "project-363d072c-3554-4f41-b1e")
DEFAULT_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
# Lyria model: lyria-002 is the current production model. Override with LYRIA_MODEL when newer versions ship.
DEFAULT_LYRIA_MODEL = os.environ.get("LYRIA_MODEL", "lyria-002")

# TTS prompts per context (documentary/thriller style, no intimate undertones)
VOICEOVER_PROMPTS: Dict[str, str] = {
    "setup": "You are a documentary narrator. Clear, crisp, professional. Deliver in a thriller-style storytelling tone. No intimate or romantic undertones.",
    "transition": "You are a thriller documentary narrator. Terse, tense, forward-moving. Build momentum. Professional and crisp, no emotional indulgence.",
    "ending": "You are a documentary narrator delivering the resolution. Clear, decisive, understated. Professional tone, no romantic or sensual delivery.",
    "chapter_summary": "Deliver as a documentary narrator. Measured, informative, professional. No intimate or emotional indulgence.",
}

# Fallback style if context not in map
DEFAULT_VOICEOVER_STYLE = "Read as a professional documentary narrator. Clear, crisp, no intimate or romantic undertones."


def _get_project() -> str:
    return os.environ.get("GOOGLE_CLOUD_PROJECT", DEFAULT_PROJECT).strip() or DEFAULT_PROJECT


def _get_location() -> str:
    return os.environ.get("GOOGLE_CLOUD_LOCATION", DEFAULT_LOCATION).strip() or DEFAULT_LOCATION


def _get_output_dir() -> Path:
    out = os.environ.get("OUTPUT_DIR", os.environ.get("GAME_OUTPUT", "output/20260218_223200"))
    return Path(out).resolve()


def generate_voiceover(
    text: str,
    output_path: str | Path,
    *,
    context: str = "setup",
    model: str = "gemini-2.5-flash-tts",
    speaker: str = "Kore",
    max_retries: int = 3,
) -> Path:
    """
    Generate emotional voiceover using Gemini-TTS. Writes WAV file.

    Args:
        text: Text to speak.
        output_path: Output file path (.wav).
        context: One of setup, transition, ending, chapter_summary — controls style prompt.
        model: TTS model (gemini-2.5-flash-tts or gemini-2.5-pro-tts).
        speaker: Voice name (e.g. Kore, Aoede, Callirrhoe).
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gemini_client as gc

    from google.genai import types

    # Send only the narration text to TTS. Do not prepend the style prompt — the API
    # speaks whatever is in contents, so prepending would make it say "Clear, crisp,
    # professional..." and cut off the first line. VOICEOVER_PROMPTS are kept for
    # reference; use only the actual script.
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    client = gc.get_client()
    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=speaker),
                        )
                    ),
                ),
            )
            if not resp.candidates:
                last_err = RuntimeError("No candidates in TTS response")
                continue
            parts = resp.candidates[0].content.parts
            if not parts:
                last_err = RuntimeError("No parts in TTS response")
                continue
            inline = getattr(parts[0], "inline_data", None)
            if not inline or not getattr(inline, "data", None):
                last_err = RuntimeError("No inline audio data in TTS response")
                continue
            data = inline.data
            if isinstance(data, str):
                data = base64.b64decode(data)
            # TTS returns PCM; typical 24kHz, 16-bit mono
            sample_rate = 24000
            if hasattr(inline, "sample_rate_hertz") and inline.sample_rate_hertz:
                sample_rate = int(inline.sample_rate_hertz)
            with wave.open(str(out), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(data)
            logger.info("Wrote voiceover: %s", out)
            return out
        except Exception as e:
            last_err = e
            if "429" in str(e).lower() or "quota" in str(e).lower():
                time.sleep(min(30, 5 * (attempt + 1)))
            else:
                time.sleep(2 + attempt)
    if last_err:
        raise last_err
    raise RuntimeError("generate_voiceover failed")


def generate_bgm(
    prompt: str,
    output_path: str | Path,
    *,
    negative_prompt: str = "loud, drums, vocals, crescendo, dramatic, busy",
    seed: Optional[int] = None,
    model: Optional[str] = None,
    max_retries: int = 3,
) -> Path:
    """
    Generate ambient background music using Lyria. Writes WAV file (~30s, 48kHz).

    Uses the latest Lyria model (lyria-002). Set LYRIA_MODEL env to switch when
    newer versions (e.g. lyria-003) become available.

    Args:
        prompt: Text description of the music (US English).
        output_path: Output file path (.wav).
        negative_prompt: What to exclude from the mix.
        seed: Optional seed for reproducibility.
        model: Override Lyria model ID (default: LYRIA_MODEL or lyria-002).
    """
    import requests

    from google.auth import default
    from google.auth.transport.requests import Request

    project = _get_project()
    location = _get_location()
    lyria_model = (model or os.environ.get("LYRIA_MODEL", DEFAULT_LYRIA_MODEL)).strip() or "lyria-002"
    url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/publishers/google/models/{lyria_model}:predict"

    credentials, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())

    instance: Dict[str, Any] = {"prompt": prompt, "negative_prompt": negative_prompt}
    if seed is not None:
        instance["seed"] = seed
    payload: Dict[str, Any] = {"instances": [instance], "parameters": {}}
    if seed is None:
        payload["parameters"]["sample_count"] = 1

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            r = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {credentials.token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120,
            )
            r.raise_for_status()
            data = r.json()
            preds = data.get("predictions", [])
            if not preds:
                logger.warning("Lyria response: %s", data)
                last_err = RuntimeError("No predictions in Lyria response")
                continue
            pred0 = preds[0] if isinstance(preds[0], dict) else {}
            b64 = pred0.get("audioContent") or pred0.get("bytesBase64Encoded")
            if not b64:
                logger.warning("Lyria prediction keys: %s", list(pred0.keys()))
                last_err = RuntimeError("No audioContent/bytesBase64Encoded in Lyria response")
                continue
            raw = base64.b64decode(b64)
            out.write_bytes(raw)
            logger.info("Wrote BGM: %s", out)
            return out
        except requests.exceptions.HTTPError as e:
            last_err = e
            if e.response is not None:
                try:
                    err_body = e.response.json()
                    logger.warning("Lyria HTTP %s: %s", e.response.status_code, err_body)
                except Exception:
                    logger.warning("Lyria HTTP %s: %s", e.response.status_code, e.response.text[:500])
            if e.response is not None and e.response.status_code == 429:
                time.sleep(min(60, 15 * (attempt + 1)))
            else:
                time.sleep(5 + attempt)
        except Exception as e:
            last_err = e
            time.sleep(5 + attempt)
    if last_err:
        raise last_err
    raise RuntimeError("generate_bgm failed")


def make_ambient_bgm_prompt(area_name: str, genre: str, tone: str) -> str:
    """Lyria prompt for quiet, loopable exploration BGM per area."""
    return (
        f"A subtle, quiet ambient soundscape for {area_name}. "
        f"Very slow tempo, soft synthesizer pads, minimal rhythm. "
        f"{tone}. Spacious reverb, atmospheric. Background underscore, loop-friendly. "
    )


def make_narrative_bgm_prompt(chapter_context: str, mood: str) -> str:
    """Lyria prompt for narrative screens (transition, setup, ending)."""
    return (
        f"Quiet, subtle ambient music for a narrative moment. {chapter_context}. {mood}. "
        f"Very slow, soft pads, minimal. Supports voiceover, does not distract. "
    )


def mix_voice_and_bgm(
    voice_path: str | Path,
    bgm_path: str | Path,
    output_path: str | Path,
    *,
    bgm_volume_db: float = -24.0,
) -> Path:
    """
    Mix voiceover and background music into a single WAV. BGM is ducked (quiet) under voice.

    Requires: pip install pydub
    """
    try:
        from pydub import AudioSegment
    except ImportError:
        raise ImportError("pydub required for mixing. pip install pydub")

    voice = AudioSegment.from_wav(str(voice_path))
    bgm = AudioSegment.from_wav(str(bgm_path))

    # Trim or loop BGM to match voice duration
    voice_dur_ms = len(voice)
    if len(bgm) < voice_dur_ms:
        # Loop BGM
        mixed_bgm = bgm
        while len(mixed_bgm) < voice_dur_ms:
            mixed_bgm += bgm
        mixed_bgm = mixed_bgm[:voice_dur_ms]
    else:
        mixed_bgm = bgm[:voice_dur_ms]

    # Duck BGM
    mixed_bgm = mixed_bgm + bgm_volume_db  # dB
    combined = voice.overlay(mixed_bgm)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    combined.export(str(out), format="wav")
    logger.info("Wrote mixed audio: %s", out)
    return out


def generate_narrative_audio_for_bundle(
    spec: Dict[str, Any],
    output_dir: Optional[str | Path] = None,
    *,
    skip_tts: bool = False,
    skip_bgm: bool = False,
    mix_voice_bgm: bool = False,
) -> Dict[str, Any]:
    """
    Generate voiceover and BGM for all narrative segments. Returns audio path overrides
    to merge into game_bundle.

    Args:
        spec: narrative_spec or game_bundle['narrative'] dict.
        output_dir: Where to write audio (default: OUTPUT_DIR/audio).
        skip_tts: Skip voiceover generation.
        skip_bgm: Skip BGM generation.
        mix_voice_bgm: Mix voice + BGM into single file (else separate files).
    """
    base = Path(output_dir) if output_dir else _get_output_dir()
    audio_dir = base / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    meta = spec.get("meta", {})
    chapters = spec.get("chapters", [])
    ending = spec.get("ending", {})
    genre = meta.get("genre", "mystery")
    tone = meta.get("tone", "tense")

    result: Dict[str, Any] = {"meta": {}, "chapters": {}, "ending": {}}

    # 1) Setup narrator
    setup_text = meta.get("narrator_setup") or meta.get("intro_premise", "Your story begins.")
    # Some earlier specs may have included markdown headings or NPC lists inside
    # narrator_setup. For TTS we only want the actual setup paragraph. Trim
    # everything after the first blank line and drop heading-style lines.
    if isinstance(setup_text, str):
        raw = setup_text
        raw = raw.split("\n\n", 1)[0]
        lines = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not lines and (
                stripped.startswith("**") and stripped.endswith("**")
                or stripped.lower().startswith("narrator_setup")
                or stripped.lower().startswith("**narrator_setup")
            ):
                continue
            lines.append(stripped)
        setup_text = " ".join(lines).strip()
    if setup_text and not skip_tts:
        try:
            v_path = audio_dir / "voiceover_setup.wav"
            generate_voiceover(str(setup_text), v_path, context="setup")
            result["meta"]["setup_voice_path"] = "audio/voiceover_setup.wav"
        except Exception as e:
            logger.warning("Setup voiceover failed: %s", e)
    if setup_text and not skip_bgm:
        try:
            prompt = make_narrative_bgm_prompt(f"Genre: {genre}", f"Tone: {tone}")
            b_path = audio_dir / "bgm_setup.wav"
            generate_bgm(prompt, b_path, negative_prompt="loud, drums, vocals, crescendo, dramatic")
            result["meta"]["setup_bgm_path"] = "audio/bgm_setup.wav"
        except Exception as e:
            logger.warning("Setup BGM failed: %s", e)

    # 2) Chapter transitions
    for ch in chapters:
        if not isinstance(ch, dict):
            continue
        ch_id = str(ch.get("id", ""))
        hook = str(ch.get("transition_player_hook") or ch.get("narration", ""))
        if not hook:
            continue
        if not skip_tts:
            try:
                v_path = audio_dir / f"voiceover_transition_{ch_id}.wav"
                generate_voiceover(hook, v_path, context="transition")
                if "chapters" not in result:
                    result["chapters"] = {}
                if ch_id not in result["chapters"]:
                    result["chapters"][ch_id] = {}
                result["chapters"][ch_id]["transition_voice_path"] = f"audio/voiceover_transition_{ch_id}.wav"
            except Exception as e:
                logger.warning("Transition voiceover %s failed: %s", ch_id, e)
        if not skip_bgm:
            try:
                title = str(ch.get("title", ch_id))
                prompt = make_narrative_bgm_prompt(f"Chapter: {title}", f"Tone: {tone}")
                b_path = audio_dir / f"bgm_transition_{ch_id}.wav"
                generate_bgm(prompt, b_path)
                if "chapters" not in result:
                    result["chapters"] = {}
                if ch_id not in result["chapters"]:
                    result["chapters"][ch_id] = {}
                result["chapters"][ch_id]["transition_bgm_path"] = f"audio/bgm_transition_{ch_id}.wav"
            except Exception as e:
                logger.warning("Transition BGM %s failed: %s", ch_id, e)

    # 3) Ending
    ending_text = ending.get("black_screen_text", "")
    if ending_text and not skip_tts:
        try:
            v_path = audio_dir / "voiceover_ending.wav"
            generate_voiceover(ending_text, v_path, context="ending")
            result["ending"]["voice_path"] = "audio/voiceover_ending.wav"
        except Exception as e:
            logger.warning("Ending voiceover failed: %s", e)
    if ending_text and not skip_bgm:
        try:
            prompt = make_narrative_bgm_prompt("Ending sequence", "Reflective, conclusive")
            b_path = audio_dir / "bgm_ending.wav"
            generate_bgm(prompt, b_path)
            result["ending"]["bgm_path"] = "audio/bgm_ending.wav"
        except Exception as e:
            logger.warning("Ending BGM failed: %s", e)

    # 4) Per-area exploration BGM (if areas available from bundle)
    # areas can come from top-level bundle.areas when called from build_game_bundle
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import json

    out_dir = _get_output_dir()
    spec_path = Path(os.environ.get("NARRATIVE_SPEC_PATH", "narrative_spec.json"))
    if not spec_path.is_absolute():
        spec_path = Path(__file__).resolve().parent / spec_path
    if spec_path.exists():
        with open(spec_path) as f:
            spec = json.load(f)
        # Ensure we have narrative structure
        if "chapters" not in spec and "narrative" in spec:
            spec = spec.get("narrative", spec)
        r = generate_narrative_audio_for_bundle(spec, out_dir)
        print(json.dumps(r, indent=2))
    else:
        print("No narrative_spec.json found. Run from Narrative_Engine with NARRATIVE_SPEC_PATH or OUTPUT_DIR set.")
