from __future__ import annotations

import os
from datetime import datetime
from typing import Callable, Dict, List, Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from manga_watch.discord_text import format_discord_link
from manga_watch.storage import load_state, load_watchlist

DEFAULT_TIMEZONE = "Asia/Tokyo"
LATEST_COMMAND = "latest"
HEADER_LINE = "保存済みの最新話一覧です"
LIST_HEADER_LINE = "現在のリスト:"
EMPTY_LINE = "- まだ保存済みの監視結果がありません"
PARTIAL_FAILURE_WARNING = "注意: 一部作品は直近巡回で失敗しており、表示内容は保存済みデータです"


def validated_timezone_name(timezone_name: str) -> str:
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown TZ value: {timezone_name}") from exc
    return timezone_name


def format_last_run(last_run_at: object, timezone_name: str) -> str:
    if last_run_at is None:
        return "まだ実行されていません"
    timezone_name = validated_timezone_name(timezone_name)
    return datetime.fromtimestamp(int(last_run_at), tz=ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M:%S %Z")


def series_label(work_id: str, latest: Mapping[str, object]) -> str:
    return str(latest.get("series_title") or latest.get("series") or work_id)


def latest_label(latest: Mapping[str, object]) -> str:
    return str(latest.get("episode_title") or latest.get("episode_code") or latest.get("url") or "未取得")


def render_work_line(work_id: str, latest: Mapping[str, object]) -> str:
    series = series_label(work_id, latest)
    if not latest:
        return f"（未取得）　{series}"
    return f"{format_discord_link(latest_label(latest), latest.get('url'))}　{series}"


def build_latest_query_lines(
    watchlist: Mapping[str, object],
    state: Mapping[str, object],
    *,
    timezone_name: Optional[str] = None,
) -> List[str]:
    works = watchlist.get("works", [])
    if not isinstance(works, list):
        raise ValueError("watchlist.works must be a list")

    state_works = state.get("works", {})
    if not isinstance(state_works, Mapping):
        raise ValueError("state.works must be an object")

    timezone_name = validated_timezone_name(timezone_name or os.environ.get("TZ", DEFAULT_TIMEZONE))
    lines = [
        HEADER_LINE,
        f"最終巡回: {format_last_run(state.get('last_run_at'), timezone_name)}",
        LIST_HEADER_LINE,
    ]

    rendered_works: List[str] = []
    partial_failure = False

    for raw_entry in works:
        if not isinstance(raw_entry, Mapping):
            raise ValueError("watchlist entry must be an object")
        if not bool(raw_entry.get("enabled")):
            continue

        work_id = str(raw_entry.get("id") or "").strip()
        if not work_id:
            raise ValueError("watchlist entry missing id")

        raw_state_entry = state_works.get(work_id, {})
        if not isinstance(raw_state_entry, Mapping):
            raise ValueError(f"state entry {work_id} must be an object")

        latest = raw_state_entry.get("latest", {})
        if latest is None:
            latest = {}
        if not isinstance(latest, Mapping):
            raise ValueError(f"state entry {work_id}.latest must be an object")

        health = raw_state_entry.get("health", {})
        if health is None:
            health = {}
        if not isinstance(health, Mapping):
            raise ValueError(f"state entry {work_id}.health must be an object")

        partial_failure = partial_failure or int(health.get("consecutive_failures") or 0) > 0
        rendered_works.append(render_work_line(work_id, latest))

    if not rendered_works or all(line.startswith("（未取得）") for line in rendered_works):
        lines.append(EMPTY_LINE)
    else:
        lines.extend(rendered_works)

    if partial_failure:
        lines.extend(["", PARTIAL_FAILURE_WARNING])
    return lines


def build_latest_query_response(
    watchlist: Mapping[str, object],
    state: Mapping[str, object],
    *,
    timezone_name: Optional[str] = None,
) -> str:
    return "\n".join(build_latest_query_lines(watchlist, state, timezone_name=timezone_name))


def handle_latest_query(
    message_content: object,
    *,
    watchlist_path: Optional[str] = None,
    state_path: Optional[str] = None,
    timezone_name: Optional[str] = None,
    watchlist_loader: Callable[[Optional[str]], Dict[str, object]] = load_watchlist,
    state_loader: Callable[[Optional[str]], Dict[str, object]] = load_state,
) -> Optional[str]:
    normalized = str(message_content or "").strip()
    if normalized != LATEST_COMMAND:
        return None
    watchlist = watchlist_loader(watchlist_path)
    state = state_loader(state_path)
    return build_latest_query_response(
        watchlist,
        state,
        timezone_name=timezone_name,
    )
