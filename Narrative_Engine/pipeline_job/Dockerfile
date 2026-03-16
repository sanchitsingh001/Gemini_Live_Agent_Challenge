# Pipeline job: narrative spec -> world -> game_bundle -> audio -> Godot Web export.
# Build from Narrative_Engine root: docker build -f pipeline_job/Dockerfile .
# Use Godot headless image as base and install Python (keeps Godot + templates in place).
FROM robpc/godot-headless:4.3-web

# Install Python runtime plus libfontconfig for Godot headless Web export.
# Also install Node.js/npm and the Firebase CLI so the job can optionally
# deploy each job's web build directly to Firebase Hosting when configured.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv ca-certificates bash libfontconfig1 \
    nodejs npm \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf python3 /usr/bin/python \
    && npm install -g firebase-tools

WORKDIR /workspace

# Copy full Narrative_Engine (see .dockerignore); pipeline and Godot project
COPY . /workspace/

# Python deps: root + game_server (for gemini_client) + GCS for upload
RUN pip3 install --break-system-packages --no-cache-dir -r requirements.txt \
    -r game_server/requirements.txt \
    google-cloud-storage

RUN chmod +x /workspace/run_world_pipeline.sh /workspace/export_godot.sh /workspace/pipeline_job/run_job.sh

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["/workspace/pipeline_job/run_job.sh"]
