#!/usr/bin/env python3
"""
run_pipeline.py — local narrative → JSON → optional Godot export.

Writes under output_jobs/<output_id>/ (game_bundle.json, exports, zips).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("narrator")


def sanitize_title(title: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]", "_", title.strip())
    return s[:64] if s else "unnamed"


def resolve_unique_output_id(project_root: Path, base_title: str) -> str:
    base = sanitize_title(base_title) or "unnamed"
    jobs_root = project_root / "output_jobs"
    if not (jobs_root / base).exists():
        return base
    return f"{base}_{str(uuid.uuid4())[:8]}"


def _is_rate_limit_error(stderr: str) -> bool:
    if not stderr:
        return False
    s = stderr.lower()
    return "429" in s or "rate limit" in s or "rate_limit" in s


def _parse_retry_after_seconds(stderr: str) -> int:
    m = re.search(r"try again in (\d+(?:\.\d+)?)\s*s", stderr, re.I)
    if m:
        return max(10, min(120, int(float(m.group(1)))))
    return 60


def _run_with_rate_limit_retry(
    run_fn: Callable[[], subprocess.CompletedProcess],
    step_name: str,
    max_retries: int = 5,
) -> subprocess.CompletedProcess:
    last_err: Optional[subprocess.CalledProcessError] = None
    for attempt in range(max_retries + 1):
        try:
            return run_fn()
        except subprocess.CalledProcessError as e:
            last_err = e
            stderr = (e.stderr or "") + str(e)
            if _is_rate_limit_error(stderr) and attempt < max_retries:
                wait = _parse_retry_after_seconds(stderr)
                logger.warning(
                    "%s rate limited, retry in %ds (%d/%d)",
                    step_name,
                    wait,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(wait)
                continue
            err_text = (e.stderr or "").strip() or (e.stdout or "").strip()
            raise RuntimeError(
                f"{step_name} failed: {err_text[-2000:] if err_text else str(e)}"
            ) from e
    raise RuntimeError(f"{step_name} failed after {max_retries + 1} attempts") from last_err


def _zip_dir(dir_path: Path, zip_path: Path) -> None:
    dir_path, zip_path = Path(dir_path), Path(zip_path)
    if not dir_path.exists():
        raise RuntimeError(f"Cannot zip missing directory: {dir_path}")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    base = str(zip_path.with_suffix(""))
    created = shutil.make_archive(
        base_name=base,
        format="zip",
        root_dir=str(dir_path.parent),
        base_dir=dir_path.name,
    )
    if Path(created).resolve() != zip_path.resolve():
        shutil.move(created, zip_path)


def run_pipeline(story: str, project_root: Path) -> tuple[str, str]:
    """
    Returns (output_id, absolute path to output_jobs/<output_id>).
    """
    project_root = Path(project_root).resolve()
    (project_root / "output_jobs").mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    venv_bin = str(project_root / "venv" / "bin")
    env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")

    python_exe = str(project_root / "venv" / "bin" / "python3")
    if not os.path.isfile(python_exe):
        raise RuntimeError(
            f"venv not found at {python_exe}. Create venv under project root."
        )

    with tempfile.TemporaryDirectory(prefix="narrator_spec_") as tmp:
        tmp_path = Path(tmp)
        story_path = tmp_path / "story_input.txt"
        narrative_spec_path = tmp_path / "narrative_spec.json"
        story_path.write_text(story, encoding="utf-8")

        def _run_generate_spec():
            return subprocess.run(
                [
                    python_exe,
                    str(project_root / "generate_narrative_spec.py"),
                    "--story",
                    str(story_path),
                    "--out",
                    str(narrative_spec_path),
                ],
                cwd=str(project_root),
                env=env,
                check=True,
                capture_output=True,
                text=True,
                timeout=600,
            )

        logger.info("step 1/4: generate_narrative_spec")
        _run_with_rate_limit_retry(_run_generate_spec, "generate_narrative_spec")

        with open(narrative_spec_path, "r", encoding="utf-8") as f:
            spec = json.load(f)
        raw_title = (spec.get("ending") or {}).get("title") or "unnamed"
        output_id = resolve_unique_output_id(project_root, raw_title)
        work_dir = project_root / "output_jobs" / output_id
        work_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(narrative_spec_path, work_dir / "narrative_spec.json")
        (work_dir / "story_input.txt").write_text(story, encoding="utf-8")

    narrative_spec_path = work_dir / "narrative_spec.json"
    runtime_config = {
        "chat_api_base": os.environ.get("CHAT_API_BASE", "").strip(),
        "world_output_id": output_id,
    }
    (work_dir / "runtime_config.json").write_text(
        json.dumps(runtime_config, indent=2), encoding="utf-8"
    )

    def _run_world_pipeline():
        return subprocess.run(
            ["bash", str(project_root / "run_world_pipeline.sh")],
            cwd=str(project_root),
            env={
                **env,
                "NARRATIVE_SPEC_PATH": str(narrative_spec_path),
                "OUTPUT_DIR": str(work_dir),
            },
            check=True,
            capture_output=True,
            text=True,
            timeout=900,
        )

    logger.info("step 2/4: run_world_pipeline -> %s", work_dir)
    _run_with_rate_limit_retry(_run_world_pipeline, "run_world_pipeline")

    export_enabled = os.environ.get("EXPORT_GODOT", "1").strip() != "0"
    if export_enabled:
        export_script = project_root / "export_godot.sh"
        if not export_script.exists():
            raise RuntimeError(f"Missing {export_script}")

        def _run_export():
            return subprocess.run(
                ["bash", str(export_script), str(work_dir)],
                cwd=str(project_root),
                env={**env, "GAME_EXPORT_BASENAME": output_id},
                check=True,
                capture_output=True,
                text=True,
                timeout=1800,
            )

        logger.info("step 3/4: export_godot")
        _run_with_rate_limit_retry(_run_export, "export_godot")

        export_dir = work_dir / "export"
        web_dir = export_dir / "web"
        if web_dir.exists() and (web_dir / "index.html").exists():
            _zip_dir(web_dir, export_dir / f"{output_id}-web.zip")

    logger.info("step 4/4: done %s", work_dir)
    return output_id, str(work_dir)
