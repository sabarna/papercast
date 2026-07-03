"""Step 6 — narrate each beat using OpenAI TTS.

Returns a list of ``AudioSegment`` records, one per beat, with the on-disk
path and measured duration (via ffprobe). The assemble step uses these
durations to set slide on-screen time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from openai import AsyncOpenAI

from app.config import settings
from app.models import Script

log = logging.getLogger(__name__)


@dataclass
class AudioSegment:
    beat_id: int
    path: Path
    duration_s: float


async def synthesize(script: Script, workdir: Path) -> list[AudioSegment]:
    audio_dir = workdir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    # Parallelize TTS calls with modest concurrency
    sem = asyncio.Semaphore(4)

    async def one(beat) -> AudioSegment:
        async with sem:
            out_path = audio_dir / f"beat_{beat.id:03d}.mp3"
            async with client.audio.speech.with_streaming_response.create(
                model=settings.tts_model,
                voice=settings.tts_voice,
                input=beat.narration,
            ) as resp:
                await resp.stream_to_file(out_path)
            dur = _probe_duration(out_path)
            log.info("synthesized beat %d (%.2fs)", beat.id, dur)
            return AudioSegment(beat_id=beat.id, path=out_path, duration_s=dur)

    return list(await asyncio.gather(*(one(b) for b in script.beats)))


def _probe_duration(path: Path) -> float:
    """Use ffprobe to read the duration of an audio file in seconds."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])
