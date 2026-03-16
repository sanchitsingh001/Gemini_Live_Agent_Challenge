"""
game_server/main.py

FastAPI app for the Narrator Web Game.
- GET /api/game-data?output=... - serves game_bundle.json
- POST /api/chat - NPC chat (Vertex Gemini) [legacy free-text]
- POST /api/dialogue_turn - structured turns: NPC line + player choices
"""

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.responses import Response
from pydantic import BaseModel
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gemini_client as gc
import npc_tts

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = os.environ.get("GAME_OUTPUT", "output/20260218_223200")
STATIC_DIR = PROJECT_ROOT / "game_client" / "build"
# NPC dialogue only — faster default than GEMINI_MODEL (e.g. pro). Override with GEMINI_NPC_MODEL.
NPC_CHAT_MODEL = os.environ.get("GEMINI_NPC_MODEL", "gemini-2.5-flash")

# Optional voice profile config (maps npc_id -> voice settings).
_VOICE_PROFILES_PATH = Path(__file__).with_name("npc_voice_profiles.json")
try:
    _NPC_VOICE_PROFILES: dict[str, dict] = json.loads(_VOICE_PROFILES_PATH.read_text(encoding="utf-8"))
except Exception:
    _NPC_VOICE_PROFILES = {}


def _get_npc_voice_profile(npc_id: str) -> dict:
    if npc_id in _NPC_VOICE_PROFILES:
        return _NPC_VOICE_PROFILES[npc_id]
    return _NPC_VOICE_PROFILES.get("default", {"voice_name": "Kore", "gender": "female", "base_emotion": "neutral"})


def _infer_emotion_from_reply(reply: str, npc_id: str) -> str:
    text = (reply or "").lower()
    if any(w in text for w in ("afraid", "scared", "terrified", "worried", "panic")):
        return "scared"
    if any(w in text for w in ("happy", "glad", "joy", "delighted", "wonderful")):
        return "joyful"
    if any(w in text for w in ("hurry", "quickly", "now", "urgent", "come on")):
        return "energetic"
    if any(w in text for w in ("angry", "furious", "mad", "upset")):
        return "angry"
    base = str(_get_npc_voice_profile(npc_id).get("base_emotion", "")).strip()
    return base or "neutral"


def _significant_words(text: str) -> list[str]:
    return [w.lower() for w in text.replace(".", " ").replace("'", " ").split() if len(w) > 2]


def _description_substantially_in_reply(desc: str, reply_lower: str) -> bool:
    if not desc:
        return False
    desc_lower = desc.lower()
    if desc_lower in reply_lower:
        return True
    words = _significant_words(desc)
    if not words:
        return desc_lower in reply_lower
    matches = sum(1 for w in words if w in reply_lower)
    return matches >= max(2, (len(words) + 2) // 3)


def _label_substantially_in_reply(label: str, reply_lower: str) -> bool:
    if not label:
        return False
    label_lower = label.lower()
    if label_lower in reply_lower:
        return True
    words = _significant_words(label)
    if not words:
        return label_lower in reply_lower
    matches = sum(1 for w in words if w in reply_lower)
    return matches >= max(1, (len(words) + 1) // 2)


def _job_id_from_output(output: str) -> str | None:
    """If output looks like a job id (no path separators or prefix output_jobs/<id>), return job_id."""
    if not output or not output.strip():
        return None
    s = output.strip()
    if "/" in s:
        if s.startswith("output_jobs/"):
            return s.replace("output_jobs/", "", 1).split("/")[0] or None
        return None
    return s


def load_game_bundle(output: str) -> dict:
    gcs_bucket = os.environ.get("GCS_BUCKET", "").strip()
    job_id = _job_id_from_output(output) if gcs_bucket else None
    if job_id and gcs_bucket:
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(gcs_bucket)
            blob = bucket.blob(f"output_jobs/{job_id}/game_bundle.json")
            data = blob.download_as_string()
            return json.loads(data)
        except Exception as e:
            raise HTTPException(
                status_code=404,
                detail=f"game_bundle.json not found in GCS for job {job_id}: {e}",
            ) from e

    local_path = (PROJECT_ROOT / output / "game_bundle.json").resolve()
    if local_path.exists():
        with open(local_path, "r") as f:
            return json.load(f)
    try:
        abs_path = (Path(output) / "game_bundle.json").resolve()
        if abs_path.is_file():
            with open(abs_path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    raise HTTPException(
        status_code=404,
        detail="game_bundle.json not found. Set GAME_OUTPUT to output_jobs/<id> or an output folder path.",
    )


def _npc_context(
    bundle: dict,
    npc_id: str,
    current_chapter: str,
    collected_clues: list[str],
    conversation_history: list[dict],
):
    narrative = bundle.get("narrative", {})
    chapters = narrative.get("chapters", [])
    clues = narrative.get("clues", [])
    npcs = narrative.get("npcs", [])
    npc = next((n for n in npcs if n.get("id") == npc_id), None)
    if not npc:
        return None

    current_chapter_obj = next((c for c in chapters if c.get("id") == current_chapter), None)
    available_clue_ids = set(current_chapter_obj.get("available_clue_ids", [])) if current_chapter_obj else set()
    spotlight_npc_ids = set(current_chapter_obj.get("spotlight_npc_ids", [])) if current_chapter_obj else set()
    npc_anchor_id = npc.get("anchor_id")
    npc_clues = [c for c in clues if c.get("anchor_id") == npc_anchor_id]
    npc_available_clues = [c for c in npc_clues if c.get("id") in available_clue_ids]
    if npc.get("id") in spotlight_npc_ids:
        uncollected_npc_clues = [c for c in npc_available_clues if c.get("id") not in collected_clues]
    else:
        uncollected_npc_clues = []

    chapter_state = None
    for cs in npc.get("chapter_states", []):
        if cs.get("chapter_id") == current_chapter:
            chapter_state = cs
            break
    using_fallback_state = not chapter_state
    if not chapter_state:
        chapter_state = npc.get("chapter_states", [{}])[0] if npc.get("chapter_states") else {}

    num_prior_replies = sum(1 for m in conversation_history if m.get("role") == "assistant")
    is_first_meeting = num_prior_replies == 0
    meta = (bundle.get("narrative") or {}).get("meta") or {}
    world_setting = (meta.get("visual_setting_lock") or meta.get("intro_premise") or "")[:900]
    return {
        "npc": npc,
        "chapter_state": chapter_state,
        "using_fallback_state": using_fallback_state,
        "uncollected_npc_clues": uncollected_npc_clues,
        "num_prior_replies": num_prior_replies,
        "is_first_meeting": is_first_meeting,
        "world_setting": world_setting,
    }


def _build_system_prompt(ctx: dict, dialogue_mode: bool) -> str:
    npc = ctx["npc"]
    chapter_state = ctx["chapter_state"]
    uncollected_npc_clues = ctx["uncollected_npc_clues"]
    num_prior_replies = ctx["num_prior_replies"]
    is_first_meeting = ctx["is_first_meeting"]
    using_fallback_state = ctx["using_fallback_state"]

    ws = (ctx.get("world_setting") or "").strip()
    parts = []
    if ws:
        parts.append(
            "World setting (architecture, place, culture—stay consistent; do not describe European churches or wrong-era props unless this text says so): "
            + ws
        )
    parts.extend([
        f"You are {npc.get('name', 'NPC')}, {npc.get('role', '')}.",
        f"Your vibe: {npc.get('vibe', '')}.",
        f"Public face: {npc.get('public_face', '')}.",
        f"Private truth: {npc.get('private_truth', '')}.",
    ])
    if npc.get("protected_truth"):
        parts.append(
            f"What you will resist revealing (do not give this freely): {npc['protected_truth']}. "
            "This is separate from the clues below—your clues ARE meant to be shared with the player."
        )
    if npc.get("misleading_claim"):
        parts.append(f"You may confidently say this, but it is not fully true: {npc['misleading_claim']}.")
    if npc.get("voice_style"):
        parts.append(f"Your conversational rhythm: {npc['voice_style']}")
    tension_state = chapter_state.get("tension_state")
    if tension_state:
        qualifier = " (applies to deeper secrets, NOT to the clues you must share)" if uncollected_npc_clues else ""
        parts.append(f"Your current situation: {tension_state}.{qualifier}")
    parts.extend([
        f"Current stance: {chapter_state.get('stance', '')}.",
        f"Current goal: {chapter_state.get('goal', '')}.",
        f"How you treat the player: {chapter_state.get('how_they_treat_player', '')}.",
        f"What you offer: {chapter_state.get('what_they_offer', '')}.",
        f"What you refuse: {chapter_state.get('what_they_refuse', '')}.",
    ])
    if is_first_meeting:
        parts.append(
            "IMPORTANT: This is your FIRST meeting with the player. Greet them as a stranger. "
            "Introduce yourself if appropriate."
        )
    parts.append(
        "The player is in the current story chapter. Do not reveal plot from future chapters."
    )
    if not uncollected_npc_clues:
        parts.append(
            "You have NO clues to reveal in the current chapter. Stay superficial—deflect, stay vague."
        )
    if uncollected_npc_clues:
        parts.append(
            "=== GAMEPLAY: You are a spotlight NPC. Your clues MUST be shared. Weave into dialogue."
        )
        clue_lines = []
        for c in uncollected_npc_clues:
            clue_lines.append(
                f"- Clue id={c.get('id')}, label='{c.get('label', '')}': "
                f"{c.get('interaction', '')}; description: {c.get('description', '')}; "
                f"implication: {c.get('what_it_implies', '')}."
            )
        if num_prior_replies < 3:
            parts.append(
                "Your first or second reply MUST include one clue (label + description). "
                "Do NOT deflect into unrelated small talk until you shared at least one clue."
            )
            if num_prior_replies == 0:
                parts.append("This is your first reply: include one clue in THIS message.")
        else:
            parts.append("Bring unrevealed clues up NOW.")
        parts.append(
            "Put clue IDs in clue_status when revealed. Mention clue label in message."
        )
        parts.append("Your clues:\n" + "\n".join(clue_lines))
    if ctx.get("collected_clues"):
        parts.append(
            f"Player already has clues: {', '.join(ctx['collected_clues'])}. You may reference them."
        )
    reacts_any = chapter_state.get("reacts_to_clues_any")
    reacts_all = chapter_state.get("reacts_to_clues_all")
    if reacts_any:
        parts.append(f"If the player has any of {reacts_any}, you may react more openly.")
    if reacts_all:
        parts.append(
            f"If the player has all of {reacts_all}, your behavior must SHIFT."
        )
    if uncollected_npc_clues:
        parts.append("Guarded in TONE but share clues—do not deflect. Distinct voice, not generic assistant.")
    else:
        parts.append("Soft resistance, evasion. Distinct voice.")
    sample = chapter_state.get("sample_lines", {})
    if sample:
        note = " Tone only." if uncollected_npc_clues else ""
        parts.append(f"Sample lines: {json.dumps(sample)}.{note}")
    if using_fallback_state:
        parts.append("Stay in character; no later-story spoilers.")
    parts.append("Keep responses concise (1-3 sentences) unless asked for more.")

    if dialogue_mode:
        parts.append(
            "The player selects OPTIONS from a menu (no free typing). "
            "You must output JSON with: message (your spoken line only), clue_status (array), "
            "choices (array of 3-4 objects with id and label). "
            "Each choice is something the player might say or ask next. "
            "Always include one choice with id 'bye' and label like 'Goodbye.' "
            "Ids: lowercase_snake. Labels short (under 60 chars)."
        )
    else:
        parts.append(
            'JSON only: {"message": "...", "clue_status": []}. No other keys.'
        )
    return "\n".join(parts)


def _parse_model_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        first_newline = raw.find("\n")
        if first_newline != -1:
            raw = raw[first_newline + 1 :]
        if "```" in raw:
            raw = raw.rsplit("```", 1)[0].strip()
    to_parse = raw
    if "{" in raw:
        start = raw.find("{")
        depth = 0
        end = -1
        for i, ch in enumerate(raw[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            to_parse = raw[start : end + 1]
    try:
        return json.loads(to_parse) if to_parse else {}
    except Exception:
        return {}


def _award_clues(reply: str, json_clue_ids: list[str], uncollected_npc_clues: list) -> list[str]:
    awarded = []
    reply_lower = reply.lower()
    if json_clue_ids:
        valid = {c.get("id"): c for c in uncollected_npc_clues if c.get("id")}
        for cid in json_clue_ids:
            c = valid.get(cid)
            if not c or cid in awarded:
                continue
            # Trust the model's explicit clue_status ids. We still keep the fallback
            # text-matching heuristic below for models that omit clue_status.
            awarded.append(cid)
    else:
        for c in uncollected_npc_clues:
            label = c.get("label") or ""
            desc = c.get("description") or ""
            if (
                label
                and desc
                and _label_substantially_in_reply(label, reply_lower)
                and _description_substantially_in_reply(desc, reply_lower)
                and c["id"] not in awarded
            ):
                awarded.append(c["id"])
    return awarded


app = FastAPI(title="Narrator Game API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


class ChatRequest(BaseModel):
    output: str | None = None
    npc_id: str
    message: str
    conversation_history: list[dict]
    current_chapter: str
    collected_clues: list[str]


class DialogueTurnRequest(BaseModel):
    output: str | None = None
    npc_id: str
    current_chapter: str
    collected_clues: list[str]
    conversation_history: list[dict]
    turn_kind: str  # open | choice | bye
    choice_id: str | None = None
    choice_label: str | None = None


@app.get("/api/game-data")
def get_game_data(output: str | None = Query(default=None)):
    return load_game_bundle(output or DEFAULT_OUTPUT)


@app.get("/api/npc_audio")
def npc_audio(blob: str, request: Request):
    """
    Proxy endpoint for NPC TTS audio stored in GCS.
    Used when signed URLs aren't available (e.g., Cloud Run default credentials).
    """
    bucket_name = os.environ.get("NPC_TTS_BUCKET", "").strip() or os.environ.get("GCS_BUCKET", "").strip()
    if not bucket_name:
        raise HTTPException(status_code=503, detail="NPC_TTS_BUCKET not configured.")
    try:
        from google.cloud import storage

        client = storage.Client()
        b = client.bucket(bucket_name)
        obj = b.blob(blob)
        data = obj.download_as_bytes()
        sample_rate_hz = 24000
        try:
            meta = obj.metadata or {}
            if "sample_rate_hz" in meta:
                sample_rate_hz = int(str(meta["sample_rate_hz"]))
        except Exception:
            sample_rate_hz = 24000
        headers = {
            "Content-Type": f"audio/pcm;rate={sample_rate_hz}",
            "Cache-Control": "public, max-age=300",
            "X-Audio-Sample-Rate": str(sample_rate_hz),
        }
        return Response(content=data, media_type="application/octet-stream", headers=headers)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Audio not found: {e}") from e


@app.post("/api/dialogue_turn")
def dialogue_turn(request: DialogueTurnRequest, http_request: Request):
    output = request.output or DEFAULT_OUTPUT
    bundle = load_game_bundle(output)
    ctx = _npc_context(
        bundle,
        request.npc_id,
        request.current_chapter,
        request.collected_clues,
        request.conversation_history,
    )
    if not ctx:
        raise HTTPException(status_code=404, detail="NPC not available.")
    ctx["collected_clues"] = request.collected_clues
    npc = ctx["npc"]
    uncollected = ctx["uncollected_npc_clues"]

    system_prompt = _build_system_prompt(ctx, dialogue_mode=True)
    messages = [{"role": "system", "content": system_prompt}]
    for m in request.conversation_history:
        if m.get("role") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"]})

    if request.turn_kind == "bye":
        user_block = (
            "The player chose to say goodbye and walk away. "
            "Reply with a SHORT farewell (one sentence). "
            'JSON: {"message":"...", "clue_status":[], "choices":[]}'
        )
    elif request.turn_kind == "open":
        user_block = (
            "The player just approached you to talk. "
            "Speak your opening line. If you have clues to share this chapter, work one into this first line. "
            'JSON: {"message":"...", "clue_status":[...], "choices":[{"id":"ask_x","label":"..."},...,{"id":"bye","label":"Goodbye."}]}'
        )
    else:
        lab = (request.choice_label or "").strip() or "..."
        user_block = (
            f"The player selected this option: {lab}\n"
            "Respond in character. Update choices for what they might say next (include bye). "
            'JSON: {"message":"...", "clue_status":[], "choices":[...]}'
        )

    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "project-363d072c-3554-4f41-b1e")
    try:
        reply_raw = gc.generate_text(
            system_prompt,
            user_block,
            model=NPC_CHAT_MODEL,
            temperature=0.7,
            max_retries=2,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Dialogue unavailable: {e}") from e

    parsed = _parse_model_json(reply_raw or "")
    reply = str(parsed.get("message") or parsed.get("reply") or "...").strip()
    clue_val = parsed.get("clue_status") or []
    json_clue_ids = [str(x).strip() for x in clue_val if isinstance(clue_val, list) and str(x).strip()]
    choices_raw = parsed.get("choices") or []
    choices = []
    if isinstance(choices_raw, list):
        for c in choices_raw[:6]:
            if isinstance(c, dict):
                choices.append(
                    {"id": str(c.get("id", "opt")), "label": str(c.get("label", "…"))[:80]}
                )
    has_bye = any(str(x.get("id", "")).lower() == "bye" for x in choices if isinstance(x, dict))
    if request.turn_kind != "bye" and not has_bye:
        choices.append({"id": "bye", "label": "Goodbye."})

    awarded = _award_clues(reply, json_clue_ids, uncollected)
    conversation_ended = request.turn_kind == "bye"

    emotion = _infer_emotion_from_reply(reply, request.npc_id)
    voice_profile = _get_npc_voice_profile(request.npc_id)
    tts_meta = None
    try:
        tts_meta = npc_tts.generate_npc_tts_url(
            reply,
            npc_id=request.npc_id,
            emotion=emotion,
            voice_profile=voice_profile,
        )
    except Exception:
        tts_meta = None

    resp = {
        "npc_line": reply,
        "choices": choices,
        "awarded_clues": awarded,
        "conversation_ended": conversation_ended,
    }
    if tts_meta and isinstance(tts_meta, dict):
        audio_url = str(tts_meta.get("audio_url", "") or "")
        blob_name = str(tts_meta.get("blob_name", "") or "")
        sample_rate_hz = int(tts_meta.get("sample_rate_hz", 24000) or 24000)
        if not audio_url and blob_name:
            # Serve via our proxy endpoint to avoid signed URL signing requirements.
            from urllib.parse import quote

            base = str(http_request.base_url).rstrip("/")
            # Cloud Run may report internal scheme as http; prefer forwarded proto for client URLs.
            forwarded_proto = (http_request.headers.get("x-forwarded-proto") or "").lower().strip()
            if forwarded_proto == "https" and base.startswith("http://"):
                base = "https://" + base[len("http://") :]
            audio_url = f"{base}/api/npc_audio?blob={quote(blob_name, safe='')}"
        resp["npc_audio_url"] = audio_url
        resp["npc_voice_id"] = str(tts_meta.get("voice_name", ""))
        resp["emotion"] = str(tts_meta.get("emotion", emotion))
        resp["npc_audio_sample_rate_hz"] = sample_rate_hz
    return resp


@app.post("/api/chat")
def chat(request: ChatRequest):
    output = request.output or DEFAULT_OUTPUT
    bundle = load_game_bundle(output)
    ctx = _npc_context(
        bundle,
        request.npc_id,
        request.current_chapter,
        request.collected_clues,
        request.conversation_history,
    )
    if not ctx:
        raise HTTPException(status_code=404, detail="NPC not available.")
    ctx["collected_clues"] = request.collected_clues
    system_prompt = _build_system_prompt(ctx, dialogue_mode=False)

    messages = [{"role": "system", "content": system_prompt}]
    for m in request.conversation_history:
        if m.get("role") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": request.message})

    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "project-363d072c-3554-4f41-b1e")
    hist = "\n".join(
        f"{m['role']}: {m['content']}" for m in messages[1:] if m.get("role") and m.get("content")
    )
    user_block = f"Conversation so far:\n{hist}\n\nPlayer says: {request.message}\n\nReply JSON only: message, clue_status"
    try:
        reply_raw = gc.generate_text(
            system_prompt,
            user_block,
            model=NPC_CHAT_MODEL,
            temperature=0.7,
            max_retries=2,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Chat unavailable: {e}") from e

    parsed = _parse_model_json(reply_raw or "")
    reply = str(parsed.get("message") or parsed.get("reply") or "...").strip()
    clue_val = parsed.get("clue_status") or []
    json_clue_ids = [str(x).strip() for x in clue_val if isinstance(clue_val, list) and str(x).strip()]
    awarded = _award_clues(reply, json_clue_ids, ctx["uncollected_npc_clues"])
    return {"reply": reply, "awarded_clues": awarded}


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}")
    def serve_spa(path: str):
        p = STATIC_DIR / path
        if p.is_file():
            return FileResponse(p)
        return FileResponse(STATIC_DIR / "index.html")
else:

    @app.get("/")
    def root():
        return {"message": "Narrator Game API. Build game_client and restart."}
