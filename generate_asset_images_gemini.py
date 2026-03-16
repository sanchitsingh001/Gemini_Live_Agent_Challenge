#!/usr/bin/env python3
"""Batch PNGs from 3d_asset_prompts.json via Vertex Imagen."""

import argparse
import json
import re
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", required=True, help="3d_asset_prompts.json")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    prompts = json.loads(Path(args.prompts).read_text())
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    import gemini_client as gc

    manifest = {}
    for eid, prompt in prompts.items():
        safe = re.sub(r"[^\w\-]", "_", str(eid))
        path = out / f"{safe}.png"
        try:
            raw = gc.generate_image_bytes(str(prompt), aspect_ratio="1:1")
            path.write_bytes(raw)
            manifest[eid] = str(path)
            print(eid, "->", path)
        except Exception as e:
            print(eid, "ERR", e, file=sys.stderr)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
