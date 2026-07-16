"""Parse an arbitrary PDF into a ``Paper`` — text, sections, figures, equations.

There's no LaTeX source to work from, so:
  * text + layout come from ``pdfplumber``
  * pages are rasterized with ``pypdfium2`` so we can crop out figure images
  * equations are detected heuristically (centered, math-heavy lines) and
    cropped to images too — for PDFs, equations become picture slides rather
    than typeset KaTeX.

All visuals (real figures and equation crops) are returned as ``Figure`` objects,
so the rest of the pipeline treats them uniformly. ``equations`` stays empty.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium

from app.models import Figure, Paper, Section

log = logging.getLogger(__name__)

_RENDER_DPI = 150
_SCALE = _RENDER_DPI / 72.0

# section headings: "1 Introduction", "3.2 Method", or known names
_NUM_HEADING = re.compile(r"^\s*(\d+(?:\.\d+){0,2})\.?\s+([A-Z][A-Za-z0-9 ,\-:]{2,60})\s*$")
_NAMED_HEADING = re.compile(
    r"^\s*(abstract|introduction|background|related work|preliminaries|method(?:s|ology)?|"
    r"approach|model|experiments?|evaluation|results?|analysis|discussion|"
    r"conclusions?|limitations?|future work|acknowledg(?:e)?ments?|references|"
    r"appendix)\s*$",
    re.IGNORECASE,
)

# characters that suggest a line is a display equation
_MATH_CHARS = re.compile(
    r"[=≤≥≈≠<>∑∏∫∈∉∀∃±∓×÷·→←⇒⇐⇔√∇∂∞≜≡⊕⊗∥⟨⟩αβγδεζηθικλμνξπρστφχψω"
    r"ΓΔΘΛΞΠΣΦΨΩ]|\\?_\{|\\?\^\{|\^|_"
)


def slugify(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "").strip()).strip("-._")
    return s[:60] or "document"


def _render_pages(pdf_path: Path):
    """Rasterize each page once with pypdfium2; return list of PIL images."""
    doc = pdfium.PdfDocument(str(pdf_path))
    images = []
    try:
        for i in range(len(doc)):
            page = doc[i]
            bitmap = page.render(scale=_SCALE)
            images.append(bitmap.to_pil())
            page.close()
    finally:
        doc.close()
    return images


def _crop(page_img, plumber_page, bbox, pad: float = 2.0):
    """Crop a pdfplumber bbox (points, top-left origin) from the rendered page."""
    x0, top, x1, bottom = bbox
    sx = page_img.width / float(plumber_page.width)
    sy = page_img.height / float(plumber_page.height)
    box = (
        max(0, int((x0 - pad) * sx)),
        max(0, int((top - pad) * sy)),
        min(page_img.width, int((x1 + pad) * sx)),
        min(page_img.height, int((bottom + pad) * sy)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return page_img.crop(box)


def _lines_from_words(words):
    """Group pdfplumber words into visual lines by their 'top' coordinate."""
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(w["top"] - lines[-1][0]["top"]) <= 3:
            lines[-1].append(w)
        else:
            lines.append([w])
    return lines


_CAPTION_RE = re.compile(r"^(figure|fig\.?|table)\s*\d+", re.IGNORECASE)


def _find_figure_caption(lines, bbox) -> str | None:
    """Find a 'Figure N: ...' caption line near an image (usually just below it)."""
    _x0, _top, _x1, bottom = bbox
    best, best_score = None, 1e9
    for line in lines:
        text = " ".join(w["text"] for w in line).strip()
        if not _CAPTION_RE.match(text):
            continue
        ltop = min(w["top"] for w in line)
        gap = ltop - bottom            # positive = below the image (preferred)
        score = gap if gap >= -12 else 1e6
        if score < best_score:
            best_score, best = score, text
    if best and best_score < 160:
        return best[:220]
    return None


def _extract_sections(pages_text: list[str]) -> tuple[str, list[Section]]:
    """Split the concatenated text into sections at detected headings."""
    abstract = ""
    sections: list[Section] = []
    current_title, current_level, buf = "Overview", 1, []

    def flush():
        text = "\n".join(buf).strip()
        if text or current_title:
            sections.append(Section(title=current_title, level=current_level, text=text))

    for page in pages_text:
        for raw in page.splitlines():
            line = raw.strip()
            if not line:
                continue
            m = _NUM_HEADING.match(line)
            named = _NAMED_HEADING.match(line)
            if m or named:
                flush()
                buf = []
                if m:
                    current_title = m.group(2).strip()
                    current_level = m.group(1).count(".") + 1
                else:
                    current_title = named.group(1).title()
                    current_level = 1
                continue
            buf.append(line)
            if current_title.lower() == "abstract" and len(abstract) < 1200:
                abstract = (abstract + " " + line).strip()
    flush()

    # drop the reference list body (saves narrative tokens)
    sections = [s for s in sections if s.title.lower() not in {"references", "bibliography"}]
    return abstract, sections


def parse_pdf(pdf_path: Path, workdir: Path, slug: str) -> Paper:
    figures_dir = workdir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    page_images = _render_pages(pdf_path)
    figures: dict[str, Figure] = {}
    pages_text: list[str] = []
    fig_n = 0
    eq_n = 0
    title = slug

    with pdfplumber.open(str(pdf_path)) as pdf:
        meta_title = (pdf.metadata or {}).get("Title") or ""
        junk_titles = {"untitled", "untitled document", "microsoft word", "paper"}
        if meta_title.strip() and meta_title.strip().lower() not in junk_titles and len(meta_title.strip()) > 3:
            title = meta_title.strip()
        elif pdf.pages:
            # fall back to the first substantial line of page 1 (usually the title)
            for ln in (pdf.pages[0].extract_text() or "").splitlines():
                if len(ln.strip()) > 8:
                    title = ln.strip()
                    break

        for pageno, page in enumerate(pdf.pages):
            pages_text.append(page.extract_text() or "")
            pimg = page_images[pageno] if pageno < len(page_images) else None
            if pimg is None:
                continue

            try:
                words = page.extract_words(use_text_flow=False)
            except Exception:  # noqa: BLE001
                words = []
            lines = _lines_from_words(words)

            # --- embedded figures (filter out tiny glyphs/logos) ---
            for img in page.images:
                w = float(img["x1"]) - float(img["x0"])
                h = float(img["bottom"]) - float(img["top"])
                if w < 90 or h < 60:
                    continue
                crop = _crop(pimg, page, (img["x0"], img["top"], img["x1"], img["bottom"]))
                if crop is None:
                    continue
                fig_n += 1
                fid = f"fig{fig_n}"
                dest = figures_dir / f"{fid}.png"
                crop.save(dest)
                cap = _find_figure_caption(lines, (img["x0"], img["top"], img["x1"], img["bottom"]))
                figures[fid] = Figure(id=fid, path=dest, caption=cap or f"Figure {fig_n} (p.{pageno + 1})")

            # --- equation regions: centered, math-heavy lines ---
            page_w = float(page.width)
            for line in lines:
                text = " ".join(w["text"] for w in line)
                if len(text) > 80 or len(text) < 2:
                    continue
                x0 = min(w["x0"] for w in line)
                x1 = max(w["x1"] for w in line)
                top = min(w["top"] for w in line)
                bottom = max(w["bottom"] for w in line)
                width = x1 - x0
                center = (x0 + x1) / 2
                centered = abs(center - page_w / 2) < page_w * 0.16
                indented = x0 > page_w * 0.14
                narrow = width < page_w * 0.72
                if not (centered and narrow and (indented or width < page_w * 0.5)):
                    continue
                if not _MATH_CHARS.search(text):
                    continue
                if _NUM_HEADING.match(text) or _NAMED_HEADING.match(text):
                    continue
                crop = _crop(pimg, page, (x0, top, x1, bottom), pad=6.0)
                if crop is None or crop.width < 30:
                    continue
                eq_n += 1
                fid = f"eq{eq_n}"
                dest = figures_dir / f"{fid}.png"
                crop.save(dest)
                figures[fid] = Figure(id=fid, path=dest, caption=f"Equation: {text.strip()[:180]}")

    abstract, sections = _extract_sections(pages_text)
    log.info(
        "PDF parsed: %d sections, %d figures, %d equation crops",
        len(sections), fig_n, eq_n,
    )

    return Paper(
        arxiv_id=slug,
        title=title,
        authors=[],
        abstract=abstract,
        sections=sections,
        figures=figures,
        equations={},
    )
