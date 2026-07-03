"""Step 7 — stitch slides + audio into a single MP4 with ffmpeg.

Each beat: one PNG shown for exactly the length of its audio. We build a
concat demuxer file listing ``file slide.png`` / ``duration N`` entries,
concatenate the audio segments, then mux.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from app.config import settings
from app.pipeline.tts import AudioSegment

log = logging.getLogger(__name__)


def build_video(
    slide_paths: list[Path],
    audio_segments: list[AudioSegment],
    workdir: Path,
) -> Path:
    if len(slide_paths) != len(audio_segments):
        raise ValueError(
            f"slides ({len(slide_paths)}) and audio segments ({len(audio_segments)}) mismatch"
        )

    # Sort both by beat id to be safe.
    paired = sorted(
        zip(slide_paths, audio_segments, strict=True),
        key=lambda p: p[1].beat_id,
    )

    # 1. build a concat list for slides (one line per beat)
    concat_file = workdir / "slides.concat.txt"
    with concat_file.open("w") as fh:
        for png, audio in paired:
            fh.write(f"file '{png.resolve()}'\n")
            fh.write(f"duration {audio.duration_s:.3f}\n")
        # ffmpeg concat demuxer quirk: repeat the last file with no duration
        fh.write(f"file '{paired[-1][0].resolve()}'\n")

    # 2. build a concat list for audio
    audio_concat_file = workdir / "audio.concat.txt"
    with audio_concat_file.open("w") as fh:
        for _, audio in paired:
            fh.write(f"file '{audio.path.resolve()}'\n")

    # 3. encode the silent video from the slide concat
    silent_mp4 = workdir / "silent.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-fps_mode", "cfr",
            "-r", str(settings.slide_fps),
            "-pix_fmt", "yuv420p",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            str(silent_mp4),
        ],
        check=True,
        capture_output=True,
    )

    # 4. concat audio
    merged_mp3 = workdir / "narration.mp3"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(audio_concat_file),
            "-c:a", "libmp3lame", "-b:a", "192k",
            str(merged_mp3),
        ],
        check=True,
        capture_output=True,
    )

    # 5. mux video + audio
    out_mp4 = workdir / "output.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(silent_mp4),
            "-i", str(merged_mp3),
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(out_mp4),
        ],
        check=True,
        capture_output=True,
    )

    log.info("wrote %s", out_mp4)
    return out_mp4
