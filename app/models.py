"""Typed domain models used across the pipeline.

The Paper model is what comes out of parse+structure; the Script model is what
Claude returns from the narrative step. Both are JSON-serializable so they can
be inspected per-job in workspace/<job_id>/.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


# ---------- Parsed paper ----------

class Figure(BaseModel):
    id: str                       # "fig1"
    path: Path                    # local file, usually PNG/JPG
    caption: str = ""
    label: str | None = None      # \label{fig:foo} if present


class Equation(BaseModel):
    id: str                       # "eq1"
    latex: str
    rendered_path: Path | None = None  # optional pre-rendered PNG


class Section(BaseModel):
    title: str
    level: int = 1                # 1 = section, 2 = subsection, ...
    text: str = ""                # plain-text prose, LaTeX stripped
    figure_ids: list[str] = Field(default_factory=list)
    equation_ids: list[str] = Field(default_factory=list)


class Paper(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    sections: list[Section] = Field(default_factory=list)
    figures: dict[str, Figure] = Field(default_factory=dict)
    equations: dict[str, Equation] = Field(default_factory=dict)


# ---------- Narrative script ----------

VisualKind = Literal["title", "bullets", "figure", "equation", "split"]


class Visual(BaseModel):
    kind: VisualKind
    title: str | None = None
    bullets: list[str] | None = None
    figure_id: str | None = None
    equation_id: str | None = None
    caption: str | None = None   # optional sub-caption under the visual


class Beat(BaseModel):
    id: int
    narration: str               # spoken text
    visual: Visual
    duration_hint_s: float = 8.0 # rough — actual length comes from TTS


class Script(BaseModel):
    target_duration_s: int
    beats: list[Beat]


# ---------- Job tracking ----------

JobStatus = Literal[
    "queued",
    "ingesting",
    "parsing",
    "scripting",
    "rendering_slides",
    "tts",
    "assembling",
    "done",
    "failed",
]


class Job(BaseModel):
    id: str
    arxiv_id: str
    status: JobStatus = "queued"
    progress: float = 0.0          # 0..1
    message: str = ""              # human-readable status message
    error: str | None = None
    video_path: Path | None = None
    script_path: Path | None = None
