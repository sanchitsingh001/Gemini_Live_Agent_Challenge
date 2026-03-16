"""
Cloud Run: creative-director style stream — text beats + optional Imagen stills.
Same Vertex ADC as the rest of the engine.
"""

import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Narrative interleaved agent")


class StoryRequest(BaseModel):
    premise: str
    beats: int = 3


def _stream(premise: str, beats: int):
    import gemini_client as gc

    yield f"data: {json.dumps({'type': 'meta', 'text': premise})}\n\n"
    for i in range(max(1, min(beats, 8))):
        system = "You write one short story beat (2-4 sentences). JSON only: {\"beat\": \"...\"}"
        user = f"Premise: {premise}\nBeat {i+1} of {beats}. Continue the story."
        try:
            obj = gc.generate_json(system, user, temperature=0.8)
            text = (obj.get("beat") or obj.get("text") or str(obj))[:1200]
        except Exception as e:
            text = f"(beat unavailable: {e})"
        yield f"data: {json.dumps({'type': 'text', 'beat': i, 'text': text})}\n\n"
        try:
            img_prompt = (
                f"Cinematic illustration, no text. Setting must match the premise (architecture + culture)—do not default to European church or castle. "
                f"Premise: {premise[:400]}. Scene: {text[:280]}"
            )
            raw = gc.generate_image_bytes(img_prompt, aspect_ratio="1:1")
            b64 = base64.standard_b64encode(raw).decode("ascii")
            yield f"data: {json.dumps({'type': 'image', 'beat': i, 'mime': 'image/png', 'b64': b64})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'image_skip', 'beat': i, 'err': str(e)})}\n\n"
    yield "data: {\"type\":\"done\"}\n\n"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/stream")
def stream(req: StoryRequest):
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "project-363d072c-3554-4f41-b1e")
    return StreamingResponse(
        _stream(req.premise.strip(), req.beats),
        media_type="text/event-stream",
    )
