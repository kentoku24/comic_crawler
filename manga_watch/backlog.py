#!/usr/bin/env python3
import argparse
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from manga_watch.storage import (
    DEFAULT_HISTORY_RETENTION,
    history_retention_for_work,
    load_state,
    load_watchlist,
    save_state,
    trim_history,
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Inspect unread updates and history from state v2.")
    parser.add_argument("--state", default=None)
    parser.add_argument("--watchlist", default=None)
    parser.add_argument("--work-id")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--unread-only", action="store_true")
    mark_group = parser.add_mutually_exclusive_group()
    mark_group.add_argument("--mark-read-all", action="store_true")
    mark_group.add_argument("--mark-read-work")
    mark_group.add_argument("--mark-read", dest="mark_read_work")
    return parser.parse_args(argv)


def format_timestamp(unix_ts: Optional[int], timezone_name: str) -> str:
    if unix_ts is None:
        return "unknown"
    tz = ZoneInfo(timezone_name)
    return datetime.fromtimestamp(int(unix_ts), tz=tz).strftime("%Y-%m-%d %H:%M:%S %Z")


def latest_label(latest: Mapping[str, object], fallback: str) -> str:
    return str(
        latest.get("episode_title")
        or latest.get("episode_code")
        or latest.get("url")
        or fallback
    )


def series_label(work_id: str, latest: Mapping[str, object]) -> str:
    return str(latest.get("series_title") or latest.get("series") or work_id)


def serialize_gap(gap: object) -> Optional[Dict[str, object]]:
    if not isinstance(gap, Mapping):
        return None
    from_latest = gap.get("from_latest", {})
    if not isinstance(from_latest, Mapping):
        from_latest = {}

    serialized: Dict[str, object] = {
        "from_episode_label": latest_label(from_latest, "不明"),
        "from_url": from_latest.get("url"),
        "multiple_updates": gap.get("multiple_updates")
        if isinstance(gap.get("multiple_updates"), bool)
        else None,
        "estimation_basis": str(gap.get("estimation_basis") or "").strip() or None,
    }

    estimated_count = gap.get("estimated_new_episode_count")
    if isinstance(estimated_count, int):
        serialized["estimated_new_episode_count"] = estimated_count
    if from_latest:
        serialized["from_latest"] = dict(from_latest)

    return {key: value for key, value in serialized.items() if value is not None}


def format_gap_suffix(event: Mapping[str, object]) -> str:
    gap = event.get("gap")
    if not isinstance(gap, Mapping):
        return ""

    from_label = str(gap.get("from_episode_label") or "不明")
    estimated_count = gap.get("estimated_new_episode_count")
    if gap.get("multiple_updates") is True and isinstance(estimated_count, int):
        return f" gap from {from_label} (+{estimated_count} estimated)"
    if gap.get("multiple_updates") is None:
        return f" gap from {from_label} (count unavailable)"
    return ""


def collect_backlog(
    state: Mapping[str, object],
    *,
    work_id: Optional[str] = None,
    limit: int = 10,
    unread_only: bool = False,
    timezone_name: str = "Asia/Tokyo",
) -> Dict[str, object]:
    works = state.get("works", {})
    if not isinstance(works, Mapping):
        works = {}

    entries: List[Dict[str, object]] = []
    unread_work_count = 0
    unread_event_count = 0

    for current_work_id, raw_entry in works.items():
        current_work_id = str(current_work_id)
        if work_id and current_work_id != work_id:
            continue

        entry = raw_entry if isinstance(raw_entry, Mapping) else {}
        history = entry.get("history", [])
        unread = entry.get("unread", {})
        latest = entry.get("latest", {})

        if not isinstance(history, list):
            history = []
        if not isinstance(unread, Mapping):
            unread = {}
        if not isinstance(latest, Mapping):
            latest = {}

        unread_ids = unread.get("event_ids", [])
        if not isinstance(unread_ids, list):
            unread_ids = []
        unread_set = {str(event_id) for event_id in unread_ids}

        all_events: List[Dict[str, object]] = []
        unread_events: List[Dict[str, object]] = []
        for event in history:
            if not isinstance(event, Mapping):
                continue
            event_id = str(event.get("event_id") or "")
            if not event_id:
                continue
            event_latest = event.get("latest", {})
            if not isinstance(event_latest, Mapping):
                event_latest = {}
            serialized = {
                "event_id": event_id,
                "seen_at": event.get("seen_at"),
                "seen_at_label": format_timestamp(event.get("seen_at"), timezone_name),
                "series_title": series_label(current_work_id, event_latest),
                "episode_label": latest_label(event_latest, "不明"),
                "url": event_latest.get("url"),
                "unread": event_id in unread_set,
                "gap": serialize_gap(event.get("gap")),
            }
            all_events.append(serialized)
            if serialized["unread"]:
                unread_events.append(serialized)

        if not work_id and not all_events and not unread_set:
            continue

        if unread_events:
            unread_work_count += 1
            unread_event_count += len(unread_events)

        if unread_only and not unread_events:
            continue

        entries.append(
            {
                "work_id": current_work_id,
                "series_title": series_label(current_work_id, latest),
                "latest_label": latest_label(latest, "未取得"),
                "unread_count": len(unread_events),
                "unread_events": unread_events[-limit:] if limit else [],
                "recent_history": all_events[-limit:] if limit else [],
            }
        )

    return {
        "history_retention_default": DEFAULT_HISTORY_RETENTION,
        "unread_work_count": unread_work_count,
        "unread_event_count": unread_event_count,
        "works": entries,
    }


def mark_read(state: Dict[str, object], *, work_id: Optional[str] = None) -> Dict[str, object]:
    works = state.get("works", {})
    if not isinstance(works, dict):
        raise ValueError("state.works must be an object")

    cleared_event_count = 0
    affected_work_count = 0
    for current_work_id, raw_entry in works.items():
        current_work_id = str(current_work_id)
        if work_id and current_work_id != work_id:
            continue

        entry = raw_entry if isinstance(raw_entry, dict) else {}
        unread = entry.get("unread", {})
        if not isinstance(unread, dict):
            unread = {}
        event_ids = unread.get("event_ids", [])
        if not isinstance(event_ids, list):
            event_ids = []
        if not event_ids:
            entry["unread"] = {"event_ids": []}
            works[current_work_id] = entry
            continue

        cleared_event_count += len(event_ids)
        affected_work_count += 1
        unread["event_ids"] = []
        entry["unread"] = unread
        works[current_work_id] = entry

    state["works"] = works
    return {
        "action": "mark_read",
        "scope": work_id or "all",
        "affected_work_count": affected_work_count,
        "cleared_event_count": cleared_event_count,
    }


def history_retention_map(path: Optional[str] = None) -> Dict[str, int]:
    try:
        watchlist = load_watchlist(path)
    except Exception:
        return {}

    works = watchlist.get("works", [])
    if not isinstance(works, list):
        return {}

    retention_by_work: Dict[str, int] = {}
    for entry in works:
        if not isinstance(entry, Mapping):
            continue
        work_id = str(entry.get("id") or "").strip()
        if not work_id:
            continue
        retention_by_work[work_id] = history_retention_for_work(entry)
    return retention_by_work


def apply_history_trim(
    state: Dict[str, object],
    *,
    retention_by_work: Mapping[str, int],
    work_id: Optional[str] = None,
) -> None:
    works = state.get("works", {})
    if not isinstance(works, dict):
        return

    for current_work_id, raw_entry in works.items():
        current_work_id = str(current_work_id)
        if work_id and current_work_id != work_id:
            continue

        entry = raw_entry if isinstance(raw_entry, dict) else {}
        history = entry.get("history", [])
        unread = entry.get("unread", {})
        if not isinstance(history, list):
            history = []
        if not isinstance(unread, dict):
            unread = {}
        unread_ids = unread.get("event_ids", [])
        if not isinstance(unread_ids, list):
            unread_ids = []
        trimmed_history, ordered_unread_ids = trim_history(
            history,
            unread_ids,
            retention_by_work.get(current_work_id, DEFAULT_HISTORY_RETENTION),
        )
        unread["event_ids"] = ordered_unread_ids
        entry["history"] = trimmed_history
        entry["unread"] = unread
        works[current_work_id] = entry

    state["works"] = works


def format_backlog_text(payload: Mapping[str, object]) -> str:
    lines = [
        "Backlog Summary",
        f"Unread works: {payload['unread_work_count']}",
        f"Unread events: {payload['unread_event_count']}",
        f"History retention: keep all unread events + latest {payload['history_retention_default']} read events per work",
    ]
    works = payload.get("works", [])
    if not works:
        lines.append("No backlog entries.")
        return "\n".join(lines)

    for work in works:
        lines.extend(
            [
                "",
                f"[{work['work_id']}] {work['series_title']}",
                f"Latest: {work['latest_label']}",
                f"Unread: {work['unread_count']}",
            ]
        )
        unread_events = work.get("unread_events", [])
        if unread_events:
            lines.append("Unread events:")
            for event in unread_events:
                suffix = f" {event['url']}" if event.get("url") else ""
                suffix += format_gap_suffix(event)
                lines.append(
                    f"- {event['seen_at_label']} {event['episode_label']} ({event['event_id']}){suffix}"
                )
            continue

        recent_history = work.get("recent_history", [])
        if recent_history:
            lines.append("Recent history:")
            for event in recent_history:
                suffix = f" {event['url']}" if event.get("url") else ""
                suffix += format_gap_suffix(event)
                lines.append(
                    f"- {event['seen_at_label']} {event['episode_label']} ({event['event_id']}){suffix}"
                )
    return "\n".join(lines)


def format_mark_read_text(payload: Mapping[str, object]) -> str:
    return "\n".join(
        [
            "Mark Read Result",
            f"Scope: {payload['scope']}",
            f"Affected works: {payload['affected_work_count']}",
            f"Cleared events: {payload['cleared_event_count']}",
        ]
    )


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.limit < 0:
        print("backlog.py: --limit must be >= 0", file=sys.stderr)
        return 2

    timezone_name = os.environ.get("TZ", "Asia/Tokyo")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        print(f"backlog.py: unknown TZ value: {timezone_name}", file=sys.stderr)
        return 2

    state = load_state(args.state)

    if args.mark_read_all or args.mark_read_work:
        payload = mark_read(state, work_id=args.mark_read_work)
        apply_history_trim(
            state,
            retention_by_work=history_retention_map(args.watchlist),
            work_id=args.mark_read_work,
        )
        save_state(state, args.state)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(format_mark_read_text(payload))
        return 0

    payload = collect_backlog(
        state,
        work_id=args.work_id,
        limit=args.limit,
        unread_only=args.unread_only,
        timezone_name=timezone_name,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(format_backlog_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
