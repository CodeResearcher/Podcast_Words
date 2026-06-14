"""Command-line interface: python -m podcast_words <command> ..."""

from __future__ import annotations

import argparse
import sys

from podcast_words.config import get_podcast, load_config


def _cmd_list(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    for pid, podcast in config.items():
        sources = ", ".join(s.type for s in podcast.sources) or "none"
        marker = "✓" if podcast.has_data() else " "
        print(f"[{marker}] {pid}: {podcast.name} ({podcast.language}) — sources: {sources}")
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    from podcast_words.pipeline.episode_sync import sync

    podcast = get_podcast(args.podcast, args.config)
    source = None
    if args.source:
        source = podcast.source_of_type(args.source)
        if source is None:
            print(f"Podcast '{podcast.id}' has no '{args.source}' source.", file=sys.stderr)
            return 1

    if args.replace_from and args.source and args.replace_from != args.source:
        print(
            "Use either --source or --replace-from, not both with different sources.",
            file=sys.stderr,
        )
        return 1

    replace_from = None
    if args.replace_from:
        replace_from = podcast.source_of_type(args.replace_from)
        if replace_from is None:
            print(
                f"Podcast '{podcast.id}' has no '{args.replace_from}' source.",
                file=sys.stderr,
            )
            return 1

    summary = sync(
        podcast,
        source=source,
        backfill=args.backfill,
        force=args.force,
        count=not args.no_count,
        rebuild=args.rebuild,
        fallback=args.fallback,
        replace_from=replace_from,
        replace_if_from=tuple(args.replace_if_from) if args.replace_if_from else None,
        limit=args.limit,
    )
    print(
        f"\nSynced {podcast.id}: +{summary['new_episodes']} new, "
        f"{summary['fetched']} transcripts fetched, "
        f"{summary['no_transcript']} without transcript, "
        f"{summary['errors']} errors."
    )
    if "replace" in summary:
        rep = summary["replace"]
        note = " (source unavailable)" if rep.get("unsupported") else ""
        print(
            f"Replace: {rep['replaced']} replaced, "
            f"{rep['skipped']} skipped (no remote match), "
            f"{rep['no_transcript']} without transcript, "
            f"{rep['errors']} errors{note}."
        )
    if "fallback" in summary:
        fb = summary["fallback"]
        note = " (source unavailable)" if fb.get("unsupported") else ""
        print(
            f"Fallback: {fb['recovered']} recovered, "
            f"{fb['still_missing']} still missing{note}."
        )
    if "count" in summary:
        c = summary["count"]
        print(
            f"Word count: {c['processed']} processed, {c['skipped']} skipped, "
            f"{c['total_episodes']} episodes total."
        )
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    from podcast_words.pipeline.manual_import import import_dir, import_file

    podcast = get_podcast(args.podcast, args.config)
    if args.dir:
        numbers = import_dir(podcast, args.dir)
        print(f"Imported {len(numbers)} transcripts: {numbers}")
    elif args.file:
        number = import_file(podcast, args.file, episode=args.episode)
        print(f"Imported transcript for episode {number}.")
    else:
        print("Provide either --file or --dir.", file=sys.stderr)
        return 1

    if args.count:
        from podcast_words.pipeline.word_counter import count_words

        result = count_words(podcast)
        print(f"Word count: {result['processed']} processed, {result['skipped']} skipped.")
    return 0


def _cmd_count(args: argparse.Namespace) -> int:
    from podcast_words.pipeline.word_counter import count_words

    podcast = get_podcast(args.podcast, args.config)
    result = count_words(podcast, rebuild=args.rebuild)
    print(
        f"Word count for {podcast.id}: {result['processed']} processed, "
        f"{result['skipped']} skipped, {result['total_episodes']} episodes total."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="podcast_words")
    parser.add_argument("--config", help="Path to podcasts.yaml (defaults to config/podcasts.yaml).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List configured podcasts.")
    p_list.set_defaults(func=_cmd_list)

    p_sync = sub.add_parser("sync", help="Discover episodes and import transcripts.")
    p_sync.add_argument("--podcast", required=True)
    p_sync.add_argument("--source", help="Force a specific source type (e.g. podlove).")
    p_sync.add_argument("--backfill", action="store_true", help="Retry all pending/no_transcript episodes.")
    p_sync.add_argument("--force", action="store_true", help="Re-fetch transcripts for every episode.")
    p_sync.add_argument(
        "--fallback",
        action="store_true",
        help="Recover no_transcript episodes from the podcast's other configured sources.",
    )
    p_sync.add_argument(
        "--replace-from",
        metavar="SOURCE",
        help="Replace existing transcripts by re-fetching from SOURCE "
        "(e.g. apple, whisper_rss). Only episodes whose transcript came from "
        "a different source are overwritten.",
    )
    p_sync.add_argument(
        "--replace-if-from",
        metavar="SOURCE",
        action="append",
        help="With --replace-from, only replace transcripts currently from SOURCE "
        "(repeatable, e.g. --replace-if-from podlove).",
    )
    p_sync.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only fetch transcripts for the first N target episodes (0 = discover only). "
        "Useful for batching slow sources like Whisper.",
    )
    p_sync.add_argument("--no-count", action="store_true", help="Skip word counting after import.")
    p_sync.add_argument("--rebuild", action="store_true", help="Recount all episodes from scratch.")
    p_sync.set_defaults(func=_cmd_sync)

    p_import = sub.add_parser("import", help="Manually import a transcript file or folder.")
    p_import.add_argument("--podcast", required=True)
    p_import.add_argument("--file", help="Path to a single transcript file.")
    p_import.add_argument("--dir", help="Path to a folder of transcript files.")
    p_import.add_argument("--episode", type=int, help="Episode number (if not in filename).")
    p_import.add_argument("--count", action="store_true", help="Run word counter after import.")
    p_import.set_defaults(func=_cmd_import)

    p_count = sub.add_parser("count", help="Run the word counter for a podcast.")
    p_count.add_argument("--podcast", required=True)
    p_count.add_argument("--rebuild", action="store_true")
    p_count.set_defaults(func=_cmd_count)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
