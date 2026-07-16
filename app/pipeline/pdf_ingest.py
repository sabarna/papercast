"""Fetch a PDF for the pipeline — from a local path or an https URL.

Unlike the arXiv path (which downloads LaTeX source), this simply gets the PDF
file into the job workdir so ``pdf_parse`` can read it.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

import httpx

log = logging.getLogger(__name__)


async def fetch_pdf(kind: str, value: str, workdir: Path) -> Path:
    """Return a local path to the PDF for this job.

    ``kind`` is ``"pdf_path"`` (``value`` is a local file) or ``"pdf_url"``
    (``value`` is an https URL). The PDF is copied/downloaded to
    ``workdir/input.pdf``.
    """
    dest = workdir / "input.pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)

    if kind == "pdf_path":
        src = Path(value).expanduser()
        if not src.exists():
            raise FileNotFoundError(f"PDF not found: {src}")
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        log.info("using local PDF %s", src)
        return dest

    if kind == "pdf_url":
        log.info("GET %s", value)
        async with httpx.AsyncClient(follow_redirects=True, timeout=90.0) as client:
            resp = await client.get(value, headers={"User-Agent": "papercast/0.1"})
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "")
            data = resp.content
            if b"%PDF" not in data[:1024] and "pdf" not in ctype.lower():
                raise ValueError(
                    f"URL did not return a PDF (content-type: {ctype!r}). "
                    "Pass a direct link to a .pdf file."
                )
            dest.write_bytes(data)
        return dest

    raise ValueError(f"unknown PDF source kind: {kind!r}")
