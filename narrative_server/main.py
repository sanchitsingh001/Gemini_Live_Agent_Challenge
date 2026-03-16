"""
Narrative Engine Server — local pipeline or GCP Cloud Run Job.

POST /generate → when GCS_BUCKET + PIPELINE_JOB_NAME set: upload story to GCS, start Cloud Run Job.
                 else: run pipeline in-process (output_jobs/<id>/).
GET /jobs/<id>  → status (queued | running | completed | failed), and on completion: game_url or error.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .run_pipeline import run_pipeline

LOG_DIR = Path(os.environ.get("PROJECT_ROOT", ".")) / "logs"


def _setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "narrator.log"
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


_setup_logging()
logger = logging.getLogger("narrator")

app = FastAPI(title="Narrative Engine API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.Lock()
job_queue: list[tuple[str, str]] = []
queue_lock = threading.Lock()
_worker_started = False

# Cloud mode: when set, POST /generate uploads story to GCS and starts Cloud Run Job instead of in-process pipeline
GCS_BUCKET = os.environ.get("GCS_BUCKET", "").strip()
PIPELINE_JOB_NAME = os.environ.get("PIPELINE_JOB_NAME", "").strip()
PIPELINE_JOB_REGION = os.environ.get("PIPELINE_JOB_REGION", os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")).strip()
CLOUD_MODE = bool(GCS_BUCKET and PIPELINE_JOB_NAME)


def _upload_story_to_gcs(job_id: str, story: str) -> None:
    from google.cloud import storage
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(f"output_jobs/{job_id}/story_input.txt")
    blob.upload_from_string(story, content_type="text/plain")


def _get_project_number(project_id: str) -> str | None:
    """Resolve project ID to project number (v1 Run API uses number as namespace)."""
    try:
        import urllib.request
        import json as _json
        import google.auth
        import google.auth.transport.requests
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        req = urllib.request.Request(
            f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}",
            headers={"Authorization": f"Bearer {credentials.token}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())
        return str(data.get("projectNumber", "")) or None
    except Exception as e:
        logger.debug("get project number: %s", e)
        return None


def _run_cloud_pipeline_job(job_id: str) -> str | None:
    """Start Cloud Run Job with JOB_ID env override via REST API. Returns execution name or None.
    Tries v2 run first (project-level invoker often works); falls back to v1 with project number."""
    import urllib.request
    import json as _json
    import urllib.error

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    if not project_id:
        logger.warning("GOOGLE_CLOUD_PROJECT not set; job may fail")

    def _auth_token() -> str:
        import google.auth
        import google.auth.transport.requests
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        return credentials.token

    overrides_body = {
        "overrides": {
            "containerOverrides": [
                {
                    "env": [
                        {"name": "JOB_ID", "value": job_id},
                        {"name": "GCS_BUCKET", "value": GCS_BUCKET},
                    ]
                }
            ]
        }
    }

    # 1) Try v2 run (project-level run.invoker often applies here)
    try:
        token = _auth_token()
        job_full = f"projects/{project_id}/locations/{PIPELINE_JOB_REGION}/jobs/{PIPELINE_JOB_NAME}"
        url = f"https://run.googleapis.com/v2/{job_full}:run"
        req = urllib.request.Request(
            url,
            data=_json.dumps(overrides_body).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode())
        # v2 returns Operation; execution name may be in metadata or we derive from operation name
        execution_name = (data.get("response") or {}).get("name") or (data.get("metadata") or {}).get("name")
        if not execution_name and data.get("name"):
            execution_name = data["name"].replace("/operations/", "/executions/")
        if execution_name:
            return execution_name
    except urllib.error.HTTPError as e:
        if e.code != 403:
            logger.exception("Failed to start Cloud Run Job (v2): %s", e)
            raise
        logger.warning("v2 run returned 403, trying v1 run with project number")
    except Exception as e:
        logger.exception("Failed to start Cloud Run Job (v2): %s", e)
        raise

    # 2) Fallback: v1 run with project number as namespace
    try:
        token = _auth_token()
        namespace = os.environ.get("GOOGLE_CLOUD_PROJECT_NUMBER") or _get_project_number(project_id) or project_id
        job_name_v1 = f"namespaces/{namespace}/jobs/{PIPELINE_JOB_NAME}"
        url = f"https://run.googleapis.com/apis/run.googleapis.com/v1/{job_name_v1}:run"
        req = urllib.request.Request(
            url,
            data=_json.dumps(overrides_body).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode())
        execution_name = (data.get("metadata") or {}).get("name")
        if execution_name:
            return execution_name
    except urllib.error.HTTPError as e:
        logger.exception("Failed to start Cloud Run Job (v1): %s", e)
        raise
    except Exception as e:
        logger.exception("Failed to start Cloud Run Job (v1): %s", e)
        raise

    raise RuntimeError("Run API returned no execution name (tried v2 and v1)")


def _get_execution_state(execution_name: str) -> str | None:
    """Return 'SUCCEEDED', 'FAILED', 'RUNNING', or None if unknown.
    Supports v1 (namespaces/.../executions/...) and v2 execution names."""
    import urllib.request
    import json as _json
    try:
        import google.auth
        import google.auth.transport.requests
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        token = credentials.token
        if execution_name.startswith("namespaces/"):
            # v1 API
            url = f"https://run.googleapis.com/apis/run.googleapis.com/v1/{execution_name}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read().decode())
            for c in data.get("status", {}).get("conditions") or []:
                if c.get("type") == "Completed":
                    return "SUCCEEDED" if c.get("status") == "True" else "FAILED"
            return "RUNNING"
        # v2 API
        url = f"https://run.googleapis.com/v2/{execution_name}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read().decode())
        conditions = data.get("conditions") or []
        if conditions:
            raw = conditions[0].get("state")
            if raw in ("CONDITION_SUCCEEDED", "SUCCEEDED"):
                return "SUCCEEDED"
            if raw in ("CONDITION_FAILED", "FAILED"):
                return "FAILED"
            return raw
        return None
    except Exception as e:
        logger.debug("get_execution %s: %s", execution_name, e)
        return None


def _read_gcs_text(bucket: str, path: str) -> str | None:
    try:
        from google.cloud import storage
        client = storage.Client()
        blob = client.bucket(bucket).blob(path)
        return blob.download_as_string().decode("utf-8").strip()
    except Exception as e:
        logger.debug("read_gcs %s/%s: %s", bucket, path, e)
        return None


def _write_job_meta_gcs(job_id: str, execution_name: str) -> None:
    """Persist job metadata to GCS so polling survives server restarts/deploys."""
    try:
        import json as _json
        from google.cloud import storage
        client = storage.Client()
        blob = client.bucket(GCS_BUCKET).blob(f"output_jobs/{job_id}/job_meta.json")
        blob.upload_from_string(
            _json.dumps({"execution_name": execution_name, "status": "running"}),
            content_type="application/json",
        )
    except Exception as e:
        logger.warning("write job_meta GCS %s: %s", job_id[:8], e)


def _load_job_from_gcs(job_id: str) -> dict[str, Any] | None:
    """If this job was started in cloud mode, rehydrate from GCS job_meta.json or from output files."""
    import json as _json
    prefix = f"output_jobs/{job_id}"
    raw = _read_gcs_text(GCS_BUCKET, f"{prefix}/job_meta.json")
    if raw:
        try:
            meta = _json.loads(raw)
            return {
                "status": meta.get("status", "running"),
                "stage": None,
                "output_id": None,
                "output_dir": None,
                "export_paths": None,
                "game_url": None,
                "error": None,
                "execution_name": meta.get("execution_name"),
            }
        except Exception as e:
            logger.debug("load job_meta %s: %s", job_id[:8], e)
    # Fallback: no job_meta (e.g. job created before we added it, or after deploy). Infer from GCS files.
    game_url = _read_gcs_text(GCS_BUCKET, f"{prefix}/game_url.txt")
    err = _read_gcs_text(GCS_BUCKET, f"{prefix}/error.txt")
    stage = _read_gcs_text(GCS_BUCKET, f"{prefix}/stage.txt")
    story_exists = _read_gcs_text(GCS_BUCKET, f"{prefix}/story_input.txt") is not None
    if not story_exists and not game_url and not err:
        return None
    status = "completed" if game_url else ("failed" if err else "running")
    return {
        "status": status,
        "stage": stage,
        "output_id": job_id if game_url else None,
        "output_dir": None,
        "export_paths": None,
        "game_url": game_url,
        "error": err,
        "execution_name": None,
    }


class GenerateRequest(BaseModel):
    story: str


class GenerateResponse(BaseModel):
    job_id: str
    status: str


class JobResponse(BaseModel):
    job_id: str
    status: str
    stage: str | None = None
    output_id: str | None = None
    output_dir: str | None = None
    export_paths: dict[str, str] | None = None
    game_url: str | None = None
    error: str | None = None


def _worker_loop() -> None:
    project_root = Path(os.environ.get("PROJECT_ROOT", os.getcwd())).resolve()

    while True:
        item = None
        with queue_lock:
            if job_queue:
                item = job_queue.pop(0)
        if item is None:
            import time
            time.sleep(1)
            continue

        job_id, story = item
        with jobs_lock:
            jobs[job_id]["status"] = "running"
        logger.info("job %s running (story_len=%d)", job_id[:8], len(story))

        try:
            output_id, output_dir = run_pipeline(story=story, project_root=project_root)
            export_paths = {
                "web_zip": str(Path(output_dir) / "export" / f"{output_id}-web.zip"),
                "game_bundle": str(Path(output_dir) / "game_bundle.json"),
            }
            with jobs_lock:
                jobs[job_id]["status"] = "completed"
                jobs[job_id]["output_id"] = output_id
                jobs[job_id]["output_dir"] = output_dir
                jobs[job_id]["export_paths"] = export_paths
                jobs[job_id]["error"] = None
            logger.info("job %s completed %s", job_id[:8], output_dir)
        except Exception as e:
            with jobs_lock:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["error"] = str(e)
                jobs[job_id]["output_id"] = None
                jobs[job_id]["output_dir"] = None
                jobs[job_id]["export_paths"] = None
            logger.exception("job %s failed: %s", job_id[:8], e)


def _ensure_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    with queue_lock:
        if _worker_started:
            return
        threading.Thread(target=_worker_loop, daemon=True).start()
        _worker_started = True


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    if not req.story or not req.story.strip():
        raise HTTPException(status_code=400, detail="story is required")
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "project-363d072c-3554-4f41-b1e")

    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {
            "status": "queued",
            "stage": None,
            "output_id": None,
            "output_dir": None,
            "export_paths": None,
            "game_url": None,
            "error": None,
            "execution_name": None,
        }

    if CLOUD_MODE:
        try:
            _upload_story_to_gcs(job_id, req.story.strip())
            execution_name = _run_cloud_pipeline_job(job_id)
            if not execution_name:
                with jobs_lock:
                    jobs[job_id]["status"] = "failed"
                    jobs[job_id]["error"] = "Failed to start pipeline job (no execution returned)."
                raise HTTPException(status_code=503, detail="Failed to start pipeline job.")
            with jobs_lock:
                jobs[job_id]["status"] = "running"
                jobs[job_id]["execution_name"] = execution_name
            _write_job_meta_gcs(job_id, execution_name)
            logger.info("job %s started (cloud) execution=%s", job_id[:8], execution_name)
            return GenerateResponse(job_id=job_id, status="running")
        except HTTPException:
            raise
        except Exception as e:
            with jobs_lock:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["error"] = str(e)
            logger.exception("job %s cloud start failed: %s", job_id[:8], e)
            raise HTTPException(status_code=503, detail=str(e))

    with queue_lock:
        job_queue.append((job_id, req.story.strip()))
    logger.info("job %s queued", job_id[:8])
    _ensure_worker()
    return GenerateResponse(job_id=job_id, status="queued")


def _refresh_cloud_job_status(job_id: str, j: dict[str, Any]) -> None:
    """If cloud job has execution_name, poll execution state and GCS game_url/error."""
    execution_name = j.get("execution_name")
    if not execution_name:
        return
    stage = _read_gcs_text(GCS_BUCKET, f"output_jobs/{job_id}/stage.txt")
    state = _get_execution_state(execution_name)
    with jobs_lock:
        jobs[job_id]["stage"] = stage

    # Always check for error.txt; if present, treat job as failed regardless of
    # what the Run API reports (some API responses only reflect Job existence,
    # not task failure).
    err = _read_gcs_text(GCS_BUCKET, f"output_jobs/{job_id}/error.txt")
    if err:
        with jobs_lock:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = err or "Pipeline job failed."
            jobs[job_id]["game_url"] = None
            jobs[job_id]["output_id"] = None
        return

    if state == "SUCCEEDED":
        game_url = _read_gcs_text(GCS_BUCKET, f"output_jobs/{job_id}/game_url.txt")
        # Only mark completed when we actually have a game_url; otherwise keep
        # the job in running state so polling can continue until either
        # game_url.txt or error.txt appears.
        if game_url:
            with jobs_lock:
                jobs[job_id]["status"] = "completed"
                jobs[job_id]["game_url"] = game_url
                jobs[job_id]["output_id"] = job_id
                jobs[job_id]["error"] = None
    elif state == "FAILED":
        # Fallback: state says FAILED but we didn't find error.txt above; record
        # a generic failure so the client isn't stuck in 'running' forever.
        with jobs_lock:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = jobs[job_id].get("error") or "Pipeline job failed."
            jobs[job_id]["game_url"] = None
            jobs[job_id]["output_id"] = None
    # else still running


def _reconcile_status_from_gcs(job_id: str, j: dict[str, Any]) -> None:
    """Final guard: ensure status reflects GCS outputs even if in-memory state drifted."""
    if not CLOUD_MODE:
        return
    prefix = f"output_jobs/{job_id}"
    game_url = _read_gcs_text(GCS_BUCKET, f"{prefix}/game_url.txt")
    err = _read_gcs_text(GCS_BUCKET, f"{prefix}/error.txt")
    with jobs_lock:
        if game_url:
            j["status"] = "completed"
            j["game_url"] = game_url
            j["output_id"] = job_id
            j["error"] = None
        elif err:
            j["status"] = "failed"
            j["error"] = err or "Pipeline job failed."
            j["game_url"] = None


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    with jobs_lock:
        j = jobs.get(job_id)
    if j is None and CLOUD_MODE:
        j = _load_job_from_gcs(job_id)
        if j is not None:
            with jobs_lock:
                jobs[job_id] = j
    if j is None:
        raise HTTPException(status_code=404, detail="job not found")
    if CLOUD_MODE:
        if j.get("execution_name"):
            _refresh_cloud_job_status(job_id, dict(j))
        # Always reconcile from GCS so we never report completed/failed without
        # checking for game_url.txt / error.txt.
        _reconcile_status_from_gcs(job_id, j)
        with jobs_lock:
            jobs[job_id] = dict(j)
    return JobResponse(
        job_id=job_id,
        status=j["status"],
        stage=j.get("stage"),
        output_id=j.get("output_id"),
        output_dir=j.get("output_dir"),
        export_paths=j.get("export_paths"),
        game_url=j.get("game_url"),
        error=j.get("error"),
    )
