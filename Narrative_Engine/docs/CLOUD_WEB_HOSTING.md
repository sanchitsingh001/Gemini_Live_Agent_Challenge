# Where the Web Build Runs and How to Host It on GCP (S3 + CloudFront Style)

Two questions: **where** is the compiled web version produced, and **how** do you host it on GCP in a way similar to S3 + CloudFront?

---

## 1. Where the web build is produced

The **compiled web version** (HTML + JS + WASM + .pck) is produced by **Godot** during the export step of your pipeline:

- **Script:** `export_godot.sh` (or `stage_and_export_story.sh` → `export_godot.sh`).
- **What it does:** Copies `game_bundle.json`, sky, images, audio into `godot_world/generated/`, then runs Godot headless with the **Web** export preset. Godot writes the web build to:
  - `OUTPUT_DIR/export/web/`  
  e.g. `index.html`, `index.js`, `index.pck`, `index.wasm`, worklet scripts, etc.

So **where that code runs** in the cloud design:

- **Single-phase pipeline:** The **Cloud Run Job** that runs the full pipeline (narrative → world → game_bundle → export) runs on GCP. Inside that job you run `run_world_pipeline.sh` with export, or `run_pipeline()` then export. The job’s workspace has `work_dir/export/web/`. After the job finishes, you **upload** that directory to GCS (or deploy it to a host). So: **the code that compiles the web version runs inside the same Cloud Run Job** that does the rest of the pipeline; the **output** is then uploaded for hosting.

- **Two-phase pipeline (with external assets):** The **Phase 2 Cloud Run Job** runs `stage_and_export_story.sh` (or equivalent) after copying external assets (GLBs) into the workspace. That script runs `export_godot.sh`, which produces `work_dir/export/web/`. Again, the web build is produced **inside the Phase 2 job**; then you upload `work_dir/export/web/` to GCS or deploy it.

**Summary:** The compiled web version is always produced **inside the GCP Cloud Run Job** (the one that runs Godot export). You then take the contents of `export/web/` and host them somewhere (GCS, Firebase, etc.).

---

## 2. Hosting on GCP

On GCP you have two main options that give you a CDN-backed static host: **Firebase Hosting** or **GCS + Cloud CDN + HTTP(S) Load Balancer**.

### Option A: Firebase Hosting (simplest, recommended)

**Conceptually:** One “static site” with a global CDN and HTTPS. You deploy a directory of files; Firebase serves it. Very similar to “S3 bucket + CloudFront” in terms of outcome.

- **Storage:** You don’t put files in GCS first for Hosting; you deploy from a local directory or from a build step (e.g. in Cloud Build or in your job after upload to GCS, then download and deploy).
- **CDN + HTTPS:** Firebase Hosting gives you a global CDN and automatic HTTPS. You get a default URL like `https://<project-id>.web.app` and can add custom domains.

**How to use it for multiple games:**

- **Single site, path per game:**  
  Deploy a structure like:
  - `public/` (or your deploy root)
    - `<job_id_1>/`   ← contents of `export/web/` for game 1 (index.html, index.js, …)
    - `<job_id_2>/`   ← contents of `export/web/` for game 2
    - …
  Then the “game link” for a job is:  
  `https://<project-id>.web.app/<job_id>/`  
  (or `https://<project-id>.web.app/<job_id>/index.html`)

- **Deploy from pipeline:**  
  After the Cloud Run Job produces `work_dir/export/web/`:
  1. Upload that directory to GCS, e.g. `gs://<bucket>/output_jobs/<job_id>/web/`.
  2. A small **deploy step** (Cloud Function, Cloud Run, or Cloud Build) either:
     - Uses the **Firebase Admin SDK** or **Firebase Hosting API** to upload the contents of `gs://.../output_jobs/<job_id>/web/` to Hosting under the path `/<job_id>/`, or
     - Clones the live Hosting content (e.g. from GCS), merges in the new `/<job_id>/` directory, and deploys the whole site.

  Alternatively, you can use **Firebase Hosting channels** or a single **Hosting site** and update only the path for that job (e.g. with a script that syncs GCS → a local dir and runs `firebase deploy` for the appropriate paths).

**Result:** Each game is at a stable URL like `https://your-project.web.app/<job_id>/`. Same idea as “one S3 bucket, key prefix per game, CloudFront in front.”

---

### Option B: GCS bucket + Cloud CDN + Load Balancer (closest to S3 + CloudFront)

**Conceptually:** GCS = S3, HTTP(S) Load Balancer + Cloud CDN = CloudFront.

- **Storage:** Upload the web export to a **GCS bucket**, e.g.  
  `gs://<bucket>/output_jobs/<job_id>/web/index.html`,  
  `gs://<bucket>/output_jobs/<job_id>/web/index.js`,  
  etc.  
  (Same bucket you use for pipeline outputs.)
- **Serving:** Create an **HTTP(S) Load Balancer** with a **backend bucket** pointing at that GCS bucket. Enable **Cloud CDN** on the backend. Map a URL (e.g. `https://games.yourdomain.com`) to that load balancer.
- **URL shape:** You can either:
  - Use **bucket object naming** so that the path in the URL is the path in the bucket:  
    `https://games.yourdomain.com/output_jobs/<job_id>/web/index.html`  
    and set a **custom error document** (e.g. `/output_jobs/<job_id>/web/index.html`) for “directory” requests, or
  - Use a **URL map** / rewrite so that `https://games.yourdomain.com/g/<job_id>/` is rewritten to the object at `gs://bucket/output_jobs/<job_id>/web/index.html`.

**CORS:** For web games that call your chat API from the browser, the static host must send CORS headers. GCS can be configured with CORS on the bucket; Firebase Hosting can be configured to add headers. Your **game server** (Cloud Run) already needs CORS for `/api/dialogue_turn` and `/api/chat`; the static host just needs to allow the game’s origin (or `*` for a demo).

**Result:** Static files live in GCS; users hit a CDN URL. Architecturally this is the direct GCP analogue of S3 + CloudFront.

---

## 3. Chat API and runtime config

The web game is **static** (HTML/JS/WASM) but it **calls your game server** for NPC dialogue:

- **Endpoints:** `/api/game-data`, `/api/dialogue_turn`, `/api/chat`.
- **Base URL:** The client gets it from **runtime_config.json**, which is bundled into the export (`chat_api_base`, `world_output_id`). So when you build the game in the pipeline, you set `CHAT_API_BASE` (or the value that ends up in `runtime_config.json`) to your **deployed game server URL**, e.g. `https://game-server-xxxx.run.app`. The same game server can serve many games; each request sends `output: <job_id>`.

So for hosting you have two pieces:

1. **Static hosting (GCP):** Where the compiled web build lives — **Firebase Hosting** or **GCS + Cloud CDN + Load Balancer** as above. That gives you the “play” link (e.g. `https://your-project.web.app/<job_id>/`).
2. **Game server (GCP):** Your existing **game_server** (FastAPI) deployed on **Cloud Run**. It serves `/api/game-data`, `/api/dialogue_turn`, `/api/chat` and loads `game_bundle` from GCS (or from the path implied by `output=<job_id>`). One service for all games.

The “deployed web link” you return to the user is the **static host URL** for that job (e.g. `https://your-project.web.app/<job_id>/`). When they open it, the page loads from Firebase or GCS+CDN, and the JavaScript calls your Cloud Run game server for chat; `world_output_id` in the bundled config is the same `<job_id>` so the server knows which game’s bundle to use.

---

## 4. Summary

| Question | Answer |
|----------|--------|
| **Where is the code that compiles the web version run?** | Inside the **Cloud Run Job** that runs the pipeline (or Phase 2). That job runs `export_godot.sh`, which writes `OUTPUT_DIR/export/web/`. So the “compile” happens on GCP in that job. |
| **Where do we host the compiled web game?** | On GCP you have two S3+CloudFront–style options: **(A) Firebase Hosting** (easiest: one site, path per game, e.g. `/<job_id>/`) or **(B) GCS + Cloud CDN + HTTP(S) Load Balancer** (bucket = S3, CDN = CloudFront). |
| **How do we get the files there?** | After the job finishes, upload `export/web/` to GCS (e.g. `gs://bucket/output_jobs/<job_id>/web/`). Then either deploy that path to Firebase Hosting (script or Cloud Build), or the bucket is already the backend for the load balancer + CDN. |
| **What about the chat API?** | Hosted separately as a **Cloud Run service** (game_server). The static web game is configured (via bundled `runtime_config.json`) to call that service; one API serves all games via the `output` parameter. |

So yes: you can host the compiled web version on GCP using **Firebase Hosting** (simplest) or **GCS + Cloud CDN + Load Balancer**.
