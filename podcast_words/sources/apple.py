"""Apple Podcasts transcript fetch via the FetchTranscript macOS helper.

Discovery is delegated to apple_catalog (iTunes Lookup + amp-api pagination).
Fetching the actual transcript requires macOS 15.5+ and a built FetchTranscript
binary (see tools/apple/), which downloads a TTML file we convert to VTT.

Reference: https://github.com/dado3212/apple-podcast-transcript-downloader
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from podcast_words.catalog import Episode
from podcast_words.config import PodcastConfig, SourceConfig
from podcast_words.models import Transcript
from podcast_words.sources.apple_auth import (
    AppleUnsupportedError,
    FETCH_TRANSCRIPT_BIN,
    ensure_supported,
)
from podcast_words.sources.apple_catalog import discover  # re-exported for the orchestrator
from podcast_words.transcripts import ttml

# Apple episode trackIds are numeric. Enforcing this prevents a crafted
# source_id (e.g. starting with '-') from being parsed as a CLI flag by the
# helper binary (argument injection).
_TRACK_ID_RE = re.compile(r"^[0-9]+$")

__all__ = ["discover", "fetch_transcript", "ensure_supported", "AppleUnsupportedError"]


def fetch_transcript(
    podcast: PodcastConfig, source: SourceConfig, episode: Episode
) -> Transcript | None:
    """Fetch and convert an episode's Apple transcript, or None if unavailable."""
    ensure_supported()
    if not episode.source_id:
        return None
    if not _TRACK_ID_RE.match(episode.source_id):
        raise ValueError(
            f"Refusing to fetch: episode source_id {episode.source_id!r} is not a "
            "numeric Apple trackId."
        )

    work_dir = FETCH_TRANSCRIPT_BIN.parent
    expected_ttml = work_dir / f"transcript_{episode.source_id}.ttml"
    if expected_ttml.exists():
        expected_ttml.unlink()
    try:
        subprocess.run(
            [str(FETCH_TRANSCRIPT_BIN), episode.source_id, "--cache-bearer-token"],
            cwd=work_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.CalledProcessError:
        return None

    ttml_path = expected_ttml if expected_ttml.exists() else None
    if ttml_path is None:
        # Fallback for older helper builds that use ttmlToken-derived names.
        matches = sorted(work_dir.glob(f"*{episode.source_id}*.ttml"))
        ttml_path = matches[-1] if matches else None
    if ttml_path is None:
        return None

    # Persist a raw copy for debugging/backup.
    raw_dir = podcast.transcripts_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"episode_{episode.number}.ttml"
    raw_path.write_text(ttml_path.read_text(encoding="utf-8"), encoding="utf-8")

    transcript = ttml.parse_file(ttml_path)
    return transcript if transcript.cues else None
