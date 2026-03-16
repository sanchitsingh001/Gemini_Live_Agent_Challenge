from __future__ import annotations

import base64
import logging
import os
import asyncio
import time
import uuid
from typing import Optional

from google.cloud import storage
from google.genai import types

import gemini_client as gc

logger = logging.getLogger(__name__)


def _get_bucket_name() -> str:
    bucket = os.environ.get("NPC_TTS_BUCKET", "").strip()
    if not bucket:
        raise RuntimeError("NPC_TTS_BUCKET env var is required for NPC TTS.")
    return bucket


def _get_tts_model() -> str:
    return os.environ.get("NPC_TTS_MODEL", "gemini-2.5-flash-tts").strip() or "gemini-2.5-flash-tts"

def _get_live_model() -> str:
    # Default to native audio Live model for low latency speech.
    return (
        os.environ.get("NPC_LIVE_MODEL", "gemini-live-2.5-flash-native-audio").strip()
        or "gemini-live-2.5-flash-native-audio"
    )


def _use_live_api() -> bool:
    # Mandatory in this project direction: default ON.
    v = os.environ.get("NPC_TTS_USE_LIVE", "").strip().lower()
    if v in ("0", "false", "no"):
        return False
    return True


def _emotion_to_system_instruction(emotion: str) -> str:
    e = (emotion or "").lower().strip()
    if e == "scared":
        return (
            "You are voicing an NPC. Speak in a quiet, tense, slightly trembling voice. "
            "Slightly slower pace, a bit higher pitch, clear fear in the tone."
        )
    if e in ("joyful", "happy"):
        return (
            "You are voicing an NPC. Speak in a bright, joyful, warm voice. "
            "Slightly faster pace and a touch higher pitch, clearly enthusiastic."
        )
    if e in ("energetic", "excited"):
        return (
            "You are voicing an NPC. Speak in an energetic, forward-driving voice. "
            "Faster pace, confident, high energy without shouting."
        )
    if e in ("angry", "upset"):
        return (
            "You are voicing an NPC. Speak in a firm, tense voice with clear irritation. "
            "Moderate pace, emphasized consonants, but not shouting."
        )
    return (
        "You are voicing an NPC. Speak in a natural, neutral conversational tone. "
        "Clear articulation, medium pace, no exaggerated emotion."
    )


def _get_voice_name(voice_profile: dict) -> str:
    # Keep the mapping simple; voice_profile can override explicitly.
    explicit = str(voice_profile.get("voice_name", "")).strip()
    if explicit:
        return explicit
    gender = str(voice_profile.get("gender", "")).lower().strip()
    if gender == "male":
        return "Aoede"
    if gender == "female":
        return "Kore"
    return "Kore"


async def _generate_pcm_via_live(
    *,
    text: str,
    system_instruction: str,
    voice_name: str,
    language_code: str = "en-US",
) -> tuple[bytes, int]:
    """
    Use Gemini Live API (Vertex) to generate PCM audio from text.
    Returns (pcm_bytes, sample_rate_hz).
    """
    from google import genai
    from google.genai.types import HttpOptions, LiveConnectConfig, Modality, SpeechConfig, VoiceConfig, PrebuiltVoiceConfig, Content, Part

    client = genai.Client(
        vertexai=True,
        project=gc.get_project(),
        location=gc.get_location(),
        http_options=HttpOptions(api_version="v1beta1"),
    )

    config = LiveConnectConfig(
        response_modalities=[Modality.AUDIO],
        speech_config=SpeechConfig(
            voice_config=VoiceConfig(
                prebuilt_voice_config=PrebuiltVoiceConfig(
                    voice_name=voice_name,
                )
            ),
            language_code=language_code,
        ),
    )

    pcm = bytearray()
    sample_rate_hz = 24000

    async with client.aio.live.connect(model=_get_live_model(), config=config) as session:
        await session.send_client_content(
            turns=Content(
                role="user",
                parts=[
                    Part(text=f"System instruction: {system_instruction}\n\nSpeak this line only:\n{text}")
                ],
            )
        )
        async for msg in session.receive():
            sc = getattr(msg, "server_content", None)
            if sc and getattr(sc, "model_turn", None):
                for part in sc.model_turn.parts:
                    if getattr(part, "inline_data", None) and getattr(part.inline_data, "data", None):
                        data = part.inline_data.data
                        if isinstance(data, str):
                            data = base64.b64decode(data)
                        pcm.extend(data)
            if sc and getattr(sc, "turn_complete", False):
                break

    return (bytes(pcm), sample_rate_hz)


def _try_make_signed_url(blob: storage.Blob, ttl_seconds: int) -> Optional[str]:
    try:
        return blob.generate_signed_url(
            version="v4",
            expiration=ttl_seconds,
            method="GET",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Signed URL generation failed: %s", e)
        return None


def generate_npc_tts_url(
    text: str,
    *,
    npc_id: str,
    emotion: str,
    voice_profile: dict,
    max_retries: int = 3,
) -> Optional[dict]:
    """
    Generate a short-lived audio URL for an NPC line.

    Returns:
      {"audio_url": str, "voice_name": str, "emotion": str}
    or None if generation fails (caller should degrade gracefully).
    """
    if not text or not text.strip():
        return None

    model = _get_tts_model()
    voice_name = _get_voice_name(voice_profile)
    sys_inst = _emotion_to_system_instruction(emotion)

    client = gc.get_client()
    storage_client = storage.Client()
    bucket = storage_client.bucket(_get_bucket_name())

    ttl_seconds = int(os.environ.get("NPC_TTS_URL_TTL_SEC", "300"))
    allow_public_fallback = os.environ.get("NPC_TTS_PUBLIC_FALLBACK", "").lower() in ("1", "true", "yes")

    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            if _use_live_api():
                pcm_bytes, sample_rate = asyncio.run(
                    _generate_pcm_via_live(
                        text=text,
                        system_instruction=sys_inst,
                        voice_name=voice_name,
                    )
                )
            else:
                resp = client.models.generate_content(
                    model=model,
                    contents=text,
                    config=types.GenerateContentConfig(
                        system_instruction=sys_inst,
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name),
                            )
                        ),
                    ),
                )
                if not resp.candidates:
                    last_err = RuntimeError("No candidates in NPC TTS response")
                    continue
                parts = resp.candidates[0].content.parts
                if not parts:
                    last_err = RuntimeError("No parts in NPC TTS response")
                    continue
                inline = getattr(parts[0], "inline_data", None)
                if not inline or not getattr(inline, "data", None):
                    last_err = RuntimeError("No inline audio data in NPC TTS response")
                    continue
                data = inline.data
                if isinstance(data, str):
                    data = base64.b64decode(data)

                sample_rate = 24000
                if hasattr(inline, "sample_rate_hertz") and inline.sample_rate_hertz:
                    sample_rate = int(inline.sample_rate_hertz)

                pcm_bytes = data

            blob_name = f"npc_tts/{npc_id}/{uuid.uuid4().hex}.pcm"
            blob = bucket.blob(blob_name)
            blob.cache_control = f"public, max-age={ttl_seconds}"
            # Raw 16-bit little-endian PCM, mono, sample_rate Hz.
            blob.metadata = {"sample_rate_hz": str(sample_rate)}
            blob.upload_from_string(pcm_bytes, content_type=f"audio/pcm;rate={sample_rate}")

            signed = _try_make_signed_url(blob, ttl_seconds)
            if signed:
                return {
                    "audio_url": signed,
                    "blob_name": blob_name,
                    "voice_name": voice_name,
                    "emotion": emotion,
                    "sample_rate_hz": int(sample_rate),
                }

            if allow_public_fallback:
                try:
                    blob.make_public()
                    public_url = blob.public_url
                    return {
                        "audio_url": public_url,
                        "blob_name": blob_name,
                        "voice_name": voice_name,
                        "emotion": emotion,
                        "sample_rate_hz": int(sample_rate),
                    }
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    continue

            # No signed URL: return the blob_name so callers can serve it via a proxy endpoint.
            return {
                "audio_url": "",
                "blob_name": blob_name,
                "voice_name": voice_name,
                "emotion": emotion,
                "sample_rate_hz": int(sample_rate),
            }
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1 + attempt)

    if last_err:
        logger.warning("NPC TTS failed for npc_id=%s: %s", npc_id, last_err)
    return None

