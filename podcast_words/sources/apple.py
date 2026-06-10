"""Apple Podcasts transcript fetch via the FetchTranscript macOS helper.

Discovery is delegated to apple_catalog (public iTunes Lookup). Fetching the
actual transcript requires macOS 15.5+ and a built FetchTranscript binary
(see tools/apple/), which downloads a TTML file we convert to VTT.

Reference: https://github.com/dado3212/apple-podcast-transcript-downloader
"""

from __future__ import annotations

import platform
import re
import subprocess
import tempfile
from pathlib import Path

from podcast_words.catalog import Episode
from podcast_words.config import PROJECT_ROOT, PodcastConfig, SourceConfig
from podcast_words.models import Transcript
from podcast_words.sources.apple_catalog import discover  # re-exported for the orchestrator
from podcast_words.transcripts import ttml

FETCH_TRANSCRIPT_BIN = PROJECT_ROOT / "tools" / "apple" / "FetchTranscript"

# Apple episode trackIds are numeric. Enforcing this prevents a crafted
# source_id (e.g. starting with '-') from being parsed as a CLI flag by the
# helper binary (argument injection).
_TRACK_ID_RE = re.compile(r"^[0-9]+$")

__all__ = ["discover", "fetch_transcript", "ensure_supported"]


class AppleUnsupportedError(RuntimeError):
    """Raised when Apple transcript fetching cannot run on this machine."""


def _macos_version() -> tuple[int, int]:
    release = platform.mac_ver()[0]
    parts = release.split(".")
    major = int(parts[0]) if parts and parts[0] else 0
    minor = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    return major, minor


def ensure_supported() -> None:
    """Raise AppleUnsupportedError unless this machine can fetch Apple transcripts."""
    if platform.system() != "Darwin":
        raise AppleUnsupportedError(
            "Apple transcript fetching is only supported on macOS (15.5+)."
        )
    major, minor = _macos_version()
    if (major, minor) < (15, 5):
        raise AppleUnsupportedError(
            f"Apple transcript fetching requires macOS 15.5+, found {major}.{minor}."
        )
    if not FETCH_TRANSCRIPT_BIN.exists():
        raise AppleUnsupportedError(
            f"FetchTranscript binary not found at {FETCH_TRANSCRIPT_BIN}. "
            "Build it from tools/apple/ (see tools/apple/README.md)."
        )


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

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        try:
            subprocess.run(
                [str(FETCH_TRANSCRIPT_BIN), episode.source_id, "--cache-bearer-token"],
                cwd=tmp_dir,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.CalledProcessError:
            return None

        ttml_files = list(tmp_dir.glob("*.ttml"))
        if not ttml_files:
            return None

        # Persist a raw copy for debugging/backup.
        raw_dir = podcast.transcripts_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"episode_{episode.number}.ttml"
        raw_path.write_text(ttml_files[0].read_text(encoding="utf-8"), encoding="utf-8")

        transcript = ttml.parse_file(ttml_files[0])
        return transcript if transcript.cues else None
