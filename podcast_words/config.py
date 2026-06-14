"""Load and validate the multi-podcast configuration from config/podcasts.yaml."""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "podcasts.yaml"
DATA_ROOT = PROJECT_ROOT / "data"

# spaCy model per language. Episodes are lemmatized with the model for their podcast.
SPACY_MODELS = {
    "de": "de_core_news_lg",
    "en": "en_core_web_lg",
}

VALID_EPISODE_ID_TYPES = {"regex", "podlove_number", "sequential"}
VALID_SOURCE_TYPES = {"whisper_rss", "podlove", "apple", "manual"}

# Loopback/reserved hosts where cleartext HTTP is fine (local dev / tests).
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_TEST_TLDS = (".test", ".local", ".localhost", ".example", ".invalid")


def _warn_if_insecure(url: str | None, field_name: str) -> None:
    """Warn when a configured endpoint uses cleartext HTTP (MITM risk)."""
    if not url:
        return
    parsed = urlparse(url)
    if parsed.scheme and parsed.scheme != "https":
        host = (parsed.hostname or "").lower()
        if host in _LOCAL_HOSTS or host.endswith(_TEST_TLDS):
            return
        warnings.warn(
            f"{field_name} uses insecure scheme '{parsed.scheme}://'. Prefer https:// "
            "to prevent transcript/feed tampering in transit.",
            stacklevel=3,
        )


@dataclass
class EpisodeIdConfig:
    type: str = "sequential"
    pattern: str | None = None

    def __post_init__(self) -> None:
        if self.type not in VALID_EPISODE_ID_TYPES:
            raise ValueError(
                f"Invalid episode_id.type '{self.type}'. "
                f"Expected one of {sorted(VALID_EPISODE_ID_TYPES)}."
            )
        if self.type == "regex" and not self.pattern:
            raise ValueError("episode_id.type 'regex' requires a 'pattern'.")


@dataclass
class SourceConfig:
    type: str
    # whisper_rss
    feed_url: str | None = None
    # podlove
    api_base: str | None = None
    # apple
    podcast_id: str | None = None
    country: str = "US"

    def __post_init__(self) -> None:
        if self.type not in VALID_SOURCE_TYPES:
            raise ValueError(
                f"Invalid source type '{self.type}'. "
                f"Expected one of {sorted(VALID_SOURCE_TYPES)}."
            )
        if self.type == "whisper_rss" and not self.feed_url:
            raise ValueError("source 'whisper_rss' requires 'feed_url'.")
        if self.type == "podlove" and not self.api_base:
            raise ValueError("source 'podlove' requires 'api_base'.")
        if self.type == "apple" and not self.podcast_id:
            raise ValueError("source 'apple' requires 'podcast_id'.")
        _warn_if_insecure(self.feed_url, "feed_url")
        _warn_if_insecure(self.api_base, "api_base")


@dataclass
class PodcastConfig:
    id: str
    name: str
    language: str = "de"
    episode_id: EpisodeIdConfig = field(default_factory=EpisodeIdConfig)
    sources: list[SourceConfig] = field(default_factory=list)
    search_words: list[str] = field(default_factory=list)
    order: int | None = None
    _yaml_index: int = 0

    @property
    def data_dir(self) -> Path:
        return DATA_ROOT / self.id

    @property
    def transcripts_dir(self) -> Path:
        return self.data_dir / "transcripts"

    @property
    def episodes_csv(self) -> Path:
        return self.data_dir / "episodes.csv"

    @property
    def word_counts_csv(self) -> Path:
        return self.data_dir / "word_counts.csv"

    @property
    def episode_stats_json(self) -> Path:
        return self.data_dir / "episode_stats.json"

    @property
    def sync_state_json(self) -> Path:
        return self.data_dir / "sync_state.json"

    @property
    def spacy_model(self) -> str:
        if self.language not in SPACY_MODELS:
            raise ValueError(
                f"No spaCy model configured for language '{self.language}'. "
                f"Known: {sorted(SPACY_MODELS)}."
            )
        return SPACY_MODELS[self.language]

    def primary_source(self) -> SourceConfig | None:
        return self.sources[0] if self.sources else None

    def source_of_type(self, source_type: str) -> SourceConfig | None:
        for source in self.sources:
            if source.type == source_type:
                return source
        return None

    def ensure_dirs(self) -> None:
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)

    def has_data(self) -> bool:
        return self.word_counts_csv.exists() and self.episode_stats_json.exists()


def _parse_podcast(podcast_id: str, raw: dict, *, yaml_index: int) -> PodcastConfig:
    if "name" not in raw:
        raise ValueError(f"Podcast '{podcast_id}' is missing required field 'name'.")

    episode_id_raw = raw.get("episode_id", {}) or {}
    episode_id = EpisodeIdConfig(
        type=episode_id_raw.get("type", "sequential"),
        pattern=episode_id_raw.get("pattern"),
    )

    sources = [SourceConfig(**src) for src in raw.get("sources", [])]

    defaults = raw.get("defaults", {}) or {}
    order = raw.get("order")
    if order is not None:
        order = int(order)

    return PodcastConfig(
        id=podcast_id,
        name=raw["name"],
        language=raw.get("language", "de"),
        episode_id=episode_id,
        sources=sources,
        search_words=list(defaults.get("search_words", [])),
        order=order,
        _yaml_index=yaml_index,
    )


def _sort_key(podcast: PodcastConfig) -> tuple[int, int, str]:
    """Sort podcasts for UI lists: explicit order, then yaml order, then id."""
    order = podcast.order if podcast.order is not None else 1_000_000 + podcast._yaml_index
    return order, podcast._yaml_index, podcast.id


def sorted_podcasts(config: dict[str, PodcastConfig]) -> list[PodcastConfig]:
    """Return podcasts in configured display order."""
    return sorted(config.values(), key=_sort_key)


def sorted_podcast_ids(config: dict[str, PodcastConfig]) -> list[str]:
    """Return podcast ids in configured display order."""
    return [podcast.id for podcast in sorted_podcasts(config)]


def load_config(path: str | os.PathLike | None = None) -> dict[str, PodcastConfig]:
    """Load all podcast configs keyed by podcast id."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    podcasts_raw = raw.get("podcasts", {})
    if not podcasts_raw:
        raise ValueError(f"No podcasts defined in {config_path}.")

    return {
        pid: _parse_podcast(pid, body, yaml_index=index)
        for index, (pid, body) in enumerate(podcasts_raw.items())
    }


def get_podcast(podcast_id: str, path: str | os.PathLike | None = None) -> PodcastConfig:
    """Load a single podcast config by id."""
    config = load_config(path)
    if podcast_id not in config:
        raise KeyError(
            f"Podcast '{podcast_id}' not found. Available: {sorted(config)}."
        )
    return config[podcast_id]
