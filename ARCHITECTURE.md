# PaperCast — Architecture

An MVP that turns an arXiv paper into a 5–10 minute narrated slideshow video.

## 1. Product at a glance

**User flow (MVP):**
1. User visits `localhost:8000`, pastes an arXiv ID (e.g. `2301.07041`) or URL.
2. Backend kicks off a job, streams status updates to the page via HTMX polling.
3. When done, the page shows an inline `<video>` player and a download link to the `.mp4`.

**Non-goals (MVP):** multi-user accounts, billing, avatar video, Manim-style animation, non-arXiv papers, video editing UI.

## 2. Tech stack

| Concern          | Choice                                   | Why                                                     |
|------------------|------------------------------------------|---------------------------------------------------------|
| Web framework    | FastAPI + Jinja2 + HTMX                  | One Python process, minimal JS, easy job-status polling |
| LLM              | OpenAI GPT (`gpt-5.5`)                    | Long context (whole paper fits), strong reasoning       |
| TTS              | OpenAI TTS (`tts-1` / `gpt-4o-mini-tts`) | Cheap, fast, decent natural voice                       |
| LaTeX parsing    | `pylatexenc` + custom heuristics         | Pure Python, handles arXiv's messy real-world LaTeX     |
| Math rendering   | `matplotlib` mathtext OR KaTeX → PNG     | No full TeX install needed for MVP                      |
| Slide rendering  | HTML template → `playwright` screenshot  | Full CSS control, same template renders in browser too  |
| Video assembly   | `ffmpeg` via `ffmpeg-python`             | Battle-tested, handles audio+image concat               |
| Job queue        | `asyncio.create_task` + in-memory dict   | Single-user MVP; swap for Redis/RQ later                |
| Storage          | Local `workspace/<job_id>/` folders      | Files on disk, no DB                                    |

## 3. Pipeline

```
┌──────────┐   ┌─────────┐   ┌───────────┐   ┌──────────┐   ┌────────┐   ┌──────┐   ┌──────────┐
│  Ingest  │──▶│  Parse  │──▶│ Structure │──▶│ Narrative│──▶│ Slides │──▶│ TTS  │──▶│ Assemble │
└──────────┘   └─────────┘   └───────────┘   └──────────┘   └────────┘   └──────┘   └──────────┘
  arXiv ID      .tex tree      Paper model     Script JSON    .png/slide   .mp3/beat    .mp4
```

### 3.1 Ingest (`app/pipeline/ingest.py`)
- Input: arXiv ID or URL.
- Fetches `https://arxiv.org/e-print/<id>` — a gzipped tarball of the paper's source.
- Unpacks to `workspace/<job_id>/source/`.
- Also fetches the PDF as a fallback for visual references.
- Handles the edge case where the "tarball" is actually a single `.tex` file or a PDF-only submission.

### 3.2 Parse (`app/pipeline/parse.py`)
- Finds the main `.tex` (the one with `\documentclass` and `\begin{document}`).
- Resolves `\input{}` / `\include{}` / `\import{}` by concatenating into a single logical document.
- Walks the AST with `pylatexenc.latexwalker`, emitting a stream of nodes:
  `section`, `subsection`, `paragraph`, `equation`, `figure`, `table`, `citation`, `label`, `ref`.
- Extracts every `\includegraphics{...}` path, resolves relative to the source dir, copies images into `workspace/<job_id>/figures/`.
- Pulls out each `equation` / `align` / `\[...\]` block verbatim and assigns a stable `eq_id`.

### 3.3 Structure (`app/pipeline/structure.py` → `app/models.py`)

Builds a typed `Paper` object:

```python
class Figure(BaseModel):
    id: str            # "fig1"
    path: Path         # local file
    caption: str
    label: str | None  # \label{fig:foo}

class Equation(BaseModel):
    id: str            # "eq1"
    latex: str
    rendered_path: Path | None  # PNG render

class Section(BaseModel):
    title: str
    level: int
    text: str                 # plain-text prose, LaTeX stripped
    figures: list[str]        # figure IDs referenced in this section
    equations: list[str]      # equation IDs in this section

class Paper(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    sections: list[Section]
    figures: dict[str, Figure]
    equations: dict[str, Equation]
```

### 3.4 Narrative (`app/pipeline/narrative.py`)

Single OpenAI call with the full `Paper` serialized as a structured prompt. Output is a JSON `Script`:

```python
class Beat(BaseModel):
    id: int
    narration: str         # spoken text, ~40-120 words
    visual: Visual         # what to show on the slide
    duration_hint_s: float # rough guess; actual = TTS output length

class Visual(BaseModel):
    kind: Literal["title", "bullets", "figure", "equation", "split"]
    title: str | None
    bullets: list[str] | None
    figure_id: str | None
    equation_id: str | None

class Script(BaseModel):
    target_duration_s: int   # e.g. 420 for 7 min
    beats: list[Beat]
```

**Prompt strategy:** the system prompt instructs the model to act as a science communicator, produce ~N beats for a 5–10 min video, and *must only reference figure/equation IDs that exist in the input*. We validate this on parse; on violation we retry once with the error appended.

### 3.5 Slides (`app/pipeline/slides.py`)
- One Jinja2 template `slide.html` with layout variants per `Visual.kind`.
- Render each beat's HTML → screenshot with Playwright (`page.screenshot`), 1920×1080 PNG.
- For equation beats, the rendered LaTeX comes from KaTeX (client-side) so the screenshot captures the typeset math.
- Figures are `<img>` tags pointing at files in `workspace/<job_id>/figures/`.

### 3.6 TTS (`app/pipeline/tts.py`)
- OpenAI `audio.speech.create` per beat, voice configurable (`alloy` default).
- Saves `beat_001.mp3`, probes duration with `ffprobe`.
- Returns `list[(beat_id, audio_path, duration_s)]`.

### 3.7 Assemble (`app/pipeline/assemble.py`)
- Build an ffmpeg concat list: each slide PNG shown for the matching audio's exact duration.
- Mix: video stream from PNG sequence + audio stream from concatenated MP3s.
- Optional: soft 0.3s crossfade between slides; subtle background music (post-MVP).
- Output: `workspace/<job_id>/output.mp4` — H.264 / AAC, web-playable.

## 4. Web layer

### 4.1 Routes (`app/main.py`)
| Method | Path                    | Purpose                                   |
|--------|-------------------------|-------------------------------------------|
| GET    | `/`                     | Upload form                               |
| POST   | `/jobs`                 | Create job from arXiv ID, redirect to `/jobs/{id}` |
| GET    | `/jobs/{id}`            | Job detail page                           |
| GET    | `/jobs/{id}/status`     | HTMX partial — polled every 2s            |
| GET    | `/jobs/{id}/video`      | Serves the final `.mp4`                   |
| GET    | `/jobs/{id}/script`     | Download the generated script JSON        |

### 4.2 Job lifecycle
Status enum: `queued → ingesting → parsing → scripting → rendering_slides → tts → assembling → done | failed`.

Status updates written to `jobs[id].status` in-memory; HTMX `hx-trigger="every 2s"` re-fetches `/jobs/{id}/status` and swaps the progress block.

## 5. Configuration (`.env`)

```
OPENAI_API_KEY=sk-...
NARRATIVE_MODEL=gpt-5.5
TTS_VOICE=alloy
TARGET_DURATION_S=420
WORKSPACE_DIR=./workspace
```

## 6. Known risks & mitigations

| Risk                                                  | Mitigation                                                                   |
|-------------------------------------------------------|------------------------------------------------------------------------------|
| arXiv source has no `.tex` (PDF-only submission)      | Fall back to PDF parsing (Nougat/GROBID) — flagged as Phase 2                |
| Main `.tex` detection fails on multi-doc sources      | Heuristic: file containing `\documentclass` with largest content             |
| `\includegraphics` uses `.pdf` / `.eps`               | Convert with `pdftoppm` / `convert` at parse time                            |
| Model hallucinates figure IDs                        | Schema-validate output, retry once with error, fall back to bullet-only beats |
| TTS duration > slide visual (e.g. long narration on title slide) | Durations are driven by TTS, not slide hints — always audio-first     |
| `ffmpeg` missing on user's machine                    | Detect at startup, show setup instructions                                   |
| Long papers blow out context window                   | Section-level summarization pass before the narrative call                   |

## 7. Phased roadmap

**Phase 1 (MVP — this scaffold):** arXiv → 5–10 min narrated slideshow, single user, local only.

**Phase 2:** PDF fallback (non-arXiv papers), voice selection, script editing before TTS, better math rendering.

**Phase 3:** Multi-user, persistent jobs (Postgres + Redis + RQ), S3 storage, auth.

**Phase 4:** Animated equation builds, avatar option, thumbnail generation, social-clip exporter.

## 8. Repo layout

```
paper-to-video/
├── ARCHITECTURE.md         ← this file
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── app/
│   ├── __init__.py
│   ├── main.py             # FastAPI app + routes
│   ├── config.py           # settings from env
│   ├── jobs.py             # in-memory job store + orchestrator
│   ├── models.py           # Pydantic: Paper, Figure, Script, Beat
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── ingest.py
│   │   ├── parse.py
│   │   ├── structure.py
│   │   ├── narrative.py
│   │   ├── slides.py
│   │   ├── tts.py
│   │   └── assemble.py
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── job.html
│   │   ├── _status.html    # HTMX partial
│   │   └── slide.html      # rendered to PNG
│   └── static/
│       └── styles.css
├── tests/
│   ├── test_ingest.py
│   ├── test_parse.py
│   └── test_narrative.py
└── workspace/              # per-job working dirs (gitignored)
```
