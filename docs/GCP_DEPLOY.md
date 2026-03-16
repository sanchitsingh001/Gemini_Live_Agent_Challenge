# GCP Full Pipeline Deployment

One-time setup and deploy steps for running the Narrative Engine on GCP: game server (Cloud Run), narrative server (Cloud Run), pipeline job (Cloud Run Job), GCS bucket, and Firebase Hosting.

---

## 1. GCS bucket and CORS

Create a bucket for pipeline outputs and (optionally) set CORS so web games can call the game server from the browser.

### Create the bucket

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GCS_BUCKET="${GOOGLE_CLOUD_PROJECT}-narrative-output"
export GOOGLE_CLOUD_LOCATION=us-central1

gcloud storage buckets create "gs://${GCS_BUCKET}" \
  --project="${GOOGLE_CLOUD_PROJECT}" \
  --location="${GOOGLE_CLOUD_LOCATION}"
```

Layout: `gs://<bucket>/output_jobs/<job_id>/` will contain `game_bundle.json`, `export/web/`, `story_input.txt`, `game_url.txt`, `error.txt`, etc.

### Set CORS (optional)

If you serve web games from a different origin and they call the game server, you may need CORS on the bucket. Save this as `cors.json`:

```json
[
  {
    "origin": ["*"],
    "method": ["GET", "HEAD"],
    "responseHeader": ["Content-Type"],
    "maxAgeSeconds": 3600
  }
]
```

Then:

```bash
gcloud storage buckets update "gs://${GCS_BUCKET}" --cors-file=cors.json
```

Or use the script: `./scripts/setup_gcs_bucket.sh` (see below).

---

## 2. Game server (Cloud Run)

The game server serves `game_bundle.json` and NPC chat. When `GCS_BUCKET` is set, it loads bundles from GCS by `output=<job_id>`.

```bash
cd Narrative_Engine
# Build and deploy (from repo root so Dockerfile can copy game_server and parent)
docker build -f game_server/Dockerfile -t gcr.io/${GOOGLE_CLOUD_PROJECT}/narrative-game-server .
docker push gcr.io/${GOOGLE_CLOUD_PROJECT}/narrative-game-server

gcloud run deploy narrative-game-server \
  --image gcr.io/${GOOGLE_CLOUD_PROJECT}/narrative-game-server \
  --region "${GOOGLE_CLOUD_LOCATION}" \
  --platform managed \
  --set-env-vars "GCS_BUCKET=${GCS_BUCKET},GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT},GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION}" \
  --allow-unauthenticated
```

Note: The game server needs a Dockerfile (see below if not present). After deploy, set `CHAT_API_BASE` to the service URL (e.g. `https://narrative-game-server-xxxx.run.app`) for the pipeline job and narrative server.

---

## 3. Narrative server (Cloud Run)

Deploy the narrative server so it can accept POST /generate, write the story to GCS, start the pipeline Cloud Run Job, and serve GET /jobs/<job_id> for polling (game_url or error).

```bash
cd Narrative_Engine/narrative_server
gcloud run deploy narrative-server --source . --region "${GOOGLE_CLOUD_LOCATION}" \
  --set-env-vars "GCS_BUCKET=${GCS_BUCKET},GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT},GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION},PIPELINE_JOB_NAME=narrative-pipeline-job,PIPELINE_JOB_REGION=${GOOGLE_CLOUD_LOCATION},CHAT_API_BASE=https://narrative-game-server-xxxx.run.app" \
  --allow-unauthenticated
```

Or build a Docker image from the repo root (copy narrative_server and project root for imports) and deploy that image.

Replace `https://narrative-game-server-xxxx.run.app` with your actual game server URL. When `GCS_BUCKET` and `PIPELINE_JOB_NAME` are set, POST /generate uploads the story to GCS and starts the Cloud Run Job; GET /jobs/<job_id> polls execution state and returns `game_url` or `error` from GCS when the job finishes.

---

## 4. Pipeline job (Cloud Run Job)

Build the pipeline job image (Python + Godot 4 + Web export templates), push to Artifact Registry or GCR, then create the Cloud Run Job. The job reads story from GCS, runs the full pipeline, uploads to GCS, deploys to Firebase Hosting, and writes `game_url.txt` or `error.txt`.

See `pipeline_job/README.md` and Section 7 below.

---

## 5. Firebase Hosting

Initialize Firebase in the project and configure Hosting. The pipeline job will deploy each game under `/<job_id>/`. Base URL: `https://<project-id>.web.app/<job_id>/`.

---

## 6. Environment variables summary

| Variable | Where | Purpose |
|---------|--------|---------|
| `GOOGLE_CLOUD_PROJECT` | All | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | All | Region (e.g. us-central1) |
| `GCS_BUCKET` | Game server, Narrative server, Pipeline job | Bucket for output_jobs/ |
| `CHAT_API_BASE` | Pipeline job, Narrative server | Game server URL for runtime_config |
| `PIPELINE_JOB_NAME` | Narrative server | Cloud Run Job name to execute |
| `PIPELINE_JOB_REGION` | Narrative server | Region of the job |
| `FIREBASE_PROJECT` / deploy credentials | Pipeline job | Deploy web build to Hosting |

---

## 7. Order of operations

1. Create GCS bucket (and CORS if needed).
2. Deploy game server → note its URL → set as `CHAT_API_BASE`.
3. Create and deploy the pipeline Cloud Run Job.
4. Deploy narrative server with `CHAT_API_BASE`, `PIPELINE_JOB_NAME`, `GCS_BUCKET`.
5. Configure Firebase Hosting so the pipeline job can deploy to it.
