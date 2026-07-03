"""PaperCast command-line interface.

Generate a narrated slideshow video from an arXiv paper straight from the
terminal — no web server required:

    papercast 2301.07041
    papercast https://arxiv.org/abs/2301.07041 -o talk.mp4 --duration 300 --voice nova

The same pipeline powers the web UI (`papercast-web`).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import shutil
import sys
from pathlib import Path

from app.config import settings

log = logging.getLogger("papercast.cli")

# accepts "2301.07041", "2301.07041v2", full URLs, and abs/pdf URLs
_ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


def _normalize_arxiv_id(raw: str) -> str:
    m = _ARXIV_RE.search(raw)
    if not m:
        raise SystemExit(f"error: could not parse an arXiv ID from: {raw!r}")
    return m.group(1)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="papercast",
        description="Turn an arXiv paper into a narrated slideshow video, locally.",
    )
    p.add_argument("paper", help="arXiv ID or URL (e.g. 2301.07041)")
    p.add_argument(
        "-o", "--output", type=Path, default=None,
        help="output .mp4 path (default: ./<arxiv_id>.mp4)",
    )
    p.add_argument(
        "--duration", type=int, default=None,
        help="target video length in seconds (default: %d)" % settings.target_duration_s,
    )
    p.add_argument("--voice", default=None, help="TTS voice (default: %s)" % settings.tts_voice)
    p.add_argument("--model", default=None, help="OpenAI model for the narrative (default: %s)" % settings.narrative_model)
    p.add_argument(
        "--keep-workspace", action="store_true",
        help="keep intermediate files (source, slides, audio) instead of pruning them",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="verbose (DEBUG) logging")
    return p


def _check_keys() -> None:
    if not settings.openai_api_key:
        raise SystemExit(
            "error: missing required OPENAI_API_KEY.\n"
            "Set it in a .env file (see .env.example) or as an environment variable."
        )


async def _run(args: argparse.Namespace) -> Path:
    # Import pipeline lazily so `--help` stays fast and import-light.
    from app.cleanup import prune_intermediates
    from app.pipeline import assemble, ingest, narrative, parse, slides, structure, tts

    arxiv_id = _normalize_arxiv_id(args.paper)
    workdir = settings.job_dir(f"cli-{arxiv_id}")
    output = args.output or Path(f"{arxiv_id}.mp4")

    log.info("[1/7] Fetching arXiv source for %s", arxiv_id)
    source_dir = await ingest.fetch_arxiv_source(arxiv_id, workdir)

    log.info("[2/7] Parsing LaTeX")
    parsed = await asyncio.to_thread(parse.parse_source, source_dir)
    paper = await asyncio.to_thread(structure.build_paper, arxiv_id, parsed, workdir)
    log.info("       %r — %d sections, %d figures, %d equations",
             paper.title, len(paper.sections), len(paper.figures), len(paper.equations))

    log.info("[3/7] Writing narrative (%s)", settings.narrative_model)
    script = await narrative.generate_script(paper, settings.target_duration_s)
    script_path = workdir / "script.json"
    script_path.write_text(script.model_dump_json(indent=2))
    log.info("       %d beats", len(script.beats))

    log.info("[4/7] Rendering slides")
    slide_paths = await slides.render_slides(script, paper, workdir)

    log.info("[5/7] Generating voiceover (%s / %s)", settings.tts_model, settings.tts_voice)
    audio_segments = await tts.synthesize(script, workdir)

    log.info("[6/7] Encoding video")
    video_path = await asyncio.to_thread(
        assemble.build_video, slide_paths, audio_segments, workdir
    )

    log.info("[7/7] Saving to %s", output)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video_path, output)

    if not args.keep_workspace:
        await asyncio.to_thread(prune_intermediates, workdir, [script_path])

    return output


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    # apply per-run overrides onto the shared settings singleton
    if args.duration is not None:
        settings.target_duration_s = args.duration
    if args.voice is not None:
        settings.tts_voice = args.voice
    if args.model is not None:
        settings.narrative_model = args.model

    _check_keys()

    try:
        output = asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001
        log.error("failed: %s", e)
        return 1

    print(f"\n✓ Done: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
