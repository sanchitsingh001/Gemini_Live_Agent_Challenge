#!/usr/bin/env python3
"""
generate_asset_metadata_from_assets.py

Uses Vertex Gemini vision to infer front-facing direction (front_yaw_deg) per asset PNG.
Writes asset_metadata.json for godot_world world_loader.

Usage:
  ASSETS_RAW_DIR=/path/to/assets_raw OUT_METADATA_JSON=/path/to/asset_metadata.json python3 generate_asset_metadata_from_assets.py

Requires: gcloud auth application-default login; GOOGLE_CLOUD_PROJECT
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

YAW_TO_PANEL = {0: "A", 90: "B", 180: "C", 270: "D"}

FRONT_PROMPT = """This image shows a single 3D object as viewed from one angle.
Which cardinal direction does the FRONT of the object face in this image?
- 0 = front faces the viewer
- 90 = front faces to the right of the image
- 180 = front faces away from the viewer
- 270 = front faces to the left of the image
Reply with exactly one number: 0, 90, 180, or 270. No other text."""


def get_front_yaw_from_image(image_path: Path) -> int:
    import gemini_client as gc

    data = image_path.read_bytes()
    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    text = gc.vision_text_prompt(data, mime, FRONT_PROMPT)
    m = re.search(r"\b(0|90|180|270)\b", text)
    if m:
        return int(m.group(1))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="asset_metadata.json from PNGs via Gemini vision")
    parser.add_argument("--assets-dir", default=os.environ.get("ASSETS_RAW_DIR", ""))
    parser.add_argument("--out", default=os.environ.get("OUT_METADATA_JSON", ""))
    args = parser.parse_args()
    assets_dir = Path(args.assets_dir or "").resolve()
    out_path = Path(args.out or "").resolve()
    if not assets_dir.is_dir():
        print("assets-dir required", file=sys.stderr)
        sys.exit(1)
    if not args.out:
        print("--out required", file=sys.stderr)
        sys.exit(1)

    meta: dict = {}
    for p in sorted(assets_dir.glob("*.png")) + sorted(assets_dir.glob("*.jpg")):
        eid = p.stem
        yaw = get_front_yaw_from_image(p)
        meta[eid] = {"front_yaw_deg": yaw, "panel": YAW_TO_PANEL.get(yaw, "A")}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Wrote {out_path} ({len(meta)} assets)")


if __name__ == "__main__":
    main()
