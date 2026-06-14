"""PodLove Publisher API v2 source.

Discovers all published episodes and fetches their WebVTT transcripts.
Docs: https://docs.podlove.org/podlove-publisher/api
"""

from __future__ import annotations

import re

import requests

from podcast_words.catalog import Episode, STATE_PENDING
from podcast_words.config import PodcastConfig, SourceConfig
from podcast_words.models import Transcript, TranscriptCue
from podcast_words.progress import iter_progress
from podcast_words.transcripts import vtt

_TIMEOUT = 30
_NUMBER_RE = re.compile(r"(\d+)")


def _api_get(url: str, params: dict | None = None) -> requests.Response:
    headers = {"Accept": "application/json"}
    return requests.get(url, params=params, headers=headers, timeout=_TIMEOUT)


def _fetch_episode(base: str, episode_id: str) -> dict | None:
    """Load a single episode from ``/episodes/{id}`` (includes ``link``)."""
    if not episode_id:
        return None
    resp = _api_get(f"{base}/episodes/{episode_id}")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    payload = resp.json()
    return payload if isinstance(payload, dict) else None


def _episode_number(item: dict, podcast: PodcastConfig, fallback: int) -> int:
    if podcast.episode_id.type == "sequential":
        return fallback
    number = item.get("number")
    if number not in (None, ""):
        try:
            return int(number)
        except (TypeError, ValueError):
            pass
    if podcast.episode_id.type == "regex" and podcast.episode_id.pattern:
        match = re.search(podcast.episode_id.pattern, str(item.get("title", "")))
        if match:
            return int(match.group(1))
    match = _NUMBER_RE.search(str(item.get("title", "")))
    if match:
        return int(match.group(1))
    return fallback


def discover(podcast: PodcastConfig, source: SourceConfig) -> list[Episode]:
    base = source.api_base.rstrip("/")
    resp = _api_get(f"{base}/episodes", params={"status": "publish"})
    resp.raise_for_status()
    payload = resp.json()

    items = payload.get("results") or payload.get("episodes") or payload.get("_embedded", {}).get(
        "episodes", []
    )
    if isinstance(payload, list):
        items = payload

    if podcast.episode_id.type == "sequential":
        items = sorted(items, key=lambda item: int(str(item.get("id", "0")).strip() or "0"))

    episodes: list[Episode] = []
    for idx, item in enumerate(
        iter_progress(items, desc="PodLove episodes", unit="ep", total=len(items)),
        start=1,
    ):
        episode_id = str(item.get("id", "")).strip()
        link = str(item.get("link", "") or "").strip()
        published_at = str(item.get("publicationDate", "") or item.get("date", "") or "")

        if episode_id and not link:
            detail = _fetch_episode(base, episode_id)
            if detail:
                link = str(detail.get("link", "") or "").strip()
                if not published_at:
                    published_at = str(detail.get("publicationDate", "") or "")
                if item.get("number") in (None, "") and detail.get("number") not in (None, ""):
                    item = {**item, "number": detail.get("number")}

        number = _episode_number(item, podcast, fallback=idx)
        episodes.append(
            Episode(
                number=number,
                title=str(item.get("title", "")).strip(),
                link=link,
                source_id=episode_id,
                published_at=published_at,
                state=STATE_PENDING,
                transcript_source="podlove",
            )
        )
    return episodes


def _cues_from_json(rows: list[dict]) -> list[TranscriptCue]:
    cues: list[TranscriptCue] = []
    for row in rows:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        start_ms = int(row.get("start_ms") or 0)
        end_ms = int(row.get("end_ms") or start_ms)
        cues.append(
            TranscriptCue(
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                voice=(row.get("voice") or None),
            )
        )
    return cues


def fetch_transcript(
    podcast: PodcastConfig, source: SourceConfig, episode: Episode
) -> Transcript | None:
    """Fetch an episode's transcript, or None if unavailable.

    The PodLove v2 endpoint returns JSON with a `transcript` array of timed
    paragraphs. Some installs may return raw WebVTT instead, which we also
    handle as a fallback.
    """
    if not episode.source_id:
        return None
    base = source.api_base.rstrip("/")
    resp = _api_get(f"{base}/transcripts/{episode.source_id}")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if "application/json" in content_type:
        data = resp.json()
        rows = data.get("transcript") if isinstance(data, dict) else None
        if isinstance(rows, list) and rows:
            cues = _cues_from_json(rows)
            return Transcript(cues=cues) if cues else None
        # Fall back to a VTT string wrapped in JSON.
        text = data.get("content") if isinstance(data, dict) else ""
    else:
        text = resp.text

    if text and "-->" in text:
        transcript = vtt.parse(text)
        return transcript if transcript.cues else None
    return None
