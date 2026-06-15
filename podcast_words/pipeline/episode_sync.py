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
    _is_audio_url,
)
from podcast_words.config import PodcastConfig, SourceConfig
from podcast_words.models import Transcript
from podcast_words.pipeline.remote_index import RemoteIndex, build_remote_index
from podcast_words.progress import iter_progress, write
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


def _merge_discovered(
    catalog: Catalog,
    discovered: list[Episode],
    *,
    source: SourceConfig | None = None,
    podcast: PodcastConfig | None = None,
) -> int:
    """Upsert discovered episodes; return the count of newly added ones."""
    from podcast_words.episode_number import catalog_number_for_remote

    from_podlove = source is not None and source.type == "podlove"
    new_count = 0
    for episode in discovered:
        merge_number = (
            catalog_number_for_remote(podcast, episode)
            if podcast is not None
            else episode.number
        )
        if merge_number is None:
            continue
        merge_episode = episode
        if merge_number != episode.number:
            merge_episode = Episode(**{**vars(episode), "number": merge_number})
        existing = catalog.get(merge_number)
        if existing is None and catalog.find_by_source_id(merge_episode.source_id) is None:
            new_count += 1
        catalog.upsert(merge_episode, new_from_podlove=from_podlove)
    return new_count


def _save_transcript(podcast: PodcastConfig, episode: Episode, transcript: Transcript) -> None:
    podcast.transcripts_dir.mkdir(parents=True, exist_ok=True)
    out_path = podcast.transcripts_dir / f"episode_{episode.number}.vtt"
    vtt.write_file(transcript, out_path)


def _write_sync_state(
    podcast: PodcastConfig,
    episode_count: int,
    *,
    last_episode: Episode | None = None,
) -> None:
    state: dict[str, object] = {
        "last_sync_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_episode_count": episode_count,
    }
    if last_episode is not None:
        state["last_episode_number"] = last_episode.number
        state["last_episode_title"] = last_episode.title or f"Episode {last_episode.number}"
    with open(podcast.sync_state_json, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _catalog_last_episode(catalog: Catalog) -> Episode | None:
    episodes = catalog.episodes()
    return episodes[-1] if episodes else None


def _discover_and_index(
    podcast: PodcastConfig,
    catalog: Catalog,
    source: SourceConfig,
) -> tuple[int, RemoteIndex]:
    """Discover from *source*, upsert the catalog, return (new_count, remote index)."""
    discover = _discover_fn(source.type)
    if discover is None:
        return 0, RemoteIndex()
    discovered = discover(podcast, source)
    index = build_remote_index(podcast, discovered)
    new_count = _merge_discovered(catalog, discovered, source=source, podcast=podcast)
    return new_count, index


def _refresh_podlove_links(podcast: PodcastConfig, catalog: Catalog) -> int:
    """Apply PodLove episode page links without changing transcript state."""
    source = podcast.source_of_type("podlove")
    if source is None:
        return 0
    discover = _discover_fn("podlove")
    if discover is None:
        return 0

    updated = 0
    for remote in discover(podcast, source):
        link = (remote.link or "").strip()
        if not link or _is_audio_url(link):
            continue
        existing = catalog.get(remote.number)
        if existing is None:
            catalog.upsert(remote, new_from_podlove=True)
            updated += 1
            continue
        if existing.link != link:
            existing.link = link
            updated += 1
    return updated


def _probe_episode(catalog_ep: Episode, remote: Episode | None) -> Episode:
    """Build a fetch probe with ids/urls from the remote source when needed."""
    if remote is None:
        return catalog_ep
    return Episode(
        number=catalog_ep.number,
        title=catalog_ep.title or remote.title,
        link=remote.link or catalog_ep.link,
        source_id=remote.source_id or catalog_ep.source_id,
    )


def _apply_transcript(
    podcast: PodcastConfig,
    episode: Episode,
    transcript: Transcript | None,
    source: SourceConfig,
) -> str:
    """Persist a fetched transcript and return outcome: fetched | no_transcript."""
    if transcript is None:
        episode.state = STATE_NO_TRANSCRIPT
        return "no_transcript"
    _save_transcript(podcast, episode, transcript)
    episode.state = STATE_DONE
    episode.transcript_source = source.type
    return "fetched"


def _run_replace(
    podcast: PodcastConfig,
    catalog: Catalog,
    source: SourceConfig,
    *,
    replace_if_from: tuple[str, ...] | None = None,
    limit: int | None = None,
) -> dict:
    """Replace existing transcripts by re-fetching from another configured source."""
    from podcast_words.sources.apple import AppleUnsupportedError

    result = {
        "replaced": 0,
        "no_transcript": 0,
        "skipped": 0,
        "errors": 0,
        "unsupported": False,
        "last_considered": None,
    }
    _, index = _discover_and_index(podcast, catalog, source)
    catalog.save()

    targets = _replace_targets(
        catalog, source_type=source.type, replace_if_from=replace_if_from
    )
    if limit is not None and limit >= 0:
        targets = targets[:limit]

    bar = iter_progress(
        targets,
        desc=f"[{podcast.id}] replace ({source.type})",
        unit="ep",
        total=len(targets),
    )
    for idx, episode in enumerate(bar, start=1):
        result["last_considered"] = episode
        remote = index.find(episode)
        if remote is None:
            result["skipped"] += 1
            continue
        probe = _probe_episode(episode, remote)
        if hasattr(bar, "set_postfix_str"):
            bar.set_postfix_str(f"#{episode.number}")
        try:
            fetch = _fetch_fn(source.type)
            if fetch is None:
                result["skipped"] += len(targets) - idx + 1
                break
            transcript = fetch(podcast, source, probe)
        except AppleUnsupportedError as exc:
            write(f"  {source.type} unavailable, stopping replace: {exc}")
            result["unsupported"] = True
            result["skipped"] += len(targets) - idx + 1
            break
        except Exception as exc:
            write(f"  episode {episode.number} error: {exc}")
            episode.state = STATE_ERROR
            result["errors"] += 1
            catalog.save()
            continue

        outcome = _apply_transcript(podcast, episode, transcript, source)
        if outcome == "fetched":
            result["replaced"] += 1
        else:
            result["no_transcript"] += 1
        catalog.save()
        time.sleep(_RATE_LIMIT_SECONDS)

    return result


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

    result = {"recovered": 0, "still_missing": 0, "unsupported": False, "last_considered": None}
    other_sources = [s for s in podcast.sources if s is not primary_source]
    remaining = [e for e in catalog.episodes() if e.state == STATE_NO_TRANSCRIPT]
    if not remaining or not other_sources:
        result["still_missing"] = len(remaining)
        return result

    for src in other_sources:
        fetch = _fetch_fn(src.type)
        if fetch is None:
            continue

        try:
            _, index = _discover_and_index(podcast, catalog, src)
        except Exception as exc:
            write(f"  fallback '{src.type}' discovery failed: {exc}")
            continue

        still: list[Episode] = []
        total = len(remaining)
        bar = iter_progress(
            remaining,
            desc=f"[{podcast.id}] fallback {src.type}",
            unit="ep",
            total=total,
        )
        for idx, episode in enumerate(bar, start=1):
            result["last_considered"] = episode
            remote = index.find(episode)
            if not remote or not remote.source_id:
                still.append(episode)
                continue
            probe = _probe_episode(episode, remote)
            if hasattr(bar, "set_postfix_str"):
                bar.set_postfix_str(f"#{episode.number}")
            try:
                transcript = fetch(podcast, src, probe)
            except AppleUnsupportedError as exc:
                write(f"  {src.type} unavailable, stopping fallback: {exc}")
                result["unsupported"] = True
                still.extend(remaining[idx - 1:])
                break
            except Exception as exc:
                write(f"  error: {exc}")
                still.append(episode)
                continue

            if transcript is None:
                still.append(episode)
                continue

            _apply_transcript(podcast, episode, transcript, src)
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
    replace_from: SourceConfig | None = None,
    replace_if_from: tuple[str, ...] | None = None,
    limit: int | None = None,
) -> dict:
    """Run discover -> import -> count for a podcast.

    backfill/force/incremental all funnel through the same code path; the only
    difference is which catalog episodes are considered "to fetch".
    """
    podcast.ensure_dirs()
    if replace_from is not None and source is not None and source is not replace_from:
        raise ValueError(
            "Use either --source or --replace-from, not both with different sources."
        )
    source = replace_from or source or podcast.primary_source()
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

    if replace_from is not None:
        summary["replace"] = _run_replace(
            podcast,
            catalog,
            replace_from,
            replace_if_from=replace_if_from,
            limit=limit,
        )
        last_considered = summary["replace"].get("last_considered") or _catalog_last_episode(
            catalog
        )
        _write_sync_state(podcast, len(catalog), last_episode=last_considered)
        if count:
            from podcast_words.pipeline.word_counter import count_words

            summary["count"] = count_words(podcast, rebuild=rebuild)
        summary["podlove_links"] = _refresh_podlove_links(podcast, catalog)
        catalog.save()
        return summary

    # --- Discover ---
    last_considered: Episode | None = None
    discover = _discover_fn(source.type)
    if discover is not None:
        discovered = discover(podcast, source)
        summary["new_episodes"] = _merge_discovered(
            catalog, discovered, source=source, podcast=podcast
        )
        if discovered:
            last_considered = max(discovered, key=lambda ep: ep.number)
        catalog.save()

    # --- Import ---
    fetch = _fetch_fn(source.type)
    if fetch is not None:
        targets = _import_targets(catalog, force=force, backfill=backfill)
        if limit is not None and limit >= 0:
            targets = targets[:limit]
        total = len(targets)
        bar = iter_progress(
            targets,
            desc=f"[{podcast.id}] transcripts ({source.type})",
            unit="ep",
            total=total,
        )
        for episode in bar:
            last_considered = episode
            if hasattr(bar, "set_postfix_str"):
                bar.set_postfix_str(f"#{episode.number}")
            try:
                transcript = fetch(podcast, source, episode)
            except Exception as exc:  # network/tooling errors should not abort the run
                write(f"  episode {episode.number} error: {exc}")
                episode.state = STATE_ERROR
                summary["errors"] += 1
                catalog.save()
                continue

            outcome = _apply_transcript(podcast, episode, transcript, source)
            if outcome == "fetched":
                summary["fetched"] += 1
            else:
                summary["no_transcript"] += 1
            catalog.save()
            time.sleep(_RATE_LIMIT_SECONDS)

    # --- Fallback: recover no_transcript episodes from secondary sources ---
    if fallback:
        summary["fallback"] = _run_fallback(podcast, catalog, primary_source=source)
        fallback_last = summary["fallback"].get("last_considered")
        if fallback_last is not None:
            last_considered = fallback_last
        catalog.save()

    summary["podlove_links"] = _refresh_podlove_links(podcast, catalog)
    catalog.save()
    if last_considered is None:
        last_considered = _catalog_last_episode(catalog)
    _write_sync_state(podcast, len(catalog), last_episode=last_considered)

    # --- Count ---
    if count:
        from podcast_words.pipeline.word_counter import count_words

        summary["count"] = count_words(podcast, rebuild=rebuild)

    return summary


def _replace_targets(
    catalog: Catalog,
    *,
    source_type: str,
    replace_if_from: tuple[str, ...] | None = None,
) -> list[Episode]:
    """Episodes with an existing transcript that should be overwritten."""
    targets: list[Episode] = []
    for ep in catalog.episodes():
        if ep.state != STATE_DONE:
            continue
        if ep.transcript_source == source_type:
            continue
        if replace_if_from and ep.transcript_source not in replace_if_from:
            continue
        targets.append(ep)
    return targets


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
