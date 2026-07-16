"""Step 1 — fetch the paper's source from arXiv.

arXiv exposes the original LaTeX source at:

    https://arxiv.org/e-print/<id>

This is almost always a gzipped tarball (occasionally a single .tex.gz file,
very rarely a PDF-only submission). We unpack it into <workdir>/source/.
"""
from __future__ import annotations

import gzip
import io
import logging
import tarfile
from pathlib import Path

import httpx

log = logging.getLogger(__name__)


ARXIV_EPRINT_URL = "https://arxiv.org/e-print/{arxiv_id}"
ARXIV_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}.pdf"


async def fetch_arxiv_source(arxiv_id: str, workdir: Path) -> Path:
    """Download and unpack the arXiv source into ``workdir/source/``.

    Returns the path to the unpacked source directory.
    Raises if the submission is PDF-only (no LaTeX source available).
    """
    source_dir = workdir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    url = ARXIV_EPRINT_URL.format(arxiv_id=arxiv_id)
    log.info("GET %s", url)

    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
        resp = await client.get(url, headers={"User-Agent": "readel/0.1"})
        resp.raise_for_status()
        data = resp.content

    _unpack(data, source_dir)

    # also grab the PDF so we have it as a visual fallback
    pdf_path = workdir / "paper.pdf"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            pdf_resp = await client.get(
                ARXIV_PDF_URL.format(arxiv_id=arxiv_id),
                headers={"User-Agent": "readel/0.1"},
            )
            if pdf_resp.status_code == 200:
                pdf_path.write_bytes(pdf_resp.content)
    except Exception as e:  # noqa: BLE001
        log.warning("couldn't fetch PDF (non-fatal): %s", e)

    return source_dir


def _unpack(data: bytes, dest: Path) -> None:
    """Unpack arXiv's e-print blob into ``dest``.

    Handles: gzipped tarball, plain tarball, single gzipped .tex, raw .tex.
    """
    # Try tarball (possibly gzipped)
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
            tf.extractall(dest, filter="data")
        log.info("unpacked tarball into %s", dest)
        return
    except tarfile.ReadError:
        pass

    # Try gzipped single file
    try:
        raw = gzip.decompress(data)
        (dest / "main.tex").write_bytes(raw)
        log.info("unpacked single gzipped file as main.tex")
        return
    except OSError:
        pass

    # Assume raw .tex or .pdf blob
    # Peek at header to pick a filename
    if data[:4] == b"%PDF":
        # PDF-only submission — no LaTeX source. Caller should fall back.
        (dest / "paper.pdf").write_bytes(data)
        raise PdfOnlySubmission("arXiv returned a PDF; no LaTeX source available")

    (dest / "main.tex").write_bytes(data)
    log.info("unpacked raw bytes as main.tex")


class PdfOnlySubmission(RuntimeError):
    """Raised when arXiv has only a PDF for this submission (no source)."""
