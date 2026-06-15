"""Index of remote (discovered) episodes for cross-source fallback lookup."""

from __future__ import annotations

from dataclasses import dataclass, field

from podcast_words.catalog import Episode
from podcast_words.config import PodcastConfig
from podcast_words.episode_number import (
    catalog_number_for_remote,
    normalize_title,
    published_date_key,
)


@dataclass
class RemoteIndex:
    by_number: dict[int, Episode] = field(default_factory=dict)
    by_title: dict[str, Episode] = field(default_factory=dict)
    by_date: dict[str, Episode] = field(default_factory=dict)

    def find(self, catalog_ep: Episode) -> Episode | None:
        if catalog_ep.number in self.by_number:
            return self.by_number[catalog_ep.number]
        title_key = normalize_title(catalog_ep.title)
        if title_key and title_key in self.by_title:
            return self.by_title[title_key]
        date_key = published_date_key(catalog_ep.published_at)
        if date_key and date_key in self.by_date:
            return self.by_date[date_key]
        return None


def build_remote_index(podcast: PodcastConfig, discovered: list[Episode]) -> RemoteIndex:
    index = RemoteIndex()
    for ep in discovered:
        number = catalog_number_for_remote(podcast, ep)
        if number is not None:
            index.by_number.setdefault(number, ep)
        title_key = normalize_title(ep.title)
        if title_key:
            index.by_title.setdefault(title_key, ep)
        date_key = published_date_key(ep.published_at)
        if date_key:
            index.by_date.setdefault(date_key, ep)
    return index
