"""Dual-mode sync orchestrator: discover, import, count.

The same entry point handles both initial backfill (first run on an empty
catalog imports every published episode) and incremental sync (later runs pick
up only newly published episodes). See the plan's "Dual-Mode Import" section.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from podcast_words.catalog import (
    Catalog,
    Episode,
    STATE_DONE,
    STATE_ERROR,
    STATE_NO_TRANSCRIPT,
)
from podcast_words.config import PodcastConfig, SourceConfig
from podcast_words.models import Transcript
from podcast_words.transcripts import vtt

# Per-source request spacing to stay polite to public APIs.
_RATE_LIMIT_SECONDS = 0.5


def _discover_fn(source_type: str):
    if source_type == "podlove":
        from podcast_words.sources import podlove

        return podlove.discover
    if source_type == "whisper_rss":
        from podcast_words.sources import rss

        return rss.discover
    if source_type == "apple":
        from podcast_words.sources import apple_catalog

        return apple_catalog.discover
    return None


def _fetch_fn(source_type: str):
    if source_type == "podlove":
        from podcast_words.sources import podlove

        return podlove.fetch_transcript
    if source_type == "whisper_rss":
        from podcast_words.sources import whisper

        return whisper.fetch_transcript
    if source_type == "apple":
        from podcast_words.sources import apple

        return apple.fetch_transcript
    return None


def _merge_discovered(catalog: Catalog, discovered: list[Episode]) -> int:
    """Upsert discovered episodes; return the count of newly added ones."""
    new_count = 0
    for episode in discovered:
        existing = catalog.get(episode.number)
        if existing is None and catalog.find_by_source_id(episode.source_id) is None:
            new_count += 1
        catalog.upsert(episode)
    return new_count


def _save_transcript(podcast: PodcastConfig, episode: Episode, transcript: Transcript) -> None:
    podcast.transcripts_dir.mkdir(parents=True, exist_ok=True)
    out_path = podcast.transcripts_dir / f"episode_{episode.number}.vtt"
    vtt.write_file(transcript, out_path)


def _write_sync_state(podcast: PodcastConfig, episode_count: int) -> None:
    state = {
        "last_sync_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_episode_count": episode_count,
    }
    with open(podcast.sync_state_json, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def sync(
    podcast: PodcastConfig,
    *,
    source: SourceConfig | None = None,
    backfill: bool = False,
    force: bool = False,
    count: bool = True,
    rebuild: bool = False,
) -> dict:
    """Run discover -> import -> count for a podcast.

    backfill/force/incremental all funnel through the same code path; the only
    difference is which catalog episodes are considered "to fetch".
    """
    podcast.ensure_dirs()
    source = source or podcast.primary_source()
    if source is None:
        raise ValueError(f"Podcast '{podcast.id}' has no configured sources.")

    catalog = Catalog.load(podcast.episodes_csv)

    summary: dict = {
        "podcast": podcast.id,
        "source": source.type,
        "new_episodes": 0,
        "fetched": 0,
        "no_transcript": 0,
        "errors": 0,
    }

    # --- Discover ---
    discover = _discover_fn(source.type)
    if discover is not None:
        discovered = discover(podcast, source)
        summary["new_episodes"] = _merge_discovered(catalog, discovered)
        catalog.save()

    # --- Import ---
    fetch = _fetch_fn(source.type)
    if fetch is not None:
        targets = _import_targets(catalog, force=force, backfill=backfill)
        total = len(targets)
        for idx, episode in enumerate(targets, start=1):
            print(f"[{podcast.id}] transcript {idx}/{total} (episode {episode.number})")
            try:
                transcript = fetch(podcast, source, episode)
            except Exception as exc:  # network/tooling errors should not abort the run
                print(f"  error: {exc}")
                episode.state = STATE_ERROR
                summary["errors"] += 1
                catalog.save()
                continue

            if transcript is None:
                episode.state = STATE_NO_TRANSCRIPT
                summary["no_transcript"] += 1
            else:
                _save_transcript(podcast, episode, transcript)
                episode.state = STATE_DONE
                summary["fetched"] += 1
            catalog.save()
            time.sleep(_RATE_LIMIT_SECONDS)

    _write_sync_state(podcast, len(catalog))

    # --- Count ---
    if count:
        from podcast_words.pipeline.word_counter import count_words

        summary["count"] = count_words(podcast, rebuild=rebuild)

    return summary


def _import_targets(catalog: Catalog, *, force: bool, backfill: bool) -> list[Episode]:
    """Decide which episodes to fetch transcripts for.

    - force: every episode in the catalog
    - backfill: all pending / no_transcript / error episodes
    - incremental (default): same pending set, which on a first run is the whole
      freshly-discovered catalog and on later runs is just the new episodes
    """
    if force:
        return catalog.episodes()
    return catalog.pending()
