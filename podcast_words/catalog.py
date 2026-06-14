"""Episode catalog: the per-podcast episodes.csv is the source of truth.

The catalog lists every known episode for a podcast and tracks the state of its
transcript. Source adapters discover episodes and upsert them here; the sync
orchestrator reads the catalog to decide what to fetch and count.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

CATALOG_FIELDS = [
    "number",
    "title",
    "link",
    "source_id",
    "published_at",
    "state",
    "transcript_source",
    "discovered_at",
]

# Episode transcript states.
STATE_DONE = "done"
STATE_PENDING = "pending"
STATE_NO_TRANSCRIPT = "no_transcript"
STATE_SKIP = "skip"
STATE_ERROR = "error"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Leading characters a spreadsheet may interpret as a formula (CSV injection).
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value):
    """Neutralize spreadsheet formula injection in string cells.

    Episode titles/links come from remote feeds; a value like ``=HYPERLINK(...)``
    would execute when the CSV is opened in Excel/Sheets. Prefix such values with
    a single quote so they are treated as literal text. Non-strings pass through.
    """
    if isinstance(value, str) and value.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


@dataclass
class Episode:
    number: int
    title: str = ""
    link: str = ""
    source_id: str = ""
    published_at: str = ""
    state: str = STATE_PENDING
    transcript_source: str = ""
    discovered_at: str = ""

    def to_row(self) -> dict:
        return {k: _csv_safe("" if v is None else v) for k, v in asdict(self).items()}


def _coerce_number(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


class Catalog:
    """In-memory episode catalog backed by episodes.csv."""

    def __init__(self, episodes: list[Episode], path: Path):
        self._by_number: dict[int, Episode] = {ep.number: ep for ep in episodes}
        self.path = path

    @classmethod
    def load(cls, path: str | Path) -> "Catalog":
        path = Path(path)
        episodes: list[Episode] = []
        if path.exists():
            with open(path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    episodes.append(_episode_from_row(row))
        return cls(episodes, path)

    def __len__(self) -> int:
        return len(self._by_number)

    def __iter__(self):
        return iter(self.episodes())

    def episodes(self) -> list[Episode]:
        return [self._by_number[n] for n in sorted(self._by_number)]

    def get(self, number: int) -> Episode | None:
        return self._by_number.get(number)

    def has(self, number: int) -> bool:
        return number in self._by_number

    def find_by_source_id(self, source_id: str) -> Episode | None:
        if not source_id:
            return None
        for ep in self._by_number.values():
            if ep.source_id and ep.source_id == source_id:
                return ep
        return None

    def upsert(self, episode: Episode, *, overwrite_state: bool = False) -> Episode:
        """Insert a new episode or update an existing one.

        Existing rows keep their state unless overwrite_state is True, so a
        re-discovery of an already-processed episode does not reset it to pending.
        """
        existing = self._by_number.get(episode.number)
        if existing is None:
            stored = Episode(**vars(episode))
            if not stored.discovered_at:
                stored.discovered_at = _now_iso()
            self._by_number[stored.number] = stored
            return stored

        # Merge metadata, preserve transcript state unless told otherwise.
        existing.title = episode.title or existing.title
        existing.link = episode.link or existing.link
        existing.source_id = episode.source_id or existing.source_id
        existing.published_at = episode.published_at or existing.published_at
        if overwrite_state:
            existing.state = episode.state
            existing.transcript_source = episode.transcript_source
        return existing

    def pending(self) -> list[Episode]:
        """Episodes that still need a transcript fetch."""
        return [
            ep
            for ep in self.episodes()
            if ep.state in (STATE_PENDING, STATE_NO_TRANSCRIPT, STATE_ERROR)
        ]

    def state_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for ep in self._by_number.values():
            counts[ep.state] = counts.get(ep.state, 0) + 1
        return counts

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CATALOG_FIELDS)
            writer.writeheader()
            for ep in self.episodes():
                writer.writerow(ep.to_row())


def _episode_from_row(row: dict) -> Episode:
    return Episode(
        number=_coerce_number(row.get("number")),
        title=(row.get("title") or "").strip(),
        link=(row.get("link") or "").strip(),
        source_id=(row.get("source_id") or "").strip(),
        published_at=(row.get("published_at") or "").strip(),
        state=(row.get("state") or STATE_PENDING).strip() or STATE_PENDING,
        transcript_source=(row.get("transcript_source") or "").strip(),
        discovered_at=(row.get("discovered_at") or "").strip(),
    )
