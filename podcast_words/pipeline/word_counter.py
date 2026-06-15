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
from podcast_words.progress import iter_progress
from podcast_words.transcripts.loader import load_transcript

_EPISODE_FILE_RE = re.compile(r"episode_(\d+)\.(vtt|txt)$", re.IGNORECASE)


def _read_word_counts_csv(csv_path: Path) -> pd.DataFrame:
    """Load word_counts.csv without treating lemmas like ``null`` as NaN."""
    df = pd.read_csv(csv_path, keep_default_na=False)
    df["word"] = df["word"].astype(str)
    episode_cols = [c for c in df.columns if c not in ("word", "is_stop")]
    if episode_cols:
        df[episode_cols] = (
            df[episode_cols].replace("", np.nan).apply(pd.to_numeric, errors="coerce")
        )
    return df


def read_word_vocab(csv_path: Path) -> tuple[str, ...]:
    """Non-stop lemmas from word_counts.csv (reads word/is_stop columns only)."""
    df = pd.read_csv(csv_path, usecols=["word", "is_stop"], keep_default_na=False)
    df["word"] = df["word"].astype(str).str.strip()
    df = df[df["is_stop"].astype(str).str.lower() != "true"]
    return tuple(sorted(w for w in df["word"] if _valid_word_label(w)))


def read_word_counts_for_words(
    csv_path: Path,
    words: frozenset[str] | set[str],
    *,
    chunk_size: int = 20_000,
) -> pd.DataFrame:
    """Episode × word counts for selected lemmas (streams the CSV in chunks)."""
    if not words:
        return pd.DataFrame(columns=["Episode"])

    rows: list[pd.DataFrame] = []
    for chunk in pd.read_csv(csv_path, chunksize=chunk_size, keep_default_na=False):
        hit = chunk["word"].astype(str).isin(words)
        if hit.any():
            rows.append(chunk.loc[hit])

    if not rows:
        return pd.DataFrame(columns=["Episode", *sorted(words)])

    df = pd.concat(rows, ignore_index=True)
    df["word"] = df["word"].astype(str).str.strip()
    df = df[df["is_stop"].astype(str).str.lower() != "true"]
    df = df.drop(columns=["is_stop"])
    episode_cols = [c for c in df.columns if c != "word"]
    if episode_cols:
        df[episode_cols] = (
            df[episode_cols].replace("", np.nan).apply(pd.to_numeric, errors="coerce").fillna(0)
        )
    df = df.astype({c: "uint32" for c in episode_cols})
    wide = df.set_index("word").T
    wide.index.name = "Episode"
    wide = wide.reset_index()
    wide["Episode"] = pd.to_numeric(wide["Episode"], errors="coerce")
    return wide.dropna(subset=["Episode"])


def _valid_word_label(word) -> bool:
    if word is None or (isinstance(word, float) and pd.isna(word)):
        return False
    text = str(word).strip()
    return bool(text) and text.lower() != "nan"


def _sanitize_word_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Drop invalid word labels and merge duplicate rows."""
    if df.empty:
        return df
    labels = pd.Series(df.index, index=df.index)
    valid = labels.apply(_valid_word_label)
    df = df.loc[valid]
    df.index = df.index.astype(str).str.strip()
    if not df.index.is_unique:
        df = df.groupby(level=0, sort=True).sum()
    return df


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
        lemma = token.lemma_.lower().strip()
        if not lemma or not lemma.isalpha():
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
        df = _read_word_counts_csv(csv_path)
        df = df.loc[df["word"].apply(_valid_word_label)]
        df.set_index("word", inplace=True)
        if "is_stop" in df.columns:
            lemma_info = {
                str(word): bool(stop)
                for word, stop in df["is_stop"].items()
                if _valid_word_label(word)
            }
            df = df.drop(columns=["is_stop"])
        df = _sanitize_word_matrix(df)
        existing = {int(c) for c in df.columns}
    else:
        df = pd.DataFrame()
        existing = set()

    pending = [n for n in sorted(transcripts) if n not in existing]
    skipped = len(transcripts) - len(pending)
    if not pending:
        return {"processed": 0, "skipped": skipped, "total_episodes": len(existing)}

    nlp = _load_spacy(podcast.spacy_model)

    # Build each episode column independently, then merge in a single pd.concat.
    # Joining one column at a time fragments the DataFrame and is O(n^2); a single
    # concat aligns all word indexes at once and avoids PerformanceWarnings.
    new_columns: list[pd.Series] = []
    bar = iter_progress(
        pending,
        desc=f"[{podcast.id}] word count",
        unit="ep",
        total=len(pending),
    )
    for number in bar:
        if hasattr(bar, "set_postfix_str"):
            bar.set_postfix_str(f"#{number}")
        transcript = load_transcript(transcripts[number])
        lemmas = _process_text(nlp, transcript.plain_text(), lemma_info)
        counts = Counter(lemmas)
        counts = Counter({k: v for k, v in counts.items() if _valid_word_label(k)})
        new_columns.append(pd.Series(counts, name=number, dtype="float64"))

    processed = len(new_columns)
    if processed == 0:
        return {"processed": 0, "skipped": skipped, "total_episodes": len(existing)}

    new_df = pd.concat(new_columns, axis=1)
    df = pd.concat([df, new_df], axis=1) if not df.empty else new_df
    df = _sanitize_word_matrix(df)

    # The matrix is now all-numeric episode columns. concat leaves one block per
    # source column, so consolidate with copy() before adding is_stop — otherwise
    # the many-block frame triggers pandas' fragmentation PerformanceWarning.
    df = df.fillna(0).astype("int64")
    df = df[sorted(df.columns, key=lambda c: int(c))].copy()
    df.insert(0, "is_stop", [bool(lemma_info.get(w, False)) for w in df.index])
    df.sort_index(inplace=True)
    df.index.name = "word"
    df = df.reset_index()
    df = df.loc[df["word"].apply(_valid_word_label)].copy()
    df.replace(0, np.nan, inplace=True)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)

    _write_stats(podcast)

    return {
        "processed": processed,
        "skipped": skipped,
        "total_episodes": len(existing) + processed,
    }


def _write_stats(podcast: PodcastConfig) -> None:
    """Recompute episode_stats.json from the word matrix."""
    df = _read_word_counts_csv(podcast.word_counts_csv)
    df = df.loc[df["word"].apply(_valid_word_label)]
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
