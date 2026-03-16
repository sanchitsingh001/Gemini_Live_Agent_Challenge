"""
Shared Vertex AI Gemini client (Application Default Credentials).

Env:
  GOOGLE_CLOUD_PROJECT  (default: project-363d072c-3554-4f41-b1e)
  GOOGLE_CLOUD_LOCATION (default: us-central1)
  GEMINI_MODEL          (default: gemini-2.5-pro — GA; override for speed: gemini-2.5-flash)
  GEMINI_NPC_MODEL      (game_server NPC chat only; default gemini-2.5-flash)
Run once: gcloud auth application-default login
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

DEFAULT_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "project-363d072c-3554-4f41-b1e")
DEFAULT_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
# GA on Vertex (see Model Garden). Unversioned gemini-2.0-flash often 404s; use gemini-2.0-flash-001 if needed.
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
DEFAULT_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "imagen-3.0-generate-002")

_client = None


def get_project() -> str:
    return os.environ.get("GOOGLE_CLOUD_PROJECT", DEFAULT_PROJECT).strip() or DEFAULT_PROJECT


def get_location() -> str:
    return os.environ.get("GOOGLE_CLOUD_LOCATION", DEFAULT_LOCATION).strip() or DEFAULT_LOCATION


def get_client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(
            vertexai=True,
            project=get_project(),
            location=get_location(),
        )
    return _client


def _contents_from_messages(system: str, user: str) -> List[Any]:
    from google.genai import types

    return [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=f"System instructions:\n{system}\n\nUser:\n{user}"),
            ],
        )
    ]


def generate_text(
    system: str,
    user: str,
    *,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_retries: int = 5,
) -> str:
    """Single-turn text generation; returns assistant text."""
    from google.genai import types

    m = model or DEFAULT_MODEL
    client = get_client()
    cfg = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=8192,
    )
    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(
                model=m,
                contents=_contents_from_messages(system, user),
                config=cfg,
            )
            if resp.text:
                return resp.text.strip()
            last_err = RuntimeError("empty response")
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if "429" in msg or "resource exhausted" in msg or "quota" in msg:
                time.sleep(min(90, 10 * (attempt + 1)))
            else:
                time.sleep(1 + attempt)
    if last_err:
        raise last_err
    raise RuntimeError("generate_text failed")


def generate_json(
    system: str,
    user: str,
    *,
    model: Optional[str] = None,
    temperature: float = 0.4,
    max_retries: int = 5,
) -> Any:
    """Ask for JSON-only reply; parse object or array."""
    from google.genai import types

    m = model or DEFAULT_MODEL
    schema_hint = (
        "\n\nReply with valid JSON only. No markdown fences, no commentary."
    )
    full_user = user + schema_hint
    client = get_client()
    cfg = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=8192,
        response_mime_type="application/json",
    )
    text = ""
    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(
                model=m,
                contents=_contents_from_messages(system, full_user),
                config=cfg,
            )
            text = (resp.text or "").strip()
            if not text:
                last_err = RuntimeError("empty JSON response")
                continue
            return json.loads(text)
        except json.JSONDecodeError as e:
            last_err = e
            fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if fence:
                try:
                    return json.loads(fence.group(1).strip())
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            last_err = e
            time.sleep(2 + attempt)
    if last_err:
        raise last_err
    raise RuntimeError("generate_json failed")


MIN_IMAGE_BYTES = 256  # Godot treats smaller files as invalid; PNG header + minimal data


def generate_image_bytes(
    prompt: str,
    *,
    aspect_ratio: str = "1:1",
    model: Optional[str] = None,
    max_retries: int = 5,
) -> bytes:
    """Vertex Imagen; returns PNG bytes. Retries on rate limit / transient errors; validates min size."""
    import io

    import vertexai
    from vertexai.preview.vision_models import ImageGenerationModel

    vertexai.init(project=get_project(), location=get_location())
    m = model or DEFAULT_IMAGE_MODEL
    ig = ImageGenerationModel.from_pretrained(m)
    ar = aspect_ratio if aspect_ratio in ("1:1", "9:16", "16:9", "4:3", "3:4") else "1:1"
    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            r = ig.generate_images(prompt=prompt, number_of_images=1, aspect_ratio=ar)
            if not r.images:
                last_err = RuntimeError("no image in response")
                continue
            img = r.images[0]
            if hasattr(img, "_image_bytes") and img._image_bytes:
                raw = img._image_bytes
            else:
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                raw = buf.getvalue()
            if raw and len(raw) >= MIN_IMAGE_BYTES:
                return raw
            last_err = RuntimeError(f"image too small ({len(raw) if raw else 0} bytes)")
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if "429" in msg or "resource exhausted" in msg or "quota" in msg:
                time.sleep(min(90, 10 * (attempt + 1)))
            else:
                time.sleep(1 + attempt)
    if last_err:
        raise last_err
    raise RuntimeError("generate_image_bytes failed after retries")


def vision_text_prompt(image_bytes: bytes, mime_type: str, prompt: str) -> str:
    """Single image + text → model text reply."""
    from google.genai import types

    client = get_client()
    parts = [
        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        types.Part.from_text(text=prompt),
    ]
    resp = client.models.generate_content(
        model=DEFAULT_MODEL,
        contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=256),
    )
    return (resp.text or "").strip()
