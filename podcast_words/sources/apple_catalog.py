"""Apple Podcasts episode discovery via iTunes Lookup and amp-api catalog.

Lookup is public and sufficient for shows with at most 200 episodes. Larger
shows fall back to paginated amp-api catalog requests, which require macOS 15.5+
and the FetchTranscript helper (same bearer token as transcript download).
"""

from __future__ import annotations

import warnings

import requests

from podcast_words.catalog import Episode, STATE_PENDING
from podcast_words.config import PodcastConfig, SourceConfig
from podcast_words.sources.apple_auth import AppleUnsupportedError, get_bearer_token

_LOOKUP_URL = "https://itunes.apple.com/lookup"
_AMP_EPISODES_URL = (
    "https://amp-api.podcasts.apple.com/v1/catalog/{storefront}/podcasts/{podcast_id}/episodes"
)
_TIMEOUT = 30
_LOOKUP_LIMIT = 200
_AMP_PAGE_SIZE = 100


def _storefront(country: str) -> str:
    return (country or "US").lower()


def _assign_number(
    podcast: PodcastConfig, title: str, sequential_index: int, *, link: str = ""
) -> int:
    if podcast.episode_id.type == "sequential":
        return sequential_index
    from podcast_words.episode_number import number_from_episode

    extracted = number_from_episode(podcast, title=title, link=link)
    if extracted is not None:
        return extracted
    return sequential_index


def _episode_from_lookup(podcast: PodcastConfig, item: dict, sequential_index: int) -> Episode:
    title = str(item.get("trackName", "")).strip()
    link = str(item.get("episodeUrl", "") or item.get("trackViewUrl", ""))
    return Episode(
        number=_assign_number(podcast, title, sequential_index, link=link),
        title=title,
        link=link,
        source_id=str(item.get("trackId", "")),
        published_at=str(item.get("releaseDate", "")),
        state=STATE_PENDING,
        transcript_source="apple",
    )


def _episode_from_amp(podcast: PodcastConfig, item: dict, sequential_index: int) -> Episode:
    attrs = item.get("attributes") or {}
    title = str(attrs.get("name", "")).strip()
    link = str(attrs.get("url") or attrs.get("websiteUrl") or attrs.get("assetUrl") or "")
    return Episode(
        number=_assign_number(podcast, title, sequential_index, link=link),
        title=title,
        link=link,
        source_id=str(item.get("id", "")),
        published_at=str(attrs.get("releaseDateTime", "")),
        state=STATE_PENDING,
        transcript_source="apple",
    )


def _fetch_lookup(source: SourceConfig) -> tuple[int | None, list[dict]]:
    params = {
        "id": source.podcast_id,
        "country": source.country,
        "media": "podcast",
        "entity": "podcastEpisode",
        "limit": _LOOKUP_LIMIT,
    }
    resp = requests.get(_LOOKUP_URL, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    results = resp.json().get("results", [])

    track_count: int | None = None
    for item in results:
        if item.get("wrapperType") == "track" and item.get("trackCount") is not None:
            track_count = int(item["trackCount"])
            break

    raw_episodes = [r for r in results if r.get("wrapperType") == "podcastEpisode"]
    return track_count, raw_episodes


def _discover_via_lookup(
    podcast: PodcastConfig, raw_episodes: list[dict]
) -> list[Episode]:
    raw_episodes.sort(key=lambda r: r.get("releaseDate", ""))
    return [
        _episode_from_lookup(podcast, item, idx)
        for idx, item in enumerate(raw_episodes, start=1)
    ]


def _discover_via_amp_api(podcast: PodcastConfig, source: SourceConfig) -> list[Episode]:
    bearer = get_bearer_token()
    storefront = _storefront(source.country)
    url = _AMP_EPISODES_URL.format(
        storefront=storefront,
        podcast_id=source.podcast_id,
    )
    headers = {"Authorization": f"Bearer {bearer}"}

    raw_episodes: list[dict] = []
    offset = 0
    while True:
        resp = requests.get(
            url,
            headers=headers,
            params={"offset": offset, "limit": _AMP_PAGE_SIZE},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
        page = payload.get("data") or []
        raw_episodes.extend(
            item
            for item in page
            if (item.get("attributes") or {}).get("mediaKind") == "audio"
        )
        if not payload.get("next") or not page:
            break
        offset += len(page)

    raw_episodes.sort(key=lambda r: (r.get("attributes") or {}).get("releaseDateTime", ""))
    return [
        _episode_from_amp(podcast, item, idx)
        for idx, item in enumerate(raw_episodes, start=1)
    ]


def discover(podcast: PodcastConfig, source: SourceConfig) -> list[Episode]:
    track_count, raw_lookup = _fetch_lookup(source)

    if track_count is not None and track_count > len(raw_lookup):
        try:
            return _discover_via_amp_api(podcast, source)
        except AppleUnsupportedError as exc:
            warnings.warn(
                f"Apple catalog for podcast {source.podcast_id!r} has "
                f"{track_count} episodes but Lookup returned only "
                f"{len(raw_lookup)}; amp-api discovery unavailable ({exc}). "
                "Install/build FetchTranscript on macOS 15.5+ for full coverage.",
                stacklevel=2,
            )

    return _discover_via_lookup(podcast, raw_lookup)
