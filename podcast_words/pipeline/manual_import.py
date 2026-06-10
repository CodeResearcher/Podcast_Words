"""Manual transcript import for a single episode or a folder of files."""

from __future__ import annotations

import re
from pathlib import Path

from podcast_words.catalog import Catalog, Episode, STATE_DONE
from podcast_words.config import PodcastConfig
from podcast_words.transcripts import vtt
from podcast_words.transcripts.loader import TRANSCRIPT_EXTENSIONS, load_transcript

_FILENAME_NUMBER_RE = re.compile(r"episode[_\-]?(\d+)", re.IGNORECASE)


def _episode_number_from_filename(path: Path) -> int | None:
    match = _FILENAME_NUMBER_RE.search(path.stem)
    if match:
        return int(match.group(1))
    digits = re.search(r"(\d+)", path.stem)
    return int(digits.group(1)) if digits else None


def import_file(
    podcast: PodcastConfig, file_path: str | Path, *, episode: int | None = None
) -> int:
    """Import one transcript file. Returns the resolved episode number."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Transcript file not found: {file_path}")

    number = episode if episode is not None else _episode_number_from_filename(file_path)
    if number is None:
        raise ValueError(
            f"Could not determine episode number for {file_path.name}. "
            "Pass --episode N or name the file like 'episode_42.vtt'."
        )

    transcript = load_transcript(file_path)
    if not transcript.cues:
        raise ValueError(f"No transcript content parsed from {file_path}.")

    podcast.ensure_dirs()
    out_path = podcast.transcripts_dir / f"episode_{number}.vtt"
    vtt.write_file(transcript, out_path)

    catalog = Catalog.load(podcast.episodes_csv)
    catalog.upsert(
        Episode(
            number=number,
            title=catalog.get(number).title if catalog.has(number) else file_path.stem,
            state=STATE_DONE,
            transcript_source="manual",
        ),
        overwrite_state=True,
    )
    catalog.save()
    return number


def import_dir(podcast: PodcastConfig, dir_path: str | Path) -> list[int]:
    """Import every supported transcript file in a directory."""
    dir_path = Path(dir_path)
    if not dir_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {dir_path}")

    imported: list[int] = []
    for path in sorted(dir_path.iterdir()):
        if path.suffix.lower() not in TRANSCRIPT_EXTENSIONS:
            continue
        try:
            imported.append(import_file(podcast, path))
        except ValueError as exc:
            print(f"  skipped {path.name}: {exc}")
    return imported
