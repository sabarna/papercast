"""Step 4 — ask Claude to turn the Paper into a Script of narrated beats.

The prompt instructs Claude to:
  * produce N beats sized for a ``target_duration_s`` video
    (~140 wpm narration, ~8s per beat on average)
  * reference ONLY figure/equation IDs that exist in the input
  * emit strict JSON matching the Script schema

We schema-validate the response. On validation failure, we retry once,
feeding the validation error back in.
"""
from __future__ import annotations

import json
import logging

from anthropic import AsyncAnthropic
from pydantic import ValidationError

from app.config import settings
from app.models import Paper, Script

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are a science communicator. Given a structured academic paper, produce a \
narrated slideshow script suitable for a 5–10 minute educational video.

OUTPUT FORMAT (strict):
Return ONLY a single JSON object matching this schema, with no prose before or \
after:

{
  "target_duration_s": <int>,
  "beats": [
    {
      "id": <int, 1-indexed>,
      "narration": "<spoken text, 40-120 words>",
      "visual": {
        "kind": "title" | "bullets" | "figure" | "equation" | "split",
        "title": <string|null>,
        "bullets": <array of strings|null>,
        "figure_id": <string|null>,   // must match a figure ID from the paper
        "equation_id": <string|null>, // must match an equation ID from the paper
        "caption": <string|null>
      },
      "duration_hint_s": <float>
    }
  ]
}

CONSTRAINTS:
- Use figure_id / equation_id values ONLY from the lists provided.
- Narration should read naturally aloud. No markdown, no LaTeX, no parentheticals \
  like "(see Figure 3)" — instead describe what's on screen.
- Aim for ~140 words per minute of narration.
- Structure: title → motivation → key idea → method → headline result → \
  takeaway. Skip or compress parts of the paper that don't serve this arc.
- Every figure you reference must get at least 3 seconds of screen time.
"""


def _serialize_paper_for_prompt(paper: Paper) -> str:
    """Compact JSON view of the paper for the LLM."""
    return json.dumps(
        {
            "title": paper.title,
            "authors": paper.authors,
            "abstract": paper.abstract,
            "sections": [
                {
                    "title": s.title,
                    "level": s.level,
                    "text": s.text[:4000],  # truncate very long sections
                    "figure_ids": s.figure_ids,
                    "equation_ids": s.equation_ids,
                }
                for s in paper.sections
            ],
            "figures": [
                {"id": f.id, "caption": f.caption} for f in paper.figures.values()
            ],
            "equations": [
                {"id": e.id, "latex": e.latex[:400]} for e in paper.equations.values()
            ],
        },
        indent=2,
    )


async def generate_script(paper: Paper, target_duration_s: int) -> Script:
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    paper_json = _serialize_paper_for_prompt(paper)

    user_msg = (
        f"Target video length: {target_duration_s} seconds.\n\n"
        f"Here is the paper as structured JSON:\n\n{paper_json}\n\n"
        "Produce the script JSON now."
    )

    last_error: str | None = None
    for attempt in range(2):
        messages = [{"role": "user", "content": user_msg}]
        if last_error:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"The previous response failed validation: {last_error}. "
                        "Please correct and return only the JSON."
                    ),
                }
            )

        resp = await client.messages.create(
            model=settings.claude_model,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )

        try:
            data = _extract_json(text)
            script = Script.model_validate(data)
            _validate_ids(script, paper)
            return script
        except (ValidationError, ValueError) as e:
            last_error = str(e)
            log.warning("script validation failed (attempt %d): %s", attempt + 1, e)

    raise RuntimeError(f"Could not produce a valid script after 2 attempts: {last_error}")


def _extract_json(text: str) -> dict:
    """Pull a JSON object out of the model's reply, tolerating code fences."""
    text = text.strip()
    if text.startswith("```"):
        # strip a single fenced block
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in model reply")
    return json.loads(text[start : end + 1])


def _validate_ids(script: Script, paper: Paper) -> None:
    """Ensure every figure/equation reference points to something that exists."""
    for beat in script.beats:
        v = beat.visual
        if v.figure_id and v.figure_id not in paper.figures:
            raise ValueError(f"beat {beat.id} references unknown figure {v.figure_id}")
        if v.equation_id and v.equation_id not in paper.equations:
            raise ValueError(f"beat {beat.id} references unknown equation {v.equation_id}")
