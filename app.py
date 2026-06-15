import json
import re
import time
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objs as go
import streamlit as st
from streamlit_searchbox import st_searchbox

from podcast_words.catalog import (
    STATE_DONE,
    STATE_ERROR,
    STATE_NO_TRANSCRIPT,
    STATE_PENDING,
    STATE_SKIP,
    Catalog,
)
from podcast_words.config import load_config, sorted_podcast_ids
from podcast_words.pipeline.word_counter import _read_word_counts_csv
from podcast_words.word_search import (
    SEARCH_MIN_LEN,
    active_search_term,
    default_selected_words,
    format_selected_display,
    search_vocabulary,
)

st.set_page_config(layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stSidebar"] [data-baseweb="select"] input {
        caret-color: transparent !important;
        cursor: pointer !important;
    }
    [data-testid="stPlotlyChart"] {
        width: 100% !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

_SOURCE_LABELS = {
    "podlove": "PodLove",
    "apple": "Apple Podcasts",
    "whisper": "Whisper",
    "whisper_rss": "Whisper",
    "manual": "Manual",
    "vtt_import": "Manual import",
    "unknown": "Unknown",
}

_STATE_LABELS = {
    STATE_PENDING: "Pending",
    STATE_NO_TRANSCRIPT: "No transcript",
    STATE_ERROR: "Error",
    STATE_SKIP: "Skipped",
}

_MISSING_TRANSCRIPT_STATES = frozenset(
    {STATE_PENDING, STATE_NO_TRANSCRIPT, STATE_ERROR, STATE_SKIP}
)

_AUDIO_SUFFIXES = (".mp3", ".m4a", ".wav", ".ogg", ".aac")
_HOVER_EPISODE_COUNT = (
    "Episode %{customdata[0]}<br>%{y}<br>Source: %{customdata[1]}<extra></extra>"
)
_HOVER_BAR_COUNT = "Episode %{customdata[0]}<br>%{x}<br>Source: %{customdata[1]}<extra></extra>"
_CHART_MARGIN = dict(l=48, r=24, t=36, b=48)
_MAX_X_TICKS = 12


def _source_label(source: str) -> str:
    key = (source or "unknown").strip()
    return _SOURCE_LABELS.get(key, key or "Unknown")


def _line_customdata(meta: dict[int, dict[str, str]], episodes) -> list[list[object]]:
    return [
        [int(ep), meta.get(int(ep), {}).get("source", "Unknown")]
        for ep in episodes
    ]


def _compact_episode_axis(episode_numbers: list[int]) -> tuple[list[int], dict]:
    """Map sorted episode numbers to compact 1..N x positions with readable ticks."""
    if not episode_numbers:
        return [], {}
    n = len(episode_numbers)
    x = list(range(1, n + 1))
    step = max(1, n // _MAX_X_TICKS)
    tickvals = list(range(1, n + 1, step))
    if tickvals[-1] != n:
        tickvals.append(n)
    ticktext = [str(episode_numbers[i - 1]) for i in tickvals]
    return x, dict(tickmode="array", tickvals=tickvals, ticktext=ticktext)


def _prepare_episode_line_chart(
    episode_numbers: pd.Series,
    meta: dict[int, dict[str, str]],
) -> tuple[list[int], list[int], list[list[object]], dict]:
    """Sort episodes and build compact x-axis coords plus hover customdata."""
    nums = pd.to_numeric(episode_numbers, errors="coerce").dropna().astype(int)
    order = nums.sort_values()
    episodes = order.tolist()
    x, xaxis_ticks = _compact_episode_axis(episodes)
    return x, episodes, _line_customdata(meta, episodes), xaxis_ticks


def _bar_customdata(meta: dict[int, dict[str, str]], episodes) -> list[list[object]]:
    return [
        [int(ep), meta.get(int(ep), {}).get("source", "Unknown")]
        for ep in episodes
    ]


def _chart_layout(fig: go.Figure, *, height: int, uirevision: str, **extra) -> go.Figure:
    """Responsive Plotly layout; uirevision keeps zoom/pan across fragment reruns."""
    fig.update_layout(
        height=height,
        autosize=True,
        margin=_CHART_MARGIN,
        hovermode="closest",
        uirevision=uirevision,
        **extra,
    )
    return fig


def _plotly_chart(fig: go.Figure, *, key: str) -> object:
    return st.plotly_chart(
        fig,
        width="stretch",
        on_select="rerun",
        selection_mode="points",
        key=key,
    )


def _is_audio_url(url: str) -> bool:
    lower = url.lower().split("?", 1)[0]
    return (
        lower.endswith(_AUDIO_SUFFIXES)
        or "/podlove/file/" in lower
        or "podigee-cdn" in lower
        or "archive.org" in lower
    )


def _episode_url(episode, podcast) -> str:
    """Best public URL for an episode page, falling back to audio when needed."""
    link = (episode.link or "").strip()
    if link and not _is_audio_url(link):
        return link

    apple = podcast.source_of_type("apple")
    track_id = episode.source_id or ""
    # Apple track IDs are long numerics; PodLove/RSS internal IDs are shorter.
    if apple and track_id.isdigit() and len(track_id) >= 9:
        country = (apple.country or "US").lower()
        return (
            f"https://podcasts.apple.com/{country}/podcast/"
            f"id{apple.podcast_id}?i={track_id}"
        )

    return link


def _selection_points(selection) -> list:
    if selection is None:
        return []
    if hasattr(selection, "get"):
        return selection.get("points") or []
    return getattr(selection, "points", None) or []


def _episode_number_from_point(point, *, axis: str = "x") -> int | None:
    if isinstance(point, dict):
        custom = point.get("customdata")
        raw = point.get(axis)
    else:
        custom = getattr(point, "customdata", None)
        raw = getattr(point, axis, None)

    if custom is not None:
        value = custom[0] if isinstance(custom, (list, tuple)) else custom
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
        if isinstance(custom, (list, tuple)) and len(custom) >= 1:
            try:
                return int(custom[0])
            except (TypeError, ValueError):
                pass

    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        match = re.search(r"(\d+)", str(raw))
        return int(match.group(1)) if match else None


def _show_selected_episode_link(selection, meta: dict[int, dict[str, str]], *, axis: str = "x") -> None:
    points = _selection_points(selection)
    if not points:
        return
    number = _episode_number_from_point(points[0], axis=axis)
    if number is None:
        return
    row = meta.get(number, {})
    url = row.get("url", "")
    title = row.get("title", "") or f"Episode {number}"
    if url:
        st.link_button(f"Open episode {number}: {title}", url, width="content")


@st.cache_data
def load_episode_meta(podcast_id: str) -> dict[int, dict[str, str]]:
    config = get_config()
    podcast = config[podcast_id]
    meta: dict[int, dict[str, str]] = {}
    if not podcast.episodes_csv.exists():
        return meta
    catalog = Catalog.load(podcast.episodes_csv)
    for ep in catalog:
        if ep.state != STATE_DONE:
            continue
        meta[ep.number] = {
            "title": ep.title,
            "url": _episode_url(ep, podcast),
            "source": _source_label(ep.transcript_source),
        }
    return meta


@st.cache_data
def get_config():
    return {pid: p for pid, p in load_config().items()}


@st.cache_data
def load_word_vocab_sorted(podcast_id: str) -> tuple[str, ...]:
    """Sorted non-stop lemmas for instant prefix search."""
    config = get_config()
    podcast = config[podcast_id]
    df = _read_word_counts_csv(podcast.word_counts_csv)
    df = df[df["is_stop"].astype(str).str.lower() != "true"]
    words = df["word"].astype(str).str.strip()
    return tuple(sorted(w for w in words if w))


@st.fragment
def _word_search_picker(
    podcast_id: str,
    podcast,
    sorted_vocab: tuple[str, ...],
) -> list[str]:
    """Single combobox: type to search, pick to add or remove words."""
    vocab = frozenset(sorted_vocab)
    words_key = f"words_{podcast_id}"
    searchbox_key = f"word_searchbox_{podcast_id}"
    if words_key not in st.session_state:
        st.session_state[words_key] = default_selected_words(podcast.search_words, vocab)

    selected: list[str] = list(st.session_state[words_key])
    selected_display = format_selected_display(selected)

    def _format_option(word: str) -> tuple[str, str]:
        mark = "✓ " if word in st.session_state[words_key] else ""
        return (f"{mark}{word}", word)

    def _sync_searchbox_display() -> None:
        display = format_selected_display(st.session_state[words_key])
        box = st.session_state[searchbox_key]
        box["search"] = display
        box["key_react"] = f"{searchbox_key}_react_{time.time()}"

    def search_fn(term: str) -> list[tuple[str, str]]:
        query = active_search_term(term)
        selected_now = list(st.session_state[words_key])
        if len(query) < SEARCH_MIN_LEN:
            return [_format_option(w) for w in selected_now]
        seen: set[str] = set()
        results: list[tuple[str, str]] = []
        for word in search_vocabulary(sorted_vocab, query):
            if word in seen:
                continue
            seen.add(word)
            results.append(_format_option(word))
        return results

    def toggle_word(word: str) -> None:
        w = str(word).strip().lower()
        if w not in vocab:
            return
        current = st.session_state[words_key]
        if w in current:
            current.remove(w)
        else:
            current.append(w)
        if searchbox_key in st.session_state:
            _sync_searchbox_display()

    st_searchbox(
        search_fn,
        label="🔍 Words for charts",
        placeholder=f"Type at least {SEARCH_MIN_LEN} characters…",
        help=(
            f"{len(selected)} selected. "
            "Pick a word to add it; pick a checked word again to remove it."
        ),
        submit_function=toggle_word,
        default_searchterm=selected_display,
        default_options=[_format_option(w) for w in selected],
        rerun_scope="fragment",
        clear_on_submit=False,
        key=searchbox_key,
    )

    return list(st.session_state[words_key])


@st.cache_data
def load_data(podcast_id: str):
    config = get_config()
    podcast = config[podcast_id]
    df = _read_word_counts_csv(podcast.word_counts_csv)
    df.set_index("word", inplace=True)
    df.fillna(0, inplace=True)
    df = df[df["is_stop"].astype(str).str.lower() != "true"]
    df = df.drop(columns=["is_stop"])
    df = df.astype("uint32")
    df = df.T  # episodes become rows
    df.index.name = "Episode"
    df.reset_index(inplace=True)
    return df


@st.cache_data
def load_stats(podcast_id: str):
    config = get_config()
    podcast = config[podcast_id]
    with open(podcast.episode_stats_json, "r", encoding="utf-8") as f:
        stats = json.load(f)
    episodes_stats_df = pd.DataFrame(stats["episodes"])
    return stats, episodes_stats_df


@st.cache_data
def load_sync_state(podcast_id: str) -> dict | None:
    config = get_config()
    podcast = config[podcast_id]
    path = podcast.sync_state_json
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        state = json.load(f)

    last_at: datetime | None = None
    raw_at = state.get("last_sync_at")
    if raw_at:
        last_at = datetime.fromisoformat(str(raw_at).replace("Z", "+00:00"))

    number = state.get("last_episode_number")
    return {
        "last_sync_at": last_at,
        "last_episode_number": int(number) if number is not None else None,
        "last_episode_title": str(state.get("last_episode_title") or "").strip(),
        "last_episode_count": state.get("last_episode_count"),
    }


def _last_sync_caption(sync_info: dict | None) -> str:
    if not sync_info or sync_info.get("last_sync_at") is None:
        return "Last sync: —"
    when = sync_info["last_sync_at"].astimezone().strftime("%Y-%m-%d %H:%M %Z")
    number = sync_info.get("last_episode_number")
    title = sync_info.get("last_episode_title") or ""
    if number is not None:
        return f"Last sync: {when} — #{number} {title}".strip()
    return f"Last sync: {when}"


@st.cache_data
def load_coverage(podcast_id: str):
    config = get_config()
    podcast = config[podcast_id]
    if not podcast.episodes_csv.exists():
        return None
    catalog = Catalog.load(podcast.episodes_csv)

    by_source: dict[str, int] = {}
    for ep in catalog:
        if ep.state == STATE_DONE:
            src = ep.transcript_source or "unknown"
            by_source[src] = by_source.get(src, 0) + 1

    latest_at: datetime | None = None
    latest_episode: int | None = None
    episode_re = re.compile(r"episode_(\d+)\.vtt$")
    for vtt_path in podcast.transcripts_dir.glob("episode_*.vtt"):
        match = episode_re.search(vtt_path.name)
        if not match:
            continue
        mtime = datetime.fromtimestamp(vtt_path.stat().st_mtime, tz=timezone.utc)
        if latest_at is None or mtime > latest_at:
            latest_at = mtime
            latest_episode = int(match.group(1))

    latest_title = ""
    if latest_episode is not None:
        ep = catalog.get(latest_episode)
        latest_title = ep.title if ep else ""

    return {
        "total": len(catalog),
        "states": catalog.state_counts(),
        "by_source": by_source,
        "latest_transcript_at": latest_at,
        "latest_transcript_episode": latest_episode,
        "latest_transcript_title": latest_title,
    }


@st.cache_data
def load_missing_episodes(podcast_id: str) -> pd.DataFrame:
    """Episodes in the catalog that do not have a transcript yet."""
    config = get_config()
    podcast = config[podcast_id]
    if not podcast.episodes_csv.exists():
        return pd.DataFrame(columns=["Episode", "Title", "State", "Published", "Link"])

    catalog = Catalog.load(podcast.episodes_csv)
    rows: list[dict[str, object]] = []
    for ep in catalog:
        if ep.state == STATE_DONE:
            continue
        if ep.state not in _MISSING_TRANSCRIPT_STATES:
            continue
        url = _episode_url(ep, podcast)
        rows.append(
            {
                "Episode": ep.number,
                "Title": ep.title or f"Episode {ep.number}",
                "State": _STATE_LABELS.get(ep.state, ep.state),
                "Published": ep.published_at or "",
                "Link": url or None,
            }
        )

    if not rows:
        return pd.DataFrame(columns=["Episode", "Title", "State", "Published", "Link"])
    return pd.DataFrame(rows).sort_values("Episode").reset_index(drop=True)


config = get_config()
available_ids = sorted_podcast_ids({pid: p for pid, p in config.items() if p.has_data()})
available = {pid: config[pid] for pid in available_ids}

st.sidebar.title("🎙️ Podcast Words")
if not available:
    st.title("🎙️ Podcast Words")
    st.warning(
        "No podcast data found yet. Build a dataset with:\n\n"
        "`python -m podcast_words sync --podcast <id>`"
    )
    st.stop()

podcast_id = st.sidebar.selectbox(
    "Podcast",
    options=available_ids,
    format_func=lambda pid: available[pid].name,
)

podcast = available[podcast_id]
coverage = load_coverage(podcast_id)
sync_info = load_sync_state(podcast_id)

st.sidebar.caption(_last_sync_caption(sync_info))

if coverage:
    with_transcript = coverage["states"].get("done", 0)
    st.sidebar.caption(
        f"{with_transcript}/{coverage['total']} episodes with transcripts"
    )
    if coverage["latest_transcript_at"] is not None:
        fetched = coverage["latest_transcript_at"].astimezone()
        ep_no = coverage["latest_transcript_episode"]
        title = coverage["latest_transcript_title"]
        label = f"#{ep_no} {title}".strip() if ep_no is not None else "—"
        st.sidebar.caption(
            f"Latest transcript: {fetched.strftime('%Y-%m-%d %H:%M %Z')} — {label}"
        )
    if coverage["by_source"]:
        parts = [
            f"{_SOURCE_LABELS.get(src, src)}: {count}"
            for src, count in sorted(
                coverage["by_source"].items(), key=lambda item: (-item[1], item[0])
            )
        ]
        st.sidebar.caption("Transcripts by source: " + " · ".join(parts))

stats, _ = load_stats(podcast_id)

st.title(f"🎙️ {podcast.name} — Word Analysis")

st.caption(_last_sync_caption(sync_info))

if coverage:
    with_transcript = coverage["states"].get("done", 0)
    st.caption(f"{with_transcript}/{coverage['total']} episodes with transcripts")

# Word search picker (server-side lookup over cached vocabulary)
sorted_vocab = load_word_vocab_sorted(podcast_id)
selected_words = _word_search_picker(podcast_id, podcast, sorted_vocab)


@st.fragment
def _word_line_chart(podcast_id: str, selected: list[str]) -> None:
    if not selected:
        return
    meta = load_episode_meta(podcast_id)
    data = load_data(podcast_id)
    df_selected = data[["Episode"] + selected]

    st.subheader("📊 Frequency of selected words across all episodes")
    df_plot = df_selected.copy()
    df_plot["_ep"] = pd.to_numeric(df_plot["Episode"], errors="coerce")
    df_plot = df_plot.dropna(subset=["_ep"]).sort_values("_ep")
    episodes = df_plot["_ep"].astype(int).tolist()
    x, xaxis_ticks = _compact_episode_axis(episodes)
    hover_custom = _line_customdata(meta, episodes)
    fig_line = go.Figure()
    for word in selected:
        fig_line.add_trace(
            go.Scatter(
                x=x,
                y=df_plot[word].tolist(),
                mode="lines",
                stackgroup="one",
                name=word,
                customdata=hover_custom,
                hovertemplate=_HOVER_EPISODE_COUNT,
            )
        )
    _chart_layout(
        fig_line,
        height=400,
        uirevision=f"{podcast_id}-word-line",
        xaxis_title="Episode",
        yaxis_title="Count",
        xaxis=xaxis_ticks,
    )
    line_event = _plotly_chart(fig_line, key=f"word_line_{podcast_id}")
    _show_selected_episode_link(line_event.selection if line_event else None, meta)


@st.fragment
def _word_bar_chart(podcast_id: str, selected: list[str]) -> None:
    if not selected:
        return
    meta = load_episode_meta(podcast_id)
    data = load_data(podcast_id)
    df_selected = data[["Episode"] + selected]

    st.subheader("🏅 Top 10 episodes for the selected words")
    ranked = df_selected.copy()
    ranked["total_selected"] = ranked[selected].sum(axis=1)
    top10 = ranked.sort_values("total_selected", ascending=False).head(10)
    top10_sorted = top10.sort_values("total_selected", ascending=True)
    bar_custom = _bar_customdata(meta, top10_sorted["Episode"])

    fig_bar = go.Figure()
    for word in selected:
        fig_bar.add_trace(
            go.Bar(
                x=top10_sorted[word],
                y=top10_sorted["Episode"].astype(str).radd("Episode "),
                customdata=bar_custom,
                name=word,
                orientation="h",
                hovertemplate=_HOVER_BAR_COUNT,
            )
        )
    _chart_layout(
        fig_bar,
        height=500,
        uirevision=f"{podcast_id}-word-bar",
        barmode="stack",
        xaxis_title="Count",
        yaxis_title="Episode (top 10)",
        yaxis=dict(type="category"),
    )
    bar_event = _plotly_chart(fig_bar, key=f"word_bar_{podcast_id}")
    _show_selected_episode_link(bar_event.selection if bar_event else None, meta, axis="y")


if selected_words:
    _word_line_chart(podcast_id, selected_words)
    _word_bar_chart(podcast_id, selected_words)
else:
    st.info("⬆ Please select one or more words above.")


@st.fragment
def _stats_total_chart(podcast_id: str) -> None:
    meta = load_episode_meta(podcast_id)
    _, episodes_stats_df = load_stats(podcast_id)
    st.subheader("📈 Words per episode")
    df = episodes_stats_df.sort_values("episode")
    x, episodes, hover_custom, xaxis_ticks = _prepare_episode_line_chart(df["episode"], meta)
    fig_total = go.Figure(
        go.Scatter(
            x=x,
            y=df.set_index("episode").loc[episodes, "total_words"].tolist(),
            mode="lines+markers",
            customdata=hover_custom,
            hovertemplate=_HOVER_EPISODE_COUNT,
        )
    )
    _chart_layout(
        fig_total,
        height=320,
        uirevision=f"{podcast_id}-stats-total",
        xaxis_title="Episode",
        yaxis_title="Words",
        xaxis=xaxis_ticks,
    )
    total_event = _plotly_chart(fig_total, key=f"stats_total_{podcast_id}")
    _show_selected_episode_link(total_event.selection if total_event else None, meta)


@st.fragment
def _stats_unique_chart(podcast_id: str) -> None:
    meta = load_episode_meta(podcast_id)
    _, episodes_stats_df = load_stats(podcast_id)
    st.subheader("🔠 Distinct words per episode")
    df = episodes_stats_df.sort_values("episode")
    x, episodes, hover_custom, xaxis_ticks = _prepare_episode_line_chart(df["episode"], meta)
    fig_unique = go.Figure(
        go.Scatter(
            x=x,
            y=df.set_index("episode").loc[episodes, "unique_words"].tolist(),
            mode="lines+markers",
            customdata=hover_custom,
            hovertemplate=_HOVER_EPISODE_COUNT,
        )
    )
    _chart_layout(
        fig_unique,
        height=320,
        uirevision=f"{podcast_id}-stats-unique",
        xaxis_title="Episode",
        yaxis_title="Count",
        xaxis=xaxis_ticks,
    )
    unique_event = _plotly_chart(fig_unique, key=f"stats_unique_{podcast_id}")
    _show_selected_episode_link(unique_event.selection if unique_event else None, meta)


@st.fragment
def _stats_new_chart(podcast_id: str) -> None:
    meta = load_episode_meta(podcast_id)
    _, episodes_stats_df = load_stats(podcast_id)
    st.subheader("🆕 New words per episode")
    df = episodes_stats_df.sort_values("episode")
    x, episodes, hover_custom, xaxis_ticks = _prepare_episode_line_chart(df["episode"], meta)
    fig_new = go.Figure(
        go.Scatter(
            x=x,
            y=df.set_index("episode").loc[episodes, "new_words"].tolist(),
            mode="lines+markers",
            customdata=hover_custom,
            hovertemplate=_HOVER_EPISODE_COUNT,
        )
    )
    _chart_layout(
        fig_new,
        height=320,
        uirevision=f"{podcast_id}-stats-new",
        xaxis_title="Episode",
        yaxis_title="New words",
        yaxis_type="log",
        title="New words per episode (logarithmic)",
        xaxis=xaxis_ticks,
    )
    new_event = _plotly_chart(fig_new, key=f"stats_new_{podcast_id}")
    _show_selected_episode_link(new_event.selection if new_event else None, meta)


# General statistics
st.header("📋 General statistics")
col1, col2, col3 = st.columns(3)
col1.metric("🎧 Episodes", stats["total_episodes"])
col2.metric("🗣️ Total words spoken", f"{stats['total_words']:,}")
col3.metric("🔤 Distinct words", f"{stats['total_unique_words']:,}")

_stats_total_chart(podcast_id)
_stats_unique_chart(podcast_id)
_stats_new_chart(podcast_id)

with st.expander("🔧 How this analysis is built"):
    st.markdown(
        """
        Transcripts are collected per podcast from the configured source
        (RSS + Whisper, the PodLove Publisher API, Apple Podcasts, or manual
        import) and stored as WebVTT files. They are then lemmatized with spaCy,
        stop words are removed, and word frequencies are aggregated per episode.

        See the project README for the full multi-podcast workflow.
        """
    )

st.header("📭 Episodes without transcript")
missing_df = load_missing_episodes(podcast_id)
if missing_df.empty:
    st.success("All catalogued episodes have transcripts.")
else:
    st.caption(f"{len(missing_df)} episodes in the catalog without a transcript.")
    st.dataframe(
        missing_df,
        width="stretch",
        hide_index=True,
        column_config={
            "Episode": st.column_config.NumberColumn("Episode", format="%d"),
            "Link": st.column_config.LinkColumn("Link", display_text="Open"),
        },
    )
