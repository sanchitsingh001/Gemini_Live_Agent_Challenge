#!/bin/bash
# Cloud Run Job entrypoint: fetch story from GCS, run pipeline, write runtime_config, export, upload to GCS, write game_url.txt or error.txt.
# Required env: JOB_ID, GCS_BUCKET, CHAT_API_BASE, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION
# Optional: FIREBASE_HOSTING_BASE_URL (e.g. https://PROJECT.web.app), GENERATE_AUDIO (default 1)

set -e

JOB_ID="${JOB_ID:?JOB_ID required}"
GCS_BUCKET="${GCS_BUCKET:?GCS_BUCKET required}"
CHAT_API_BASE="${CHAT_API_BASE:-}"
GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-}"
GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
FIREBASE_HOSTING_BASE_URL="${FIREBASE_HOSTING_BASE_URL:-}"
OUTPUT_DIR="/workspace/output_jobs/${JOB_ID}"
STORY_PATH="/workspace/story_input.txt"
RUNTIME_CONFIG_PATH="${OUTPUT_DIR}/runtime_config.json"

update_stage() {
  local msg="$1"
  echo "$msg" > "${OUTPUT_DIR}/stage.txt"
  python3 - <<'PY'
from google.cloud import storage
import os

bucket_name = os.environ["GCS_BUCKET"]
job_id = os.environ["JOB_ID"]
client = storage.Client()
bucket = client.bucket(bucket_name)
blob = bucket.blob(f"output_jobs/{job_id}/stage.txt")
blob.upload_from_filename(f"/workspace/output_jobs/{job_id}/stage.txt", content_type="text/plain")
PY
}

write_error() {
  local msg="$1"
  update_stage "failed: ${msg}"
  echo "$msg" > "${OUTPUT_DIR}/error.txt"
  # Upload error.txt to GCS so narrative server can read it
  if command -v gcloud &>/dev/null; then
    gcloud storage cp "${OUTPUT_DIR}/error.txt" "gs://${GCS_BUCKET}/output_jobs/${JOB_ID}/error.txt" || true
  elif python3 -c "from google.cloud import storage" 2>/dev/null; then
    python3 -c "
from google.cloud import storage
import sys
c = storage.Client()
b = c.bucket('${GCS_BUCKET}')
blob = b.blob('output_jobs/${JOB_ID}/error.txt')
blob.upload_from_filename('${OUTPUT_DIR}/error.txt', content_type='text/plain')
"
  fi
  exit 1
}

mkdir -p "$OUTPUT_DIR"

# 1) Download story from GCS
echo "▶ Downloading story from gs://${GCS_BUCKET}/output_jobs/${JOB_ID}/story_input.txt"
update_stage "downloading_story"
if python3 -c "
from google.cloud import storage
c = storage.Client()
b = c.bucket('${GCS_BUCKET}')
blob = b.blob('output_jobs/${JOB_ID}/story_input.txt')
blob.download_to_filename('${STORY_PATH}')
" 2>/dev/null; then
  :
else
  write_error "Failed to download story_input.txt from GCS for job ${JOB_ID}"
fi
[ -f "$STORY_PATH" ] || write_error "story_input.txt not found after download"

# 2) Run pipeline up to (and including) audio; skip Godot export for now so we can inject runtime_config
echo "▶ Running world pipeline (no export yet)..."
update_stage "running_pipeline"
export OUTPUT_DIR
export NARRATIVE_SPEC_PATH="${OUTPUT_DIR}/narrative_spec.json"
export RUN_EXPORT=0
cd /workspace
bash ./run_world_pipeline.sh "$STORY_PATH" --skip-3d || write_error "run_world_pipeline.sh failed"

# 3) Write runtime_config.json so the web build calls the deployed game server
echo "▶ Writing runtime_config.json (chat_api_base=${CHAT_API_BASE}, world_output_id=${JOB_ID})"
update_stage "writing_runtime_config"
python3 -c "
import json, os
p = '${RUNTIME_CONFIG_PATH}'
os.makedirs(os.path.dirname(p), exist_ok=True)
with open(p, 'w') as f:
    json.dump({
        'chat_api_base': os.environ.get('CHAT_API_BASE', '').strip(),
        'world_output_id': '${JOB_ID}',
    }, f, indent=2)
"

# 4) Export Godot web build
echo "▶ Exporting Godot web build..."
update_stage "exporting_web_build"
bash ./export_godot.sh "$OUTPUT_DIR" || write_error "export_godot.sh failed"

# 5) Upload output to GCS
echo "▶ Uploading to gs://${GCS_BUCKET}/output_jobs/${JOB_ID}/..."
update_stage "uploading_to_gcs"
python3 -c "
from google.cloud import storage
import os
from pathlib import Path
bucket_name = '${GCS_BUCKET}'
prefix = 'output_jobs/${JOB_ID}'
local_dir = Path('${OUTPUT_DIR}')
client = storage.Client()
bucket = client.bucket(bucket_name)
for f in local_dir.rglob('*'):
    if f.is_file():
        rel = f.relative_to(local_dir)
        blob = bucket.blob(f'{prefix}/{rel}')
        blob.upload_from_filename(str(f), content_type='application/octet-stream')
        print(f'  uploaded {rel}')
" || write_error "GCS upload failed"

# 6) Optional: deploy export/web to Firebase Hosting under /<job_id>/
if [ -n "${FIREBASE_PROJECT:-}" ] && [ -n "${FIREBASE_TOKEN:-}" ] && command -v firebase &>/dev/null; then
  echo "▶ Deploying to Firebase Hosting (${FIREBASE_PROJECT})..."
  update_stage "deploying_firebase_hosting"
  FIREBASE_TARGET_DIR="/tmp/firebase_deploy_${JOB_ID}"
  mkdir -p "$FIREBASE_TARGET_DIR/${JOB_ID}"
  cp -R "${OUTPUT_DIR}/export/web/"* "$FIREBASE_TARGET_DIR/${JOB_ID}/"
  (cd "$FIREBASE_TARGET_DIR" && firebase deploy --only hosting --token "$FIREBASE_TOKEN" --project "$FIREBASE_PROJECT") || true
  rm -rf "$FIREBASE_TARGET_DIR"
fi

# 7) Write game_url.txt so narrative server can return it on poll
GAME_URL="${FIREBASE_HOSTING_BASE_URL}/${JOB_ID}/"
if [ -z "$FIREBASE_HOSTING_BASE_URL" ]; then
  GAME_URL="https://${GOOGLE_CLOUD_PROJECT}.web.app/${JOB_ID}/"
fi
echo "$GAME_URL" > "${OUTPUT_DIR}/game_url.txt"
update_stage "completed"
python3 -c "
from google.cloud import storage
c = storage.Client()
b = c.bucket('${GCS_BUCKET}')
blob = b.blob('output_jobs/${JOB_ID}/game_url.txt')
blob.upload_from_string('${GAME_URL}', content_type='text/plain')
"
echo "▶ Done. game_url=${GAME_URL}"
