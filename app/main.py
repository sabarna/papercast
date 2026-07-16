"""FastAPI entry point.

Routes:
    GET  /                     upload form
    POST /jobs                 create a new job from an arXiv ID
    GET  /jobs/{id}            job detail page
    GET  /jobs/{id}/status     HTMX partial, polled every 2s
    GET  /jobs/{id}/video      stream the final mp4
    GET  /jobs/{id}/script     download the generated script JSON
"""
from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import jobs
from app.pipeline import acquire
from app.auth import require_auth
from app.cleanup import cleanup_workspace
from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    deleted = cleanup_workspace(settings.workspace_dir)
    if deleted:
        log.info("startup cleanup: removed %d job dir(s)", deleted)
    yield


app = FastAPI(title="PaperCast", dependencies=[Depends(require_auth)], lifespan=lifespan)

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def _resolve_web_input(raw: str) -> str:
    """Validate a submitted input for the web UI.

    Accepts an arXiv ID/URL or a PDF URL. Local file paths are rejected here —
    the server must not read arbitrary files off disk from a web request.
    """
    raw = raw.strip()
    try:
        kind, _value, _slug = acquire.detect_source(raw)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    if kind == "pdf_path":
        raise HTTPException(
            status_code=400,
            detail="Local file paths aren't allowed here. Use an arXiv ID or a PDF URL "
                   "(the command-line tool can take local PDFs).",
        )
    return raw


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/jobs")
async def create_job(arxiv_input: str = Form(...)):
    source = _resolve_web_input(arxiv_input)
    job = jobs.create_job(source)
    asyncio.create_task(jobs.run_job(job.id))
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(job_id: str, request: Request):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "job.html", {"job": job})


@app.get("/jobs/{job_id}/status", response_class=HTMLResponse)
async def job_status(job_id: str, request: Request):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "_status.html", {"job": job})


@app.get("/jobs/{job_id}/video")
async def job_video(job_id: str):
    job = jobs.get_job(job_id)
    if not job or not job.video_path or not job.video_path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(job.video_path, media_type="video/mp4", filename=f"{job.arxiv_id}.mp4")


@app.get("/jobs/{job_id}/script")
async def job_script(job_id: str):
    job = jobs.get_job(job_id)
    if not job or not job.script_path or not job.script_path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(job.script_path, media_type="application/json")
