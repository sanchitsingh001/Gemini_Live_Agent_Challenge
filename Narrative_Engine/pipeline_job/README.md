# Pipeline Job (Cloud Run Job)

Runs the full Narrative Engine pipeline in GCP: story from GCS → narrative spec → world → game_bundle → audio → Godot web export → upload to GCS → write `game_url.txt` or `error.txt`.

## Build (from Narrative_Engine root)

```bash
cd Narrative_Engine
docker build -f pipeline_job/Dockerfile -t gcr.io/${GOOGLE_CLOUD_PROJECT}/narrative-pipeline-job .
docker push gcr.io/${GOOGLE_CLOUD_PROJECT}/narrative-pipeline-job
```

Requires Docker build context at repo root so `COPY .` includes all pipeline scripts and `godot_world/`. Uses `robpc/godot-headless:4.3-web` for Godot 4 + Web export templates.

## Create the Cloud Run Job

```bash
gcloud run jobs create narrative-pipeline-job \
  --image gcr.io/${GOOGLE_CLOUD_PROJECT}/narrative-pipeline-job \
  --region ${GOOGLE_CLOUD_LOCATION} \
  --set-env-vars "GCS_BUCKET=${GCS_BUCKET},GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT},GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION},CHAT_API_BASE=${CHAT_API_BASE}" \
  --task-timeout 3600 \
  --max-retries 0
```

Set `CHAT_API_BASE` to your deployed game server URL (e.g. `https://narrative-game-server-xxxx.run.app`). Optional: `FIREBASE_HOSTING_BASE_URL`, `FIREBASE_PROJECT`, `FIREBASE_TOKEN` for deploy to Firebase Hosting from the job.

## Job execution

The job is started by the narrative server when you POST `/generate` (cloud mode). It expects:

- **Env (set at run time by narrative server):** `JOB_ID`, `GCS_BUCKET`
- **Precondition:** `gs://${GCS_BUCKET}/output_jobs/${JOB_ID}/story_input.txt` exists (narrative server uploads it before starting the job).

The job writes `game_url.txt` or `error.txt` to `gs://${GCS_BUCKET}/output_jobs/${JOB_ID}/` so the narrative server can return the result when you poll GET `/jobs/<job_id>`.
