"""Vocabulary search helpers for the Streamlit word picker."""

from __future__ import annotations

import bisect

SEARCH_MIN_LEN = 2
SEARCH_MAX_RESULTS = 20


def search_vocabulary(
    sorted_vocab: tuple[str, ...],
    query: str,
    *,
    limit: int = SEARCH_MAX_RESULTS,
    exclude: frozenset[str] | set[str] | None = None,
) -> list[str]:
    """Return prefix matches first, then substring matches (sorted vocab required)."""
    q = query.strip().lower()
    if len(q) < SEARCH_MIN_LEN:
        return []

    blocked = exclude or set()
    results: list[str] = []
    seen: set[str] = set()

    start = bisect.bisect_left(sorted_vocab, q)
    i = start
    while i < len(sorted_vocab) and sorted_vocab[i].startswith(q) and len(results) < limit:
        word = sorted_vocab[i]
        if word not in blocked and word not in seen:
            results.append(word)
            seen.add(word)
        i += 1

    if len(results) < limit and len(q) >= 3:
        for word in sorted_vocab:
            if word in seen or word in blocked:
                continue
            if q in word:
                results.append(word)
                seen.add(word)
                if len(results) >= limit:
                    break

    return results


def extract_query(term: str, selected: "list[str] | tuple[str, ...]") -> str:
    """Search text left after removing already-selected words from the box.

    The combobox shows the selection as text, so a user who types to search
    ends up with e.g. ``"ukraine dat"``. Removing the selected words isolates
    the part actually being typed (``"dat"``).
    """
    text = (term or "").lower().replace(",", " ")
    for word in sorted(selected, key=len, reverse=True):
        if word:
            text = text.replace(word.lower(), " ")
    return " ".join(text.split()).strip()


def default_selected_words(search_words: list[str], vocab: frozenset[str]) -> list[str]:
    """Config defaults that exist in the podcast vocabulary."""
    selected: list[str] = []
    seen: set[str] = set()
    for word in search_words:
        w = str(word).strip().lower()
        if w and w in vocab and w not in seen:
            seen.add(w)
            selected.append(w)
    return selected
