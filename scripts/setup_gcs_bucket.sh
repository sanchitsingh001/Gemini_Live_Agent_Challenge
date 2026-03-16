#!/bin/bash
# Create GCS bucket for Narrative Engine pipeline outputs and set CORS.
# Usage: GCS_BUCKET=my-bucket ./scripts/setup_gcs_bucket.sh
# Or:   ./scripts/setup_gcs_bucket.sh  (uses GOOGLE_CLOUD_PROJECT-narrative-output)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-}"
GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
GCS_BUCKET="${GCS_BUCKET:-}"

if [ -z "$GCS_BUCKET" ]; then
  if [ -z "$GOOGLE_CLOUD_PROJECT" ]; then
    echo "Error: set GCS_BUCKET or GOOGLE_CLOUD_PROJECT"
    exit 1
  fi
  GCS_BUCKET="${GOOGLE_CLOUD_PROJECT}-narrative-output"
fi

echo "Creating bucket gs://${GCS_BUCKET} (location=${GOOGLE_CLOUD_LOCATION})..."
gcloud storage buckets create "gs://${GCS_BUCKET}" \
  --project="${GOOGLE_CLOUD_PROJECT}" \
  --location="${GOOGLE_CLOUD_LOCATION}" \
  2>/dev/null || echo "Bucket may already exist."

echo "Setting CORS on gs://${GCS_BUCKET}..."
CORS_FILE="${SCRIPT_DIR}/cors_gcs.json"
cat <<'CORS' > "$CORS_FILE"
[
  {
    "origin": ["*"],
    "method": ["GET", "HEAD"],
    "responseHeader": ["Content-Type"],
    "maxAgeSeconds": 3600
  }
]
CORS
gcloud storage buckets update "gs://${GCS_BUCKET}" --cors-file="$CORS_FILE"
rm -f "$CORS_FILE"
echo "Done. Use GCS_BUCKET=${GCS_BUCKET} for game server and pipeline."
echo "Layout: gs://${GCS_BUCKET}/output_jobs/<job_id>/"
