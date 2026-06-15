"""Re-convert saved Apple TTML files in transcripts/raw/ to WebVTT."""

from __future__ import annotations

import re
from pathlib import Path

from podcast_words.config import PodcastConfig
from podcast_words.transcripts import ttml, vtt

_RAW_EPISODE_RE = re.compile(r"episode_(\d+)\.ttml$", re.IGNORECASE)


def reconvert_raw(
    podcast: PodcastConfig,
    *,
    all_episodes: bool = False,
    dry_run: bool = False,
) -> dict:
    """Rewrite VTT from raw TTML when conversion looks incomplete or missing.

    By default only episodes where the VTT has fewer cues than the TTML are
    updated. Pass all_episodes=True to force a full re-conversion.
    """
    raw_dir = podcast.transcripts_dir / "raw"
    if not raw_dir.is_dir():
        return {"updated": 0, "skipped": 0, "errors": 0, "candidates": []}

    podcast.transcripts_dir.mkdir(parents=True, exist_ok=True)
    updated = 0
    skipped = 0
    errors = 0
    candidates: list[int] = []

    for ttml_path in sorted(raw_dir.glob("episode_*.ttml")):
        match = _RAW_EPISODE_RE.match(ttml_path.name)
        if not match:
            skipped += 1
            continue
        number = int(match.group(1))
        vtt_path = podcast.transcripts_dir / f"episode_{number}.vtt"

        try:
            transcript = ttml.parse_file(ttml_path)
            ttml_cues = len(transcript.cues)
            if ttml_cues == 0:
                skipped += 1
                continue

            vtt_cues = len(vtt.parse_file(vtt_path).cues) if vtt_path.exists() else 0
            if not all_episodes and vtt_path.exists() and vtt_cues >= ttml_cues:
                skipped += 1
                continue

            candidates.append(number)
            if dry_run:
                updated += 1
                continue

            vtt.write_file(transcript, vtt_path)
            updated += 1
        except Exception:
            errors += 1

    return {
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "candidates": candidates,
    }
