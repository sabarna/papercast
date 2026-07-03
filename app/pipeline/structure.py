"""Step 3 — lift the raw ParsedSource into a typed Paper model.

This is where we:
  - Assign stable IDs (fig1, fig2, eq1, eq2, ...) usable by Claude.
  - Convert LaTeX figure paths to web-safe PNGs (pdf/eps -> png) and copy
    them to ``<workdir>/figures/``.
  - Strip LaTeX from section body text for the narrative prompt.
  - Cross-reference section -> figures/equations by ID.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from app.models import Equation, Figure, Paper, Section
from app.pipeline.parse import ParsedSource, RawFigure

log = logging.getLogger(__name__)


def build_paper(arxiv_id: str, ps: ParsedSource, workdir: Path) -> Paper:
    figures_dir = workdir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    fig_by_idx: dict[int, str] = {}
    figures: dict[str, Figure] = {}
    for idx, raw in enumerate(ps.figures, start=1):
        fig_id = f"fig{idx}"
        dest = _prepare_figure(raw, figures_dir, fig_id)
        if dest is None:
            continue
        figures[fig_id] = Figure(
            id=fig_id, path=dest, caption=raw.caption, label=raw.label
        )
        fig_by_idx[idx - 1] = fig_id

    eq_by_idx: dict[int, str] = {}
    equations: dict[str, Equation] = {}
    for idx, raw in enumerate(ps.equations, start=1):
        eq_id = f"eq{idx}"
        equations[eq_id] = Equation(id=eq_id, latex=raw.latex)
        eq_by_idx[idx - 1] = eq_id

    sections: list[Section] = []
    for raw_sec in ps.sections:
        from app.pipeline.parse import _tex_to_text  # reuse

        sections.append(
            Section(
                title=raw_sec.title,
                level=raw_sec.level,
                text=_tex_to_text(raw_sec.body).strip(),
                figure_ids=[fig_by_idx[i] for i in raw_sec.figures if i in fig_by_idx],
                equation_ids=[eq_by_idx[i] for i in raw_sec.equations if i in eq_by_idx],
            )
        )

    return Paper(
        arxiv_id=arxiv_id,
        title=ps.title or arxiv_id,
        authors=ps.authors,
        abstract=ps.abstract,
        sections=sections,
        figures=figures,
        equations=equations,
    )


def _prepare_figure(raw: RawFigure, dest_dir: Path, fig_id: str) -> Path | None:
    """Copy the figure into dest_dir, converting PDF/EPS to PNG if needed.

    Returns the destination path, or None if the figure can't be prepared.
    """
    src = raw.path
    if not src.exists():
        return None

    ext = src.suffix.lower()
    if ext in {".png", ".jpg", ".jpeg"}:
        dest = dest_dir / f"{fig_id}{ext}"
        shutil.copy2(src, dest)
        return dest

    if ext == ".pdf":
        dest = dest_dir / f"{fig_id}.png"
        try:
            subprocess.run(
                ["pdftoppm", "-png", "-r", "200", "-singlefile", str(src), str(dest.with_suffix(""))],
                check=True,
                capture_output=True,
            )
            return dest
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            log.warning("pdftoppm failed for %s: %s", src, e)
            return None

    if ext == ".eps":
        dest = dest_dir / f"{fig_id}.png"
        try:
            subprocess.run(
                ["convert", "-density", "200", str(src), str(dest)],
                check=True,
                capture_output=True,
            )
            return dest
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            log.warning("ImageMagick convert failed for %s: %s", src, e)
            return None

    # Unknown type — just copy
    dest = dest_dir / f"{fig_id}{ext}"
    shutil.copy2(src, dest)
    return dest
