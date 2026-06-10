"""Deprecated entry point.

Word counting now lives in podcast_words.pipeline.word_counter and is per-podcast.
This wrapper is kept for backward compatibility.

Use instead:
    python -m podcast_words count --podcast pufo
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    print(
        "episode_processor/word_counter.py is deprecated.\n"
        "Run word counting via:\n"
        "    python -m podcast_words count --podcast pufo\n"
    )
    from podcast_words.cli import main as cli_main

    return cli_main(["count", "--podcast", "pufo"])


if __name__ == "__main__":
    raise SystemExit(main())
