"""Terminal progress bars for long-running sync operations."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Iterator
from typing import TypeVar

T = TypeVar("T")


def progress_enabled() -> bool:
    """True when stderr is a TTY and progress has not been opted out."""
    if os.environ.get("PODCASTWORDS_NO_PROGRESS"):
        return False
    return sys.stderr.isatty()


def iter_progress(
    iterable: Iterable[T],
    *,
    desc: str,
    unit: str = "item",
    total: int | None = None,
    leave: bool = True,
) -> Iterator[T]:
    """Wrap *iterable* with a tqdm bar when progress output is enabled."""
    if not progress_enabled():
        return iter(iterable)
    from tqdm import tqdm

    return tqdm(iterable, desc=desc, unit=unit, total=total, leave=leave)


def write(message: str) -> None:
    """Print without breaking an active progress bar."""
    if progress_enabled():
        from tqdm import tqdm

        tqdm.write(message)
    else:
        print(message)
