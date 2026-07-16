"""Figure out what kind of input we were given, and turn it into a ``Paper``.

Accepted inputs:
  * an arXiv ID or arxiv.org URL   -> download LaTeX source (best quality)
  * a local path to a ``.pdf``     -> parse the PDF
  * an https URL to a ``.pdf``     -> download, then parse the PDF
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.models import Paper
from app.pipeline import ingest, parse, pdf_ingest, pdf_parse, structure

log = logging.getLogger(__name__)

import re

_ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


def detect_source(raw: str) -> tuple[str, str, str]:
    """Return ``(kind, value, slug)``.

    kind is one of ``"arxiv"``, ``"pdf_path"``, ``"pdf_url"``.
    slug is a filesystem-safe identifier used for the workdir + output name.
    """
    raw = raw.strip()
    lower = raw.lower()

    # arXiv URLs (abs/ or pdf/) — prefer the LaTeX path, it renders best
    if "arxiv.org" in lower:
        m = _ARXIV_RE.search(raw)
        if m:
            return ("arxiv", m.group(1), m.group(1))

    # explicit URL
    if lower.startswith(("http://", "https://")):
        return ("pdf_url", raw, pdf_parse.slugify(Path(lower.split("?")[0]).stem or "paper"))

    # local file
    p = Path(raw).expanduser()
    if p.suffix.lower() == ".pdf" or (p.exists() and p.is_file()):
        if not p.exists():
            raise FileNotFoundError(f"PDF not found: {p}")
        return ("pdf_path", str(p), pdf_parse.slugify(p.stem))

    # bare arXiv ID
    m = _ARXIV_RE.search(raw)
    if m:
        return ("arxiv", m.group(1), m.group(1))

    raise ValueError(
        f"Could not interpret {raw!r} as an arXiv ID, a local .pdf path, or a PDF URL."
    )


async def build_paper(kind: str, value: str, slug: str, workdir: Path) -> Paper:
    """Run the right ingest + parse for the detected source and return a Paper."""
    if kind == "arxiv":
        source_dir = await ingest.fetch_arxiv_source(value, workdir)
        parsed = await asyncio.to_thread(parse.parse_source, source_dir)
        return await asyncio.to_thread(structure.build_paper, value, parsed, workdir)

    pdf_path = await pdf_ingest.fetch_pdf(kind, value, workdir)
    return await asyncio.to_thread(pdf_parse.parse_pdf, pdf_path, workdir, slug)
