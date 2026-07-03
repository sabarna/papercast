"""TTL-based cleanup of the workspace directory.

Each job writes intermediates + the final mp4 under workspace_dir/<job_id>/.
Without pruning, the Fly volume fills up; this module deletes any job dir
older than RETENTION_DAYS (by mtime).
"""
from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger(__name__)

RETENTION_DAYS = 1


def cleanup_workspace(workspace_dir: Path, retention_days: int = RETENTION_DAYS) -> int:
    if not workspace_dir.exists():
        return 0
    cutoff = time.time() - retention_days * 86400
    deleted = 0
    for entry in workspace_dir.iterdir():
        if not entry.is_dir():
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry)
                log.info("cleanup: deleted %s (older than %dd)", entry.name, retention_days)
                deleted += 1
        except OSError as e:
            log.warning("cleanup: failed to delete %s: %s", entry, e)
    return deleted


def prune_intermediates(workdir: Path, keep: Iterable[Path | None]) -> int:
    """Delete everything in `workdir` except the named children in `keep`.

    Used right after a job succeeds: we hold on to the final mp4 + script.json
    and drop the source tarball, figures, slide PNGs, and TTS chunks — those
    are 80%+ of a job's footprint and aren't served to the user.

    Returns the number of top-level entries removed.
    """
    if not workdir.exists():
        return 0
    keep_names = {p.name for p in keep if p is not None and p.parent == workdir}
    removed = 0
    for entry in workdir.iterdir():
        if entry.name in keep_names:
            continue
        try:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            removed += 1
        except OSError as e:
            log.warning("prune: failed to delete %s: %s", entry, e)
    if removed:
        log.info("prune: removed %d intermediate entries from %s", removed, workdir.name)
    return removed
