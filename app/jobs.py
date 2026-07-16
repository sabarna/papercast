"""In-memory job store + the async orchestrator that runs the pipeline.

For the MVP we keep jobs in a process-local dict. A production deployment
would swap this for Redis + a real task queue (RQ, Celery, Arq).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Dict

from app.cleanup import prune_intermediates
from app.config import settings
from app.models import Job, JobStatus
from app.pipeline import acquire, assemble, narrative, slides, tts

log = logging.getLogger(__name__)

# process-local job registry (a cache, not the source of truth — see _persist/get_job)
_jobs: Dict[str, Job] = {}

JOB_FILE = "job.json"


def _job_file(job_id: str) -> Path:
    # Direct path, no mkdir — used by get_job's lookup-miss path too.
    return settings.workspace_dir / job_id / JOB_FILE


def _persist(job: Job) -> None:
    """Snapshot the job to <workdir>/job.json so downloads survive a restart.

    The in-memory _jobs dict is lost whenever the process stops (Fly idle-stop,
    deploy, crash). job.json lets get_job() rehydrate from the volume.
    """
    try:
        path = _job_file(job.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(job.model_dump_json(indent=2))
    except OSError as e:
        log.warning("persist: failed to write %s: %s", job.id, e)


def create_job(arxiv_id: str) -> Job:
    job_id = uuid.uuid4().hex[:12]
    job = Job(id=job_id, arxiv_id=arxiv_id)
    _jobs[job_id] = job
    _persist(job)
    return job


def get_job(job_id: str) -> Job | None:
    job = _jobs.get(job_id)
    if job is not None:
        return job
    # Memory miss — likely a restart wiped _jobs. Rehydrate from disk.
    path = _job_file(job_id)
    if not path.exists():
        return None
    try:
        job = Job.model_validate_json(path.read_text())
    except (OSError, ValueError) as e:
        log.warning("get_job: failed to load %s from disk: %s", job_id, e)
        return None
    _jobs[job_id] = job  # warm the cache so the next call is in-memory
    return job


def _update(job: Job, status: JobStatus, progress: float, message: str = "") -> None:
    job.status = status
    job.progress = progress
    job.message = message
    log.info("job=%s status=%s progress=%.2f %s", job.id, status, progress, message)
    _persist(job)


async def run_job(job_id: str) -> None:
    """Run the full pipeline for a job. Designed to be launched with asyncio.create_task."""
    job = _jobs[job_id]
    workdir = settings.job_dir(job.id)

    try:
        kind, value, slug = acquire.detect_source(job.arxiv_id)

        _update(job, "ingesting", 0.05, "Acquiring source")
        paper = await acquire.build_paper(kind, value, slug, workdir)

        _update(job, "parsing", 0.15, "Parsed paper")

        _update(job, "scripting", 0.30, "Writing narrative")
        script = await narrative.generate_script(paper, settings.target_duration_s)
        script_path = workdir / "script.json"
        script_path.write_text(script.model_dump_json(indent=2))
        job.script_path = script_path

        _update(job, "rendering_slides", 0.50, "Rendering slides")
        slide_paths = await slides.render_slides(script, paper, workdir)

        _update(job, "tts", 0.70, "Generating voiceover")
        audio_segments = await tts.synthesize(script, workdir)

        _update(job, "assembling", 0.90, "Encoding video")
        video_path = await asyncio.to_thread(
            assemble.build_video, slide_paths, audio_segments, workdir
        )
        job.video_path = video_path

        # Free disk: keep only the final mp4 + script.json + job.json, drop intermediates.
        # job.json MUST be in the keep-list or prune deletes the metadata downloads rely on.
        try:
            await asyncio.to_thread(
                prune_intermediates,
                workdir,
                [job.video_path, job.script_path, _job_file(job.id)],
            )
        except Exception:
            log.exception("job %s: prune_intermediates failed (non-fatal)", job.id)

        _update(job, "done", 1.0, "Ready")
    except Exception as e:  # noqa: BLE001
        log.exception("job %s failed", job.id)
        job.status = "failed"
        job.error = str(e)
        job.message = f"Failed: {e}"
        _persist(job)
