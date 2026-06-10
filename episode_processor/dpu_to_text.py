"""Deprecated entry point.

The RSS + Whisper pipeline now lives in the podcast_words package and is driven
by the unified sync command. This wrapper is kept for backward compatibility.

Use instead:
    python -m podcast_words sync --podcast pufo

See README.md for the multi-podcast workflow.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    print(
        "episode_processor/dpu_to_text.py is deprecated.\n"
        "Run the RSS + Whisper pipeline via:\n"
        "    python -m podcast_words sync --podcast pufo\n"
    )
    from podcast_words.cli import main as cli_main

    return cli_main(["sync", "--podcast", "pufo"])


if __name__ == "__main__":
    raise SystemExit(main())
