"""Shared episode numbering helpers for cross-source catalog alignment."""

from __future__ import annotations

import html
import re
from email.utils import parsedate_to_datetime

from podcast_words.config import PodcastConfig

_GENERIC_NUMBER_RE = re.compile(r"(\d+)")
_PODLOVE_PREFIX_RE = re.compile(r"(?:FS|MM)(\d+)", re.I)
_TITLE_PREFIX_RE = re.compile(r"^(?:FS|MM|UFO|UKW|LNP)\d+\s*[-:–—]*\s*", re.I)


def number_from_episode(
    podcast: PodcastConfig, *, title: str = "", link: str = ""
) -> int | None:
    """Extract a catalog episode number from title and/or link metadata."""
    title = html.unescape((title or "").strip())
    link = (link or "").strip()
    if podcast.episode_id.type == "sequential":
        return None
    if podcast.episode_id.type == "regex" and podcast.episode_id.pattern:
        for text in (link, title):
            if not text:
                continue
            match = re.search(podcast.episode_id.pattern, text, re.I)
            if match:
                return int(match.group(1))
        return None
    if not title:
        return None
    if podcast.episode_id.type == "podlove_number":
        match = _PODLOVE_PREFIX_RE.search(title)
        if match:
            return int(match.group(1))
        return None
    match = _GENERIC_NUMBER_RE.search(title)
    return int(match.group(1)) if match else None


def number_from_title(podcast: PodcastConfig, title: str) -> int | None:
    """Extract a catalog episode number from an episode title."""
    return number_from_episode(podcast, title=title)


def normalize_title(title: str) -> str:
    """Normalize a title for fuzzy cross-source matching."""
    text = html.unescape(title or "").strip()
    text = _TITLE_PREFIX_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).lower().strip()
    return text


def published_date_key(value: str) -> str | None:
    """Return YYYY-MM-DD for ISO or RSS-style publication timestamps."""
    if not value:
        return None
    value = value.strip()
    if len(value) >= 10 and value[4] == "-" and value[7] == "-":
        return value[:10]
    try:
        return parsedate_to_datetime(value).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError):
        return None


def catalog_number_for_remote(podcast: PodcastConfig, episode) -> int | None:
    """Map a remote episode row to the catalog episode number."""
    if podcast.episode_id.type == "sequential":
        return episode.number
    number = number_from_episode(
        podcast, title=episode.title, link=getattr(episode, "link", "") or ""
    )
    if number is not None:
        return number
    return None
