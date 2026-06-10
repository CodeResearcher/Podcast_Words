"""One-time migration of the original PUFO data into the multi-podcast layout.

Moves the root word_counts.csv / episode_stats.json and the legacy
episode_processor data into data/pufo/, upgrades episodes.csv to the new catalog
schema, and converts the legacy Whisper .txt transcripts to canonical VTT.

Run from the project root:  python scripts/migrate_pufo.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from podcast_words.catalog import Catalog, Episode, STATE_DONE, STATE_PENDING  # noqa: E402
from podcast_words.config import get_podcast  # noqa: E402
from podcast_words.transcripts import vtt  # noqa: E402
from podcast_words.transcripts.whisper_legacy import parse_file as parse_legacy  # noqa: E402

LEGACY_TEXT_DIR = PROJECT_ROOT / "episode_processor" / "text"
LEGACY_EPISODES_CSV = PROJECT_ROOT / "episode_processor" / "episodes.csv"
ROOT_WORD_COUNTS = PROJECT_ROOT / "word_counts.csv"
ROOT_STATS = PROJECT_ROOT / "episode_stats.json"


def _copy_if_exists(src: Path, dest: Path) -> None:
    if src.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        print(f"  copied {src.name} -> {dest}")
    else:
        print(f"  skipped (missing): {src}")


def _transcript_numbers(transcripts_dir: Path) -> set[int]:
    numbers: set[int] = set()
    for path in transcripts_dir.glob("episode_*.vtt"):
        try:
            numbers.add(int(path.stem.split("_")[1]))
        except (IndexError, ValueError):
            continue
    return numbers


def main() -> int:
    podcast = get_podcast("pufo")
    podcast.ensure_dirs()
    print(f"Migrating PUFO data into {podcast.data_dir}")

    print("\n[1/4] Copying generated data files")
    _copy_if_exists(ROOT_WORD_COUNTS, podcast.word_counts_csv)
    _copy_if_exists(ROOT_STATS, podcast.episode_stats_json)

    print("\n[2/4] Converting legacy Whisper transcripts to VTT")
    converted = 0
    if LEGACY_TEXT_DIR.exists():
        for txt_path in sorted(LEGACY_TEXT_DIR.glob("episode_*.txt")):
            try:
                number = int(txt_path.stem.split("_")[1])
            except (IndexError, ValueError):
                continue
            out_path = podcast.transcripts_dir / f"episode_{number}.vtt"
            if out_path.exists():
                continue
            try:
                transcript = parse_legacy(txt_path)
            except Exception as exc:
                print(f"  failed {txt_path.name}: {exc}")
                continue
            vtt.write_file(transcript, out_path)
            converted += 1
    print(f"  converted {converted} transcripts")

    print("\n[3/4] Building catalog (episodes.csv)")
    transcript_numbers = _transcript_numbers(podcast.transcripts_dir)
    old_catalog = Catalog.load(LEGACY_EPISODES_CSV) if LEGACY_EPISODES_CSV.exists() else None

    new_catalog = Catalog([], podcast.episodes_csv)
    source_rows = old_catalog.episodes() if old_catalog else []
    for ep in source_rows:
        has_transcript = ep.number in transcript_numbers
        new_catalog.upsert(
            Episode(
                number=ep.number,
                title=ep.title,
                link=ep.link,
                state=STATE_DONE if has_transcript else (ep.state or STATE_PENDING),
                transcript_source="whisper" if has_transcript else "",
            )
        )
    # Include any transcript not present in the old CSV.
    for number in transcript_numbers:
        if not new_catalog.has(number):
            new_catalog.upsert(
                Episode(number=number, state=STATE_DONE, transcript_source="whisper")
            )
    new_catalog.save()
    print(f"  catalog rows: {len(new_catalog)}")

    print("\n[4/4] Parity check")
    done = sum(1 for ep in new_catalog if ep.state == STATE_DONE)
    print(f"  catalog episodes: {len(new_catalog)}")
    print(f"  done (with transcript): {done}")
    print(f"  vtt transcript files: {len(transcript_numbers)}")
    print("\nMigration complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
