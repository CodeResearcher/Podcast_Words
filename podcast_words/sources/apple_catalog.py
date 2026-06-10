"""Apple Podcasts episode discovery via the public iTunes Lookup API.

Given a show Podcast ID, returns all published episodes. No authentication is
required for discovery; fetching the actual transcript (apple.py) does require
macOS and the Apple Podcasts app.
"""

from __future__ import annotations

import re

import requests

from podcast_words.catalog import Episode, STATE_PENDING
from podcast_words.config import PodcastConfig, SourceConfig

_LOOKUP_URL = "https://itunes.apple.com/lookup"
_TIMEOUT = 30
_NUMBER_RE = re.compile(r"(\d+)")


def _assign_number(podcast: PodcastConfig, item: dict, sequential_index: int) -> int:
    if podcast.episode_id.type == "regex" and podcast.episode_id.pattern:
        match = re.search(podcast.episode_id.pattern, str(item.get("trackName", "")))
        if match:
            return int(match.group(1))
    return sequential_index


def discover(podcast: PodcastConfig, source: SourceConfig) -> list[Episode]:
    params = {
        "id": source.podcast_id,
        "country": source.country,
        "media": "podcast",
        "entity": "podcastEpisode",
        "limit": 200,
    }
    resp = requests.get(_LOOKUP_URL, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    results = resp.json().get("results", [])

    # First result is the show; the rest are episodes.
    raw_episodes = [r for r in results if r.get("wrapperType") == "podcastEpisode"]
    # Oldest first, so sequential numbering is stable as new episodes appear.
    raw_episodes.sort(key=lambda r: r.get("releaseDate", ""))

    episodes: list[Episode] = []
    for idx, item in enumerate(raw_episodes, start=1):
        number = _assign_number(podcast, item, idx)
        episodes.append(
            Episode(
                number=number,
                title=str(item.get("trackName", "")).strip(),
                link=str(item.get("episodeUrl", "") or item.get("trackViewUrl", "")),
                source_id=str(item.get("trackId", "")),
                published_at=str(item.get("releaseDate", "")),
                state=STATE_PENDING,
                transcript_source="apple",
            )
        )
    return episodes
