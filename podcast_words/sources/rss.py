"""RSS feed parsing for the whisper_rss source.

Discovers episodes from a podcast RSS feed. The actual transcription is handled
by whisper.py; this module only builds the episode catalog (number, title,
enclosure URL) so the sync orchestrator knows what audio to transcribe.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from podcast_words.catalog import Episode, STATE_PENDING
from podcast_words.config import PodcastConfig, SourceConfig

_TIMEOUT = 30
_NUMBER_RE = re.compile(r"(\d+)")


def _assign_number(podcast: PodcastConfig, title: str, fallback: int) -> int | None:
    if podcast.episode_id.type == "regex" and podcast.episode_id.pattern:
        match = re.search(podcast.episode_id.pattern, title)
        return int(match.group(1)) if match else None
    match = _NUMBER_RE.search(title)
    return int(match.group(1)) if match else fallback


def discover(podcast: PodcastConfig, source: SourceConfig) -> list[Episode]:
    resp = requests.get(source.feed_url, timeout=_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "xml")

    episodes: list[Episode] = []
    for idx, item in enumerate(soup.find_all("item"), start=1):
        title_tag = item.find("title")
        title = title_tag.text.strip() if title_tag else ""
        enclosure = item.find("enclosure")
        media_url = enclosure["url"] if enclosure and enclosure.has_attr("url") else ""
        pub_tag = item.find("pubDate")
        published_at = pub_tag.text.strip() if pub_tag else ""

        number = _assign_number(podcast, title, fallback=idx)
        if number is None:
            continue

        episodes.append(
            Episode(
                number=number,
                title=title,
                link=media_url,
                published_at=published_at,
                state=STATE_PENDING,
                transcript_source="whisper",
            )
        )

    episodes.sort(key=lambda e: e.number)
    return episodes
