"""Per-podcast word counting over canonical transcripts.

Reads every transcript in data/{id}/transcripts/, lemmatizes with the spaCy
model for the podcast's language, and writes a word_counts.csv matrix plus an
episode_stats.json. Incremental by default: episodes already present in
word_counts.csv are skipped unless rebuild=True.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from podcast_words.config import PodcastConfig
from podcast_words.transcripts.loader import load_transcript

_EPISODE_FILE_RE = re.compile(r"episode_(\d+)\.(vtt|txt)$", re.IGNORECASE)


def _load_spacy(model_name: str):
    import spacy

    try:
        return spacy.load(model_name)
    except OSError as exc:
        raise RuntimeError(
            f"spaCy model '{model_name}' is not installed. "
            f"Install it with: python -m spacy download {model_name}"
        ) from exc


def _transcript_files(transcripts_dir: Path) -> dict[int, Path]:
    """Map episode number -> transcript path, preferring .vtt over legacy .txt."""
    found: dict[int, Path] = {}
    if not transcripts_dir.exists():
        return found
    for path in sorted(transcripts_dir.iterdir()):
        match = _EPISODE_FILE_RE.search(path.name)
        if not match:
            continue
        number = int(match.group(1))
        is_vtt = path.suffix.lower() == ".vtt"
        if number not in found or is_vtt:
            found[number] = path
    return found


def _process_text(nlp, text: str, lemma_info: dict[str, bool]) -> list[str]:
    lemmas: list[str] = []
    for token in nlp(text):
        lemma = token.lemma_.lower()
        if not lemma.isalpha():
            continue
        lemmas.append(lemma)
        if lemma not in lemma_info:
            lemma_info[lemma] = bool(token.is_stop)
    return lemmas


def count_words(podcast: PodcastConfig, *, rebuild: bool = False) -> dict:
    """Count words for all transcripts not yet in the matrix.

    Returns a small summary dict for CLI reporting.
    """
    csv_path = podcast.word_counts_csv
    transcripts = _transcript_files(podcast.transcripts_dir)

    if not transcripts:
        return {"processed": 0, "skipped": 0, "total_episodes": 0}

    lemma_info: dict[str, bool] = {}

    if csv_path.exists() and not rebuild:
        df = pd.read_csv(csv_path)
        df.set_index("word", inplace=True)
        existing = {int(c) for c in df.columns if c != "is_stop"}
        if "is_stop" in df.columns:
            lemma_info = {
                str(word): bool(stop)
                for word, stop in df["is_stop"].items()
            }
    else:
        df = pd.DataFrame()
        existing = set()

    pending = [n for n in sorted(transcripts) if n not in existing]
    skipped = len(transcripts) - len(pending)
    if not pending:
        return {"processed": 0, "skipped": skipped, "total_episodes": len(existing)}

    nlp = _load_spacy(podcast.spacy_model)

    processed = 0
    for number in pending:
        transcript = load_transcript(transcripts[number])
        lemmas = _process_text(nlp, transcript.plain_text(), lemma_info)
        column = pd.Series(Counter(lemmas), name=number)
        df = df.join(column, how="outer") if not df.empty else column.to_frame()
        processed += 1

    if processed == 0:
        return {"processed": 0, "skipped": skipped, "total_episodes": len(existing)}

    df.fillna(0, inplace=True)
    episode_columns = [c for c in df.columns if c != "is_stop"]
    df = df.astype({c: "int" for c in episode_columns})
    df["is_stop"] = df.index.map(lambda w: lemma_info.get(w, False))

    ordered = ["is_stop"] + sorted(
        (c for c in df.columns if c != "is_stop"), key=lambda c: int(c)
    )
    df = df[ordered]
    df.sort_index(inplace=True)
    df.reset_index(inplace=True)
    df.rename(columns={"index": "word"}, inplace=True)
    df.replace(0, np.nan, inplace=True)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)

    _write_stats(podcast)

    return {
        "processed": processed,
        "skipped": skipped,
        "total_episodes": len(episode_columns),
    }


def _write_stats(podcast: PodcastConfig) -> None:
    """Recompute episode_stats.json from the word matrix."""
    df = pd.read_csv(podcast.word_counts_csv)
    episode_cols = sorted(
        (c for c in df.columns if c not in ("word", "is_stop")),
        key=lambda c: int(c),
    )
    if not episode_cols:
        return

    df["word"] = df["word"].astype(str)
    total_words = int(df[episode_cols].sum().sum())
    total_unique = int((df[episode_cols].sum(axis=1) > 0).sum())

    seen: set[str] = set()
    episode_stats = []
    for col in episode_cols:
        counts = df[col]
        current = set(df.loc[counts > 0, "word"])
        new_words = current - seen
        seen.update(current)
        episode_stats.append(
            {
                "episode": int(col),
                "total_words": int(counts.sum()),
                "unique_words": int((counts > 0).sum()),
                "new_words": len(new_words),
            }
        )

    result = {
        "total_episodes": len(episode_cols),
        "total_words": total_words,
        "total_unique_words": total_unique,
        "episodes": sorted(episode_stats, key=lambda e: e["episode"]),
    }

    with open(podcast.episode_stats_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
