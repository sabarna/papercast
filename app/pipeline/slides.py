"""Step 5 — render each beat's slide to a PNG.

We use Playwright (headless Chromium) so the same HTML template that renders
a slide in a browser also produces the PNG. This lets us use real CSS, web
fonts, and KaTeX for equation typesetting.

Each beat's HTML is written to ``<workdir>/slides/beat_<id>.html`` and
screenshotted at SLIDE_WIDTH × SLIDE_HEIGHT.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright

from app.config import settings
from app.models import Beat, Paper, Script


# Non-math LaTeX layout/spacing commands that sometimes get captured inside an
# equation. KaTeX can't use them, so we remove them (with their arguments)
# rather than let them render as stray text.
_LAYOUT_STRIP = [
    re.compile(r"\\setlength\s*\{?\s*\\[a-zA-Z@]+\s*\}?\s*\{[^}]*\}"),
    re.compile(r"\\(?:vspace|vskip|addvspace)\*?\s*\{[^}]*\}"),
    re.compile(r"\\(?:abovedisplayskip|belowdisplayskip|abovedisplayshortskip|belowdisplayshortskip)\b"),
    re.compile(r"\\(?:noindent|centering|raggedright|raggedleft|allowdisplaybreaks)\b"),
]


def _strip_layout_commands(latex: str) -> str:
    for pat in _LAYOUT_STRIP:
        latex = pat.sub(" ", latex)
    return latex


def _clean_equation_latex(latex: str) -> str:
    """Prep a raw LaTeX equation for KaTeX rendering.

    Papers often capture equations from ``align`` / ``equation`` environments,
    which carry constructs KaTeX can't handle inside plain ``$$...$$``:
      - ``\\label{...}`` — metadata, not math; just strip.
      - ``&`` column separators and ``\\\\`` row breaks — only valid inside
        an explicit alignment environment, so wrap in ``\\begin{aligned}``.
    """
    latex = re.sub(r"\\label\{[^}]*\}", "", latex)
    latex = _strip_layout_commands(latex).strip()
    # Only add an alignment wrapper if the equation needs one AND doesn't
    # already contain its own environment (nesting \begin{aligned} around an
    # existing \begin{gathered}/\begin{cases} makes KaTeX hard-fail).
    needs_align = "&" in latex or "\\\\" in latex
    if needs_align and "\\begin{" not in latex:
        latex = r"\begin{aligned}" + latex + r"\end{aligned}"
    return latex

log = logging.getLogger(__name__)


TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def _beat_context(beat: Beat, paper: Paper) -> dict:
    """Populate the template context for one beat."""
    v = beat.visual
    figure = paper.figures.get(v.figure_id) if v.figure_id else None
    equation = paper.equations.get(v.equation_id) if v.equation_id else None
    return {
        "visual": v,
        "figure_url": f"file://{figure.path.resolve()}" if figure else None,
        "figure_caption": figure.caption if figure else None,
        "equation_latex": _clean_equation_latex(equation.latex) if equation else None,
        "katex_macros": json.dumps(paper.macros),
        "paper_title": paper.title,
    }


async def render_slides(script: Script, paper: Paper, workdir: Path) -> list[Path]:
    slides_dir = workdir / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)
    env = _env()
    template = env.get_template("slide.html")

    # Render all HTML first, then batch screenshots with one browser.
    html_paths: list[Path] = []
    for beat in script.beats:
        ctx = _beat_context(beat, paper)
        html = template.render(**ctx)
        html_path = slides_dir / f"beat_{beat.id:03d}.html"
        html_path.write_text(html, encoding="utf-8")
        html_paths.append(html_path)

    png_paths: list[Path] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page(
                viewport={"width": settings.slide_width, "height": settings.slide_height}
            )
            for html_path in html_paths:
                png_path = html_path.with_suffix(".png")
                await page.goto(f"file://{html_path.resolve()}", wait_until="load")
                # auto-render.min.js sets this flag once KaTeX has finished
                # typesetting every $…$ / $$…$$ block on the page.
                await page.wait_for_function(
                    "document.body.dataset.katexDone === '1'", timeout=20000
                )
                await page.screenshot(path=str(png_path), full_page=False)
                png_paths.append(png_path)
                log.info("rendered %s", png_path.name)
        finally:
            await browser.close()

    return png_paths
