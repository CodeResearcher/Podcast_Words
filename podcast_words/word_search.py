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


def format_selected_display(words: list[str]) -> str:
    """Comma-separated label for the searchbox input."""
    return ", ".join(words)


def active_search_term(term: str) -> str:
    """Last comma-separated segment — supports typing after selected words."""
    if not term:
        return ""
    return term.rsplit(",", 1)[-1].strip().lower()


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
