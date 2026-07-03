"""Step 2 — parse the unpacked LaTeX source into a structured form.

Produces a ``ParsedSource`` dataclass that ``structure.py`` then lifts into a
typed ``Paper``. We intentionally keep this step "close to the LaTeX" —
keeping raw equation strings, figure paths, and section prose — and do the
cleanup/normalization in structure.py.

The hard parts that earn their own attention later:
  - Detecting the main .tex when there are multiple candidates.
  - Resolving \\input, \\include, \\import recursively.
  - Handling \\includegraphics with .pdf/.eps (needs conversion to PNG).
  - Extracting inline vs display math with positions preserved.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pylatexenc.latex2text import LatexNodes2Text

log = logging.getLogger(__name__)


@dataclass
class RawFigure:
    path: Path          # resolved path on disk
    caption: str = ""
    label: str | None = None


@dataclass
class RawEquation:
    latex: str
    label: str | None = None


@dataclass
class RawSection:
    title: str
    level: int
    body: str                              # raw LaTeX
    figures: list[int] = field(default_factory=list)   # indices into ParsedSource.figures
    equations: list[int] = field(default_factory=list) # indices into ParsedSource.equations


@dataclass
class ParsedSource:
    main_tex: Path
    source_dir: Path
    title: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    sections: list[RawSection] = field(default_factory=list)
    figures: list[RawFigure] = field(default_factory=list)
    equations: list[RawEquation] = field(default_factory=list)
    macros: dict = field(default_factory=dict)   # {"\\name": "body"} for KaTeX


# --- entry point ---

def parse_source(source_dir: Path) -> ParsedSource:
    """Walk the unpacked arXiv source and produce a ParsedSource."""
    main_tex = _find_main_tex(source_dir)
    log.info("main .tex: %s", main_tex)

    flat = _resolve_inputs(main_tex, source_dir)
    ps = ParsedSource(main_tex=main_tex, source_dir=source_dir)

    ps.title = _extract_command(flat, "title") or ""
    ps.authors = _extract_authors(flat)
    ps.abstract = _extract_environment(flat, "abstract") or ""

    ps.figures = _extract_figures(flat, source_dir)
    ps.equations = _extract_equations(flat)
    ps.macros = _extract_all_macros(source_dir)
    ps.sections = _split_into_sections(flat, ps)

    return ps


# --- helpers ---

def _find_main_tex(source_dir: Path) -> Path:
    """Pick the .tex that looks like the top-level document."""
    candidates = list(source_dir.rglob("*.tex"))
    if not candidates:
        raise FileNotFoundError(f"No .tex files found in {source_dir}")

    def score(p: Path) -> tuple[int, int]:
        txt = p.read_text(errors="ignore")
        has_class = "\\documentclass" in txt
        has_begin = "\\begin{document}" in txt
        # prefer files with \documentclass AND \begin{document}, then size
        return (int(has_class) + int(has_begin), len(txt))

    return max(candidates, key=score)


_INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")


def _resolve_inputs(main_tex: Path, source_dir: Path, seen: set[Path] | None = None) -> str:
    """Recursively inline \\input and \\include directives."""
    if seen is None:
        seen = set()
    if main_tex in seen:
        return ""
    seen.add(main_tex)

    text = main_tex.read_text(errors="ignore")

    def sub(m: re.Match[str]) -> str:
        name = m.group(1).strip()
        # try with and without .tex
        for candidate in [source_dir / name, source_dir / f"{name}.tex"]:
            if candidate.exists() and candidate.is_file():
                return _resolve_inputs(candidate, source_dir, seen)
        log.warning("could not resolve \\input{%s}", name)
        return ""

    return _INPUT_RE.sub(sub, text)


_TITLE_RE = re.compile(r"\\title\{((?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL)


def _extract_command(src: str, cmd: str) -> str | None:
    """Extract a brace-delimited command like \\title{...}. One-level nesting OK."""
    if cmd == "title":
        m = _TITLE_RE.search(src)
        if not m:
            return None
        return _tex_to_text(m.group(1)).strip()

    pattern = re.compile(rf"\\{cmd}\{{((?:[^{{}}]|\{{[^{{}}]*\}})*)\}}", re.DOTALL)
    m = pattern.search(src)
    return _tex_to_text(m.group(1)).strip() if m else None


def _extract_authors(src: str) -> list[str]:
    raw = _extract_command(src, "author")
    if not raw:
        return []
    # Rough heuristic: split on ' and ' or commas at top level
    parts = re.split(r"\s+and\s+|,", raw)
    return [p.strip() for p in parts if p.strip()]


def _extract_environment(src: str, env: str) -> str | None:
    pattern = re.compile(
        rf"\\begin\{{{env}\}}(.*?)\\end\{{{env}\}}", re.DOTALL
    )
    m = pattern.search(src)
    if not m:
        return None
    return _tex_to_text(m.group(1)).strip()


_FIGURE_ENV_RE = re.compile(r"\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}", re.DOTALL)
_INCLUDEGRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
_CAPTION_RE = re.compile(r"\\caption\{((?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL)
_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")


def _extract_figures(src: str, source_dir: Path) -> list[RawFigure]:
    figures: list[RawFigure] = []
    for m in _FIGURE_ENV_RE.finditer(src):
        body = m.group(1)
        graphics = _INCLUDEGRAPHICS_RE.findall(body)
        if not graphics:
            continue
        caption_m = _CAPTION_RE.search(body)
        label_m = _LABEL_RE.search(body)
        # Use first \includegraphics per figure env for MVP
        resolved = _resolve_figure_path(graphics[0], source_dir)
        if resolved is None:
            log.warning("figure path not found: %s", graphics[0])
            continue
        figures.append(
            RawFigure(
                path=resolved,
                caption=_tex_to_text(caption_m.group(1)).strip() if caption_m else "",
                label=label_m.group(1) if label_m else None,
            )
        )
    return figures


def _resolve_figure_path(name: str, source_dir: Path) -> Path | None:
    name = name.strip()
    # Try the exact name and common extensions
    exts = ["", ".pdf", ".png", ".jpg", ".jpeg", ".eps"]
    for ext in exts:
        p = (source_dir / f"{name}{ext}")
        if p.exists():
            return p
    # Recursive fallback
    for candidate in source_dir.rglob("*"):
        if candidate.is_file() and candidate.stem == Path(name).stem:
            return candidate
    return None


_EQUATION_BLOCKS = [
    (re.compile(r"\\begin\{equation\*?\}(.*?)\\end\{equation\*?\}", re.DOTALL), None),
    (re.compile(r"\\begin\{align\*?\}(.*?)\\end\{align\*?\}", re.DOTALL), None),
    (re.compile(r"\\\[(.*?)\\\]", re.DOTALL), None),
]


def _extract_equations(src: str) -> list[RawEquation]:
    eqs: list[RawEquation] = []
    for pattern, _ in _EQUATION_BLOCKS:
        for m in pattern.finditer(src):
            body = m.group(1).strip()
            label_m = _LABEL_RE.search(body)
            eqs.append(RawEquation(latex=body, label=label_m.group(1) if label_m else None))
    return eqs


_SECTION_SPLIT_RE = re.compile(
    r"\\(section|subsection|subsubsection)\*?\{((?:[^{}]|\{[^{}]*\})*)\}",
    re.DOTALL,
)
_LEVEL = {"section": 1, "subsection": 2, "subsubsection": 3}


def _split_into_sections(src: str, ps: ParsedSource) -> list[RawSection]:
    """Split the resolved source into sections at every \\section-family command.

    Body text is kept raw; structure.py converts it to plain text.
    Each section records which figure/equation indices appear within its span.
    """
    matches = list(_SECTION_SPLIT_RE.finditer(src))
    if not matches:
        return []

    sections: list[RawSection] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(src)
        body = src[start:end]
        sec = RawSection(
            title=_tex_to_text(m.group(2)).strip(),
            level=_LEVEL[m.group(1)],
            body=body,
        )
        # Cross-reference figures/equations by position
        for idx, fig in enumerate(ps.figures):
            # cheap: figures are referenced in-body by \includegraphics or \ref
            # we mark a figure as "in section" if its path basename shows up
            if fig.path.name in body:
                sec.figures.append(idx)
        for idx, eq in enumerate(ps.equations):
            if eq.latex[:30] in body:
                sec.equations.append(idx)
        sections.append(sec)
    return sections


_LATEX2TEXT = LatexNodes2Text(math_mode="verbatim")


def _tex_to_text(s: str) -> str:
    try:
        return _LATEX2TEXT.latex_to_text(s)
    except Exception:  # noqa: BLE001
        # pylatexenc can choke on weird fragments; fall back to regex cleanup
        return re.sub(r"\\[a-zA-Z]+\*?", "", s)


# --- custom macro extraction (so KaTeX understands the paper's own commands) ---

# Commands KaTeX doesn't implement but that are harmless in always-math context.
_SHIM_MACROS = {
    "\\ensuremath": "#1",   # KaTeX is already in math mode
    "\\xspace": "",
}

# The `cryptocode` package (very common in crypto papers) ships style wrappers
# that aren't in the arXiv source, so we can't extract them — shim them here so
# paper macros that expand to \pcalgostyle{...} etc. render instead of breaking.
_CRYPTOCODE_SHIMS = {
    "\\pcalgostyle": "\\mathsf{#1}",
    "\\pckeystyle": "\\mathsf{#1}",
    "\\pcnotionstyle": "\\mathrm{#1}",
    "\\pcmathhyphen": "\\text{-}",
    "\\highlightkeyword": "#1",
    "\\texorpdfstring": "#1",
    "\\pcalgo": "\\mathsf{#1}",
}

_MACRO_STARTS = re.compile(
    r"\\(newcommand|renewcommand|providecommand|DeclareMathOperator|def)\b\*?"
)


def _read_group(src: str, i: int) -> tuple[str, int]:
    """src[i] must be '{'. Return (inner_text, index_after_matching_brace)."""
    depth = 0
    j = i
    while j < len(src):
        c = src[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[i + 1 : j], j + 1
        j += 1
    return src[i + 1 :], len(src)


def _extract_macros(src: str) -> dict:
    """Collect macro definitions from a LaTeX blob.

    Supports \\newcommand / \\renewcommand / \\providecommand / \\DeclareMathOperator
    and plain \\def. Returns ``{"\\name": "body"}`` for KaTeX's ``macros`` option;
    the body keeps ``#1`` placeholders so KaTeX infers the argument count.
    """
    macros: dict[str, str] = {}
    for m in _MACRO_STARTS.finditer(src):
        kind = m.group(1)
        i = m.end()
        while i < len(src) and src[i].isspace():
            i += 1
        # --- command name: {\name} or bare \name ---
        name = None
        if i < len(src) and src[i] == "{":
            grp, i = _read_group(src, i)
            name = grp.strip()
        elif i < len(src) and src[i] == "\\":
            j = i + 1
            while j < len(src) and src[j].isalpha():
                j += 1
            name = src[i:j]
            i = j
        if not name or not name.startswith("\\") or len(name) < 2:
            continue
        # --- everything between the name and the body brace is arg spec ---
        # (newcommand: [n][default];  def: #1#2...). Neither contains '{', so
        # scanning to the next top-level '{' lands us on the body for all forms.
        depth_brackets = 0
        while i < len(src):
            c = src[i]
            if c == "{":
                break
            if c == "\n" and depth_brackets == 0:
                # a def/newcommand body is on the same logical line; a bare newline
                # with no pending bracket means a malformed capture — bail.
                pass
            i += 1
        if i >= len(src) or src[i] != "{":
            continue
        body, i = _read_group(src, i)
        if kind == "DeclareMathOperator":
            body = "\\operatorname{" + body + "}"
        macros.setdefault(name, body)  # first definition wins
    return macros


def _extract_all_macros(source_dir: Path) -> dict:
    """Scan every .tex/.sty file in the source tree for macro definitions.

    Macros are frequently defined in a separate ``macros.tex`` or a local ``.sty``
    that the main file pulls in via \\usepackage — so we can't rely on the flattened
    main document alone.
    """
    macros: dict[str, str] = {}
    for pattern in ("*.tex", "*.sty"):
        for f in sorted(source_dir.rglob(pattern)):
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            for name, body in _extract_macros(text).items():
                macros.setdefault(name, body)
    # shims fill in only where the paper didn't define its own
    for shim in (_CRYPTOCODE_SHIMS, _SHIM_MACROS):
        for name, body in shim.items():
            macros.setdefault(name, body)
    return macros
