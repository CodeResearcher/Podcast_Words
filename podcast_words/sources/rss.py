"""RSS feed parsing for the whisper_rss source.

Discovers episodes from a podcast RSS feed. The actual transcription is handled
by whisper.py; this module only builds the episode catalog (number, title,
enclosure URL) so the sync orchestrator knows what audio to transcribe.
"""

from __future__ import annotations

import re
from xml.etree.ElementTree import ParseError

import requests
from bs4 import BeautifulSoup
from defusedxml.ElementTree import fromstring as _safe_fromstring
from defusedxml.common import DefusedXmlException

from podcast_words.catalog import Episode, STATE_PENDING
from podcast_words.config import PodcastConfig, SourceConfig

_TIMEOUT = 30
_NUMBER_RE = re.compile(r"(\d+)")


def _reject_unsafe_xml(content: bytes) -> None:
    """Refuse feeds containing DTDs/entity declarations before lenient parsing.

    BeautifulSoup's XML backend is permissive and may resolve entities. We run
    the raw bytes through defusedxml first purely as a gate: a DefusedXmlException
    means the feed tried something unsafe (XXE / billion-laughs) and we abort.
    A plain ParseError is ignored so BeautifulSoup can still recover real-world
    feeds with minor markup issues.
    """
    try:
        _safe_fromstring(content)
    except DefusedXmlException as exc:
        raise ValueError(
            "RSS feed contains a DTD or entity declarations; refusing to parse."
        ) from exc
    except ParseError:
        pass


def _assign_number(podcast: PodcastConfig, title: str, fallback: int) -> int | None:
    if podcast.episode_id.type == "regex" and podcast.episode_id.pattern:
        match = re.search(podcast.episode_id.pattern, title)
        return int(match.group(1)) if match else None
    match = _NUMBER_RE.search(title)
    return int(match.group(1)) if match else fallback


def discover(podcast: PodcastConfig, source: SourceConfig) -> list[Episode]:
    resp = requests.get(source.feed_url, timeout=_TIMEOUT)
    resp.raise_for_status()
    _reject_unsafe_xml(resp.content)
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
