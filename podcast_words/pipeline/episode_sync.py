"""Dual-mode sync orchestrator: discover, import, count.

The same entry point handles both initial backfill (first run on an empty
catalog imports every published episode) and incremental sync (later runs pick
up only newly published episodes). See the plan's "Dual-Mode Import" section.
"""

from __future__ import annotations

import json
import re
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
_GENERIC_NUMBER_RE = re.compile(r"(\d+)")


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


def _number_from_title(podcast: PodcastConfig, title: str) -> int | None:
    """Extract an episode number from a title for cross-source matching.

    Uses the podcast's regex pattern when configured, else the first integer in
    the title (e.g. 'FS308 Casual Punk' -> 308). This lets a fallback source
    (Apple) be aligned to catalog episodes numbered by the primary source.
    """
    if podcast.episode_id.type == "regex" and podcast.episode_id.pattern:
        match = re.search(podcast.episode_id.pattern, title)
        return int(match.group(1)) if match else None
    match = _GENERIC_NUMBER_RE.search(title)
    return int(match.group(1)) if match else None


def _run_fallback(
    podcast: PodcastConfig,
    catalog: Catalog,
    *,
    primary_source: SourceConfig,
) -> dict:
    """Recover transcripts for no_transcript episodes from secondary sources.

    For each non-primary source configured on the podcast, discover its episodes,
    match them to the catalog by episode number, and try fetching a transcript
    for episodes the primary source could not provide.
    """
    from podcast_words.sources.apple import AppleUnsupportedError

    result = {"recovered": 0, "still_missing": 0, "unsupported": False}
    other_sources = [s for s in podcast.sources if s is not primary_source]
    remaining = [e for e in catalog.episodes() if e.state == STATE_NO_TRANSCRIPT]
    if not remaining or not other_sources:
        result["still_missing"] = len(remaining)
        return result

    for src in other_sources:
        discover = _discover_fn(src.type)
        fetch = _fetch_fn(src.type)
        if discover is None or fetch is None:
            continue

        try:
            discovered = discover(podcast, src)
        except Exception as exc:
            print(f"  fallback '{src.type}' discovery failed: {exc}")
            continue

        index: dict[int, str] = {}
        for ep in discovered:
            number = _number_from_title(podcast, ep.title)
            if number is not None and ep.source_id:
                index.setdefault(number, ep.source_id)

        still: list[Episode] = []
        total = len(remaining)
        for idx, episode in enumerate(remaining, start=1):
            source_id = index.get(episode.number)
            if not source_id:
                still.append(episode)
                continue
            probe = Episode(
                number=episode.number, title=episode.title, source_id=source_id
            )
            print(
                f"[{podcast.id}] fallback {src.type} {idx}/{total} (episode {episode.number})"
            )
            try:
                transcript = fetch(podcast, src, probe)
            except AppleUnsupportedError as exc:
                print(f"  {src.type} unavailable, stopping fallback: {exc}")
                result["unsupported"] = True
                still.extend(remaining[idx - 1:])
                break
            except Exception as exc:
                print(f"  error: {exc}")
                still.append(episode)
                continue

            if transcript is None:
                still.append(episode)
                continue

            _save_transcript(podcast, episode, transcript)
            episode.state = STATE_DONE
            episode.transcript_source = src.type
            result["recovered"] += 1
            catalog.save()
            time.sleep(_RATE_LIMIT_SECONDS)

        remaining = still
        if result["unsupported"]:
            break

    result["still_missing"] = len(remaining)
    return result


def sync(
    podcast: PodcastConfig,
    *,
    source: SourceConfig | None = None,
    backfill: bool = False,
    force: bool = False,
    count: bool = True,
    rebuild: bool = False,
    fallback: bool = False,
    limit: int | None = None,
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
        if limit is not None and limit >= 0:
            targets = targets[:limit]
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

    # --- Fallback: recover no_transcript episodes from secondary sources ---
    if fallback:
        summary["fallback"] = _run_fallback(podcast, catalog, primary_source=source)
        catalog.save()

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
