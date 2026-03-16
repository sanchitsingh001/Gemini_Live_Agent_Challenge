#!/bin/bash
# Export Godot game as Web (HTML5/WASM) only.
#
# Usage:
#   ./export_godot.sh OUTPUT_DIR
#
# Prerequisites:
#   - Godot 4.x editor in PATH (godot or godot4)
#   - Web export templates (Editor → Manage Export Templates → Web)
#   - game_bundle.json and sky.png in OUTPUT_DIR (from run_world_pipeline)

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

OUTPUT_DIR="${1:?Usage: ./export_godot.sh OUTPUT_DIR}"
if [ ! -d "$OUTPUT_DIR" ]; then
  echo "Error: output directory not found: $OUTPUT_DIR"
  exit 1
fi
# Resolve to absolute path so Godot (--path godot_world) does not interpret export path relative to project
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
if [ ! -f "$OUTPUT_DIR/game_bundle.json" ]; then
  echo "Error: game_bundle.json not found in $OUTPUT_DIR. Run run_world_pipeline.sh first."
  exit 1
fi

# -----------------------------------------------------------------------------
# Debug instrumentation (writes NDJSON to .cursor/debug-44f8f9.log)
# -----------------------------------------------------------------------------
DEBUG_LOG_PATH="/Users/sanchitsingh/Desktop/Cursor_Projects/Gemini_Narrative/.cursor/debug-44f8f9.log"
DEBUG_SESSION_ID="44f8f9"
debug_log() {
  # Usage: debug_log hypothesisId location message jsonData
  # jsonData must be a JSON object literal (e.g. {"k":1})
  local hypothesisId="${1:-}"
  local location="${2:-}"
  local message="${3:-}"
  local dataJson="${4:-{}}"
  python3 - "$DEBUG_SESSION_ID" "$hypothesisId" "$location" "$message" "$dataJson" >>"$DEBUG_LOG_PATH" 2>/dev/null <<'PY' || true
import json, sys, time
session_id, hypothesis_id, location, message, data_json = sys.argv[1:6]
try:
    data = json.loads(data_json) if data_json else {}
except Exception:
    data = {"_log_json_parse_error": True, "raw": data_json}
payload = {
    "sessionId": session_id,
    "runId": session_id,
    "hypothesisId": hypothesis_id,
    "location": location,
    "message": message,
    "data": data,
    "timestamp": int(time.time() * 1000),
}
print(json.dumps(payload, ensure_ascii=False))
PY
}

# Basic sanity: log invocation + output dir.
debug_log "BOOT" "export_godot.sh:debug" "export invoked" "{\"output_dir\":\"${OUTPUT_DIR}\"}"

# -----------------------------------------------------------------------------
# Prevent stale generated assets/mappings from leaking into local exports.
#
# - Asset-aware exports: ./stage_and_export_story.sh copies GLBs + writes `.asset_stage_marker`.
# - Plain pipeline exports should NOT reuse any prior staged GLBs/mappings.
# -----------------------------------------------------------------------------
GENERATED_DIR="$ROOT/godot_world/generated"
ASSET_MARKER="$GENERATED_DIR/.asset_stage_marker"
if [ -d "$GENERATED_DIR" ] && [ ! -f "$ASSET_MARKER" ]; then
  rm -f "$GENERATED_DIR/entity_models.json" "$GENERATED_DIR/npc_models.json" "$GENERATED_DIR/asset_metadata.json" 2>/dev/null || true
  rm -rf "$GENERATED_DIR/assets" 2>/dev/null || true
fi
rm -f "$ASSET_MARKER" 2>/dev/null || true

# Detect Godot binary
GODOT_CMD=""
if command -v godot &>/dev/null; then
  GODOT_CMD="godot"
elif command -v godot4 &>/dev/null; then
  GODOT_CMD="godot4"
else
  echo "Error: Godot not found. Install Godot 4.x and add 'godot' or 'godot4' to PATH."
  exit 1
fi

# Copy game_bundle, sky, all bundle PNGs, and audio to godot_world/generated/ (bundled into export)
mkdir -p godot_world/generated
cp "$OUTPUT_DIR/game_bundle.json" godot_world/generated/
echo "Copied game_bundle.json to godot_world/generated/"
if [ -f "$OUTPUT_DIR/sky.png" ]; then
  cp "$OUTPUT_DIR/sky.png" godot_world/generated/
  echo "Copied sky.png to godot_world/generated/"
fi
if [ -f "$OUTPUT_DIR/runtime_config.json" ]; then
  cp "$OUTPUT_DIR/runtime_config.json" godot_world/generated/
  echo "Copied runtime_config.json to godot_world/generated/"
fi
# Bundle images (opening, setup, chapter transitions, ending) so web export has them
PNG_TOTAL=0
PNG_VALID=0
PNG_INVALID=0
for f in "$OUTPUT_DIR"/*.png; do
  if [ -f "$f" ]; then
    PNG_TOTAL=$((PNG_TOTAL + 1))
    # Validate PNG signature (some pipeline outputs may be JPEG-with-.png-extension).
    if python3 - "$f" <<'PY'
import sys
with open(sys.argv[1], "rb") as fp:
    sig = fp.read(8)
sys.exit(0 if sig == b"\x89PNG\r\n\x1a\n" else 1)
PY
    then
      PNG_VALID=$((PNG_VALID + 1))
    else
      PNG_INVALID=$((PNG_INVALID + 1))
    fi
    cp "$f" godot_world/generated/ && echo "Copied $(basename "$f") to godot_world/generated/"
  fi
done
debug_log "H1" "export_godot.sh:png" "png copy+validation complete" "{\"png_total\":${PNG_TOTAL},\"png_valid\":${PNG_VALID},\"png_invalid\":${PNG_INVALID}}"
# Bundle audio (voiceover + BGM) so web export has them
AUD_TOTAL=0
if [ -d "$OUTPUT_DIR/audio" ]; then
  mkdir -p godot_world/generated/audio
  # Count audio files before copy for logging.
  AUD_TOTAL=$(ls -1 "$OUTPUT_DIR/audio" 2>/dev/null | wc -l | tr -d ' ')
  cp -R "$OUTPUT_DIR/audio"/* godot_world/generated/audio/
  echo "Copied audio/ to godot_world/generated/audio/"
fi
debug_log "H3" "export_godot.sh:audio" "audio copy complete" "{\"audio_files\":${AUD_TOTAL}}"

# Headless export does not re-import newly copied files; run editor once so generated/* get
# imported and packed into the .pck (otherwise web build misses images and audio).
echo "▶ Importing generated assets (editor pass so export packs them)..."
IMPORT_LOG="$(mktemp -t godot_import.XXXXXX.log)"
set +e
$GODOT_CMD --headless --path godot_world --editor --quit >"$IMPORT_LOG" 2>&1
IMPORT_CODE=$?
set -e
# Log a small tail of import output to avoid huge logs.
IMPORT_TAIL="$(tail -n 40 "$IMPORT_LOG" 2>/dev/null | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
IMPORTED_COUNT=0
if [ -d "godot_world/.godot/imported" ]; then
  IMPORTED_COUNT=$(ls -1 godot_world/.godot/imported 2>/dev/null | wc -l | tr -d ' ')
fi
debug_log "H2" "export_godot.sh:import" "godot import pass finished" "{\"exit_code\":${IMPORT_CODE},\"imported_files\":${IMPORTED_COUNT},\"tail\":${IMPORT_TAIL}}"
rm -f "$IMPORT_LOG" 2>/dev/null || true

# Create export output dir (web only)
mkdir -p "$OUTPUT_DIR/export/web"

# Export Web (HTML5 / WebAssembly) for browser deployment
WEB_OUTPUT="$OUTPUT_DIR/export/web"
WEB_INDEX="$WEB_OUTPUT/index.html"
echo "▶ Exporting Web build..."
EXPORT_LOG="$(mktemp -t godot_export.XXXXXX.log)"
set +e
$GODOT_CMD --headless --path godot_world --export-release "Web" "$WEB_INDEX" >"$EXPORT_LOG" 2>&1
EXPORT_CODE=$?
set -e
EXPORT_TAIL="$(tail -n 60 "$EXPORT_LOG" 2>/dev/null | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
debug_log "H4" "export_godot.sh:export" "godot export finished" "{\"exit_code\":${EXPORT_CODE},\"web_index_exists\":$([ -f "$WEB_INDEX" ] && echo true || echo false),\"tail\":${EXPORT_TAIL}}"
rm -f "$EXPORT_LOG" 2>/dev/null || true

# Verify whether generated assets were actually packed into the exported .pck.
PCK_PATH="$WEB_OUTPUT/index.pck"
PACKED_JSON="{}"
if [ -f "$PCK_PATH" ]; then
  PACKED_JSON="$(python3 - "$PCK_PATH" <<'PY'
import json, sys
pck = sys.argv[1]
data = open(pck, "rb").read()
needles = {
  "opening_png": b"generated/opening.png",
  "setup_png": b"generated/setup_screen.png",
  "transition_1_png": b"generated/chapter_transition_chapter_1.png",
  "ending_png": b"generated/ending_screen.png",
  "audio_dir": b"generated/audio/",
  "voiceover_setup": b"generated/audio/voiceover_setup.wav",
  "bgm_setup": b"generated/audio/bgm_setup.wav",
}
out = {k: (v in data) for k, v in needles.items()}
out["pck_size_bytes"] = len(data)
print(json.dumps(out))
PY
  )"
fi
debug_log "H5" "export_godot.sh:pack" "pck contains generated assets?" "$PACKED_JSON"
# If Godot wrote to the preset path (project root web_build/) instead, copy into export/web
if [ ! -f "$WEB_INDEX" ] && [ -d "$ROOT/web_build" ] && [ -n "$(ls -A "$ROOT/web_build" 2>/dev/null)" ]; then
  echo "  → Copying from godot_world/../web_build to export/web..."
  cp -R "$ROOT/web_build"/* "$WEB_OUTPUT/"
fi
if [ -f "$WEB_INDEX" ]; then
  echo "  → $WEB_OUTPUT/ (index.html + .pck + .wasm)"
else
  echo "  → Web export produced no files. Install Web export templates in Godot (Editor → Manage Export Templates → Web) and re-run."
  # Treat missing Web export as a hard failure so Cloud jobs surface a clear error
  exit 1
fi

# Clean stale build output
rm -rf godot_world/../web_build 2>/dev/null || true

echo ""
echo "▶ Export complete. Web build in $OUTPUT_DIR/export/web/"

# -----------------------------------------------------------------------------
# Post-process web export for Yanah-branded loader + favicon.
# This runs for every generated game so all exports share the same branding.
# -----------------------------------------------------------------------------
YANAH_LOADER_SRC="$OUTPUT_DIR/yanah_loading.png"
if [ -f "$YANAH_LOADER_SRC" ] && [ -f "$WEB_INDEX" ]; then
  echo "▶ Applying Yanah branding to web loader..."
  # Copy loader art + favicons into the web export folder.
  cp "$YANAH_LOADER_SRC" "$WEB_OUTPUT/yanah_loading.png"
  cp "$YANAH_LOADER_SRC" "$WEB_OUTPUT/yanah_favicon.png"
  # Also override Godot's default icon so any runtime swaps still show Yanah.
  cp "$YANAH_LOADER_SRC" "$WEB_OUTPUT/index.icon.png"

  python3 - "$WEB_INDEX" <<'PY' || echo "Warning: Yanah branding patch failed; leaving default Godot loader."
import io, sys, re
path = sys.argv[1]
text = open(path, encoding="utf-8").read()

# 1) Title
text = re.sub(r"<title>.*?</title>", "<title>Yanah</title>", text, count=1, flags=re.DOTALL)

# 2) Favicon links (ensure they all point at yanah_favicon.png)
def ensure_favicons(html: str) -> str:
    # Replace existing engine icon link if present.
    html = re.sub(
        r'<link id="-gd-engine-icon"[^>]*>',
        '<link id="-gd-engine-icon" rel="icon" type="image/png" href="yanah_favicon.png" />',
        html,
        count=1,
    )
    # Ensure shortcut + apple-touch icons exist (append inside <head> if missing).
    head_close = html.find("</head>")
    if head_close != -1:
        inject = '\n\t\t<link rel="shortcut icon" type="image/png" href="yanah_favicon.png" />\n\t\t<link rel="apple-touch-icon" href="yanah_favicon.png"/>'
        if "shortcut icon" not in html:
            html = html[:head_close] + inject + html[head_close:]
    return html

text = ensure_favicons(text)

# 3) Loader CSS: make Yanah art a full-screen background and keep the progress bar/text.
text = re.sub(
    r"#status\s*\{[^}]*\}",
    "#status {\n\tbackground-color: black;\n\tbackground-image: url('yanah_loading.png');\n\tbackground-position: center center;\n\tbackground-repeat: no-repeat;\n\tbackground-size: contain;\n\tdisplay: flex;\n\tflex-direction: column;\n\tjustify-content: center;\n\talign-items: center;\n\tvisibility: hidden;\n}",
    text,
    count=1,
    flags=re.DOTALL,
)

text = re.sub(
    r"#status-splash\s*\{[^}]*\}",
    "#status-splash {\n\tdisplay: none;\n}",
    text,
    count=1,
    flags=re.DOTALL,
)

# Some Godot templates include a combined selector like `#status, #status-splash { display: none; }`.
# Our loader uses #status for the background + progress bar, so force it visible.
# Also style the progress bar so it doesn't fall back to browser-default blue.
YANAH_CSS = r"""

/* --- Yanah loader overrides (post-export patch) --- */
body {
	background-color: #020202;
}
#status {
	position: fixed !important;
	inset: 0 !important;
	display: flex !important;
	flex-direction: column;
	justify-content: center;
	align-items: center;
	visibility: hidden; /* JS switches this to visible during load */
}
#status-splash {
	display: block !important;
	position: absolute !important;
	inset: 0 !important;
	width: 100% !important;
	height: 100% !important;
	object-fit: contain !important;
	z-index: 0;
}
#status-progress, #status-notice {
	position: relative;
	z-index: 1;
}
#status-progress {
	position: absolute;
	left: 10%;
	right: 10%;
	bottom: 14%;
	display: block;
	height: 8px;
	border-radius: 999px;
	overflow: hidden;
	background: rgba(255, 255, 255, 0.18);
	border: 1px solid rgba(255, 255, 255, 0.22);
}
#status-progress::-webkit-progress-bar {
	background: rgba(255, 255, 255, 0.18);
	border-radius: 999px;
}
#status-progress::-webkit-progress-value {
	background: linear-gradient(90deg, #e6c07a, #f2e6c9);
	border-radius: 999px;
}
#status-progress::-moz-progress-bar {
	background: linear-gradient(90deg, #e6c07a, #f2e6c9);
	border-radius: 999px;
}
"""

if "</style>" in text and "Yanah loader overrides" not in text:
    text = text.replace("</style>", YANAH_CSS + "\n\t\t</style>", 1)

# Add status text style if not already present.
if "#status-text" not in text:
    insert_after = re.search(r"#status-progress[^{]*\{[^}]*\}", text, flags=re.DOTALL)
    if insert_after:
        start, end = insert_after.span()
        snippet = text[start:end]
        replacement = snippet + "\n\n#status-text {\n\tposition: absolute;\n\tleft: 0;\n\tright: 0;\n\tbottom: 18%;\n\ttext-align: center;\n\tfont-family: 'Noto Sans', 'Droid Sans', Arial, sans-serif;\n\tfont-size: 1rem;\n\tcolor: #e0e0e0;\n}"
        text = text[:start] + replacement + text[end:]

# 4) Loader HTML content.
text = re.sub(
    r'<div id="status">[\s\S]*?<div id="status-notice"></div>\s*</div>',
    '<div id="status">\n\t\t\t<img id="status-splash" class="show-image--true fullsize--true use-filter--true" src="yanah_loading.png" alt="Yanah loading">\n\t\t\t<div id="status-text">Loading Yanah...</div>\n\t\t\t<progress id="status-progress"></progress>\n\t\t\t<div id="status-notice"></div>\n\t\t</div>',
    text,
    count=1,
)

# 5) Runtime favicon guard: some templates re-point icons to the engine icon at runtime.
# Inject a tiny script after index.js that continuously forces Yanah favicon.
FAVICON_GUARD = r'''
<script>
(function() {
  function applyYanahFavicon() {
    var links = document.querySelectorAll('link[rel~="icon"], link#-gd-engine-icon');
    for (var i = 0; i < links.length; i++) {
      links[i].href = 'yanah_favicon.png';
      links[i].type = 'image/png';
      links[i].rel = 'icon';
    }
  }
  // Initial and a few follow-ups in case engine JS tweaks icons later.
  document.addEventListener('DOMContentLoaded', applyYanahFavicon);
  window.addEventListener('load', function() {
    applyYanahFavicon();
    var n = 0;
    var id = setInterval(function() {
      applyYanahFavicon();
      if (++n > 5) clearInterval(id);
    }, 1000);
  });
})();
</script>
'''

if '<script src="index.js"></script>' in text and 'Runtime favicon guard' not in text:
    text = text.replace('<script src="index.js"></script>', '<script src="index.js"></script>' + FAVICON_GUARD, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)
PY
fi

# Optional: disable with CLEAN_GODOT_CACHE=0 to keep the editor cache
if [ "${CLEAN_GODOT_CACHE:-1}" != "0" ]; then
  rm -rf godot_world/.godot || true
  echo "Cleaned Godot cache: godot_world/.godot"
fi
