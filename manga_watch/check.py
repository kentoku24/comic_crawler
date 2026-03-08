#!/usr/bin/env python3
import json
import sys
import time
from typing import Dict, Mapping, Optional, Sequence, Tuple

from manga_watch.sources import (
    DEFAULT_ADAPTERS,
    HttpClient,
    RequestsHttpClient,
    SourceAdapter,
    WorkDescriptor,
    fetch_latest_for_work,
    normalize_seed_url,
)
from manga_watch.sources.base import SourceParseError
from manga_watch.sources.comic_action import extract_comic_action_series_id
from manga_watch.storage import (
    history_retention_for_work,
    latest_runtime_to_storage,
    latest_storage_to_runtime,
    load_state,
    load_watchlist,
    save_state,
    trim_history,
    unread_event_ids_in_order,
)


class CheckRunError(RuntimeError):
    def __init__(self, stage: str, exc: Exception, result: Mapping[str, object]):
        super().__init__(f"{stage}: {exc}")
        self.stage = stage
        self.result = dict(result)
        self.original_error = exc


def _selected_adapters(adapters: Optional[Sequence[SourceAdapter]]) -> Sequence[SourceAdapter]:
    return DEFAULT_ADAPTERS if adapters is None else adapters


def item_id_for_state(item: Mapping[str, object]) -> str:
    return str(item.get("workId") or item.get("series") or item["seedUrl"])


def latest_id_for_state(latest: Mapping[str, object]) -> str:
    return str(latest.get("latestKey") or latest.get("episodeCode") or latest.get("url") or "")


def merge_latest_metadata(
    previous_latest: Mapping[str, object],
    latest: Mapping[str, object],
) -> Dict[str, object]:
    merged = dict(previous_latest)
    for key, value in latest.items():
        if value is None:
            continue
        if key in ("seriesTitle", "episodeTitle", "pageTitle"):
            if value and value != merged.get(key):
                merged[key] = value
            continue
        if not merged.get(key):
            merged[key] = value
    return merged


def success_health(previous_entry: Optional[Mapping[str, object]], *, seen_at: int) -> Dict[str, object]:
    health = dict((previous_entry or {}).get("health", {}) or {})
    health["last_checked_at"] = seen_at
    health["last_success_at"] = seen_at
    health["consecutive_failures"] = 0
    return health


def unread_state_for_entry(previous_entry: Optional[Mapping[str, object]]) -> Dict[str, object]:
    unread = dict((previous_entry or {}).get("unread", {}) or {})
    event_ids = unread.get("event_ids")
    if not isinstance(event_ids, list):
        event_ids = []
    unread["event_ids"] = [str(event_id) for event_id in event_ids]
    return unread


def sync_history_event(
    history,
    latest: Mapping[str, object],
    *,
    seen_at: int,
    insert_if_missing: bool,
):
    event_id = latest_id_for_state(latest)
    if not event_id:
        return list(history), False

    updated_history = []
    found = False
    for event in history:
        if str(event.get("event_id")) != event_id:
            updated_history.append(dict(event))
            continue
        found = True
        merged_event = dict(event)
        previous_latest = latest_storage_to_runtime(event.get("latest", {}) or {})
        merged_event["latest"] = latest_runtime_to_storage(merge_latest_metadata(previous_latest, latest))
        if merged_event.get("seen_at") is None:
            merged_event["seen_at"] = seen_at
        updated_history.append(merged_event)

    if found or not insert_if_missing:
        return updated_history, False

    updated_history.append(
        {
            "event_id": event_id,
            "seen_at": seen_at,
            "latest": latest_runtime_to_storage(latest),
        }
    )
    return updated_history, True


def apply_item_transition(
    item_id: str,
    previous_entry: Optional[Mapping[str, object]],
    latest: Mapping[str, object],
    *,
    seen_at: int,
    history_retention: int,
) -> Tuple[Dict[str, object], Optional[Dict[str, object]]]:
    latest_copy = dict(latest)
    latest_copy.setdefault("workId", item_id)
    history = list((previous_entry or {}).get("history", []) or [])
    unread = unread_state_for_entry(previous_entry)
    unread_event_ids = unread_event_ids_in_order(history, unread)
    if not previous_entry or not previous_entry.get("latest"):
        history, unread_event_ids = trim_history(history, unread_event_ids, history_retention)
        return {
            "latest": latest_runtime_to_storage(latest_copy),
            "history": history,
            "unread": {"event_ids": unread_event_ids},
            "health": success_health(previous_entry, seen_at=seen_at),
        }, None

    previous_latest = latest_storage_to_runtime(previous_entry.get("latest", {}) or {})
    previous_latest_id = latest_id_for_state(previous_latest)
    latest_id = latest_id_for_state(latest_copy)
    if previous_latest_id != latest_id:
        history, inserted = sync_history_event(
            history,
            latest_copy,
            seen_at=seen_at,
            insert_if_missing=True,
        )
        if inserted and latest_id not in unread_event_ids:
            unread_event_ids.append(latest_id)
        history, unread_event_ids = trim_history(history, unread_event_ids, history_retention)
        return (
            {
                "latest": latest_runtime_to_storage(latest_copy),
                "history": history,
                "unread": {"event_ids": unread_event_ids},
                "health": success_health(previous_entry, seen_at=seen_at),
            },
            {"id": item_id, "from": previous_latest, "to": latest_copy},
        )

    merged_latest = merge_latest_metadata(previous_latest, latest_copy)
    history, _ = sync_history_event(
        history,
        merged_latest,
        seen_at=seen_at,
        insert_if_missing=False,
    )
    history, unread_event_ids = trim_history(history, unread_event_ids, history_retention)
    return (
        {
            "latest": latest_runtime_to_storage(merged_latest),
            "history": history,
            "unread": {"event_ids": unread_event_ids},
            "health": success_health(previous_entry, seen_at=seen_at),
        },
        None,
    )


def failure_entry(
    previous_entry: Optional[Mapping[str, object]],
    *,
    seen_at: int,
    history_retention: int,
) -> Dict[str, object]:
    previous_entry = previous_entry or {}
    health = dict(previous_entry.get("health", {}) or {})
    health["last_checked_at"] = seen_at
    health["last_success_at"] = health.get("last_success_at")
    health["consecutive_failures"] = int(health.get("consecutive_failures") or 0) + 1
    history = list(previous_entry.get("history", []) or [])
    unread_event_ids = unread_event_ids_in_order(history, unread_state_for_entry(previous_entry))
    history, unread_event_ids = trim_history(history, unread_event_ids, history_retention)
    return {
        "latest": dict(previous_entry.get("latest", {}) or {}),
        "history": history,
        "unread": {"event_ids": unread_event_ids},
        "health": health,
    }


def empty_errors() -> Dict[str, list]:
    return {"sources": [], "run": []}


def source_error_record(
    url: str,
    *,
    item_id: Optional[str],
    phase: str,
    exc: Exception,
) -> Dict[str, str]:
    error = {
        "url": url,
        "phase": phase,
        "kind": "parse" if isinstance(exc, SourceParseError) else "runtime",
        "errorType": exc.__class__.__name__,
        "message": str(exc),
    }
    if item_id:
        error["id"] = item_id
    return error


def run_error_record(stage: str, exc: Exception) -> Dict[str, str]:
    return {
        "stage": stage,
        "kind": "runtime",
        "errorType": exc.__class__.__name__,
        "message": str(exc),
    }


def normalize_item(url: str, adapters: Optional[Sequence[SourceAdapter]] = None):
    work = normalize_seed_url(url, adapters=_selected_adapters(adapters))
    return work.to_dict()


def stable_work_id_for_item(
    item: Mapping[str, object],
    *,
    http_client: Optional[HttpClient] = None,
) -> str:
    source = str(item.get("source") or "")
    if source != "comic-action":
        return item_id_for_state(item)

    seed_url = str(item.get("seedUrl") or "")
    if not seed_url:
        raise RuntimeError("comic-action: seedUrl is required to derive work_id")
    client = http_client or RequestsHttpClient()
    html = client.get_text(seed_url)
    series_id = extract_comic_action_series_id(html)
    if not series_id:
        raise RuntimeError("comic-action: series_id not found")
    return f"comic-action:{series_id}"


def build_watchlist_entry(
    url: str,
    adapters: Optional[Sequence[SourceAdapter]] = None,
    http_client: Optional[HttpClient] = None,
) -> Dict[str, object]:
    item = normalize_item(url, adapters=adapters)
    return {
        "id": stable_work_id_for_item(item, http_client=http_client),
        "source": str(item["source"]),
        "seed_url": str(item["seedUrl"]),
        "enabled": True,
        "notification_policy": {
            "mode": "all",
            "allowed_update_types": None,
        },
    }


def compute_latest(
    item,
    adapters: Optional[Sequence[SourceAdapter]] = None,
    http_client: Optional[HttpClient] = None,
):
    work = WorkDescriptor.from_dict(item)
    latest = fetch_latest_for_work(
        work,
        adapters=_selected_adapters(adapters),
        http_client=http_client,
    )
    return latest.to_dict()


def ensure_watchlist_contract(entry: Mapping[str, object], item: Mapping[str, object]) -> None:
    if str(entry["source"]) != str(item.get("source") or ""):
        raise RuntimeError(
            f"watchlist entry {entry['id']} source drifted: expected {entry['source']}, got {item.get('source')}"
        )


def run_check(
    watchlist_path: str,
    *,
    adapters: Optional[Sequence[SourceAdapter]] = None,
    http_client: Optional[HttpClient] = None,
):
    updates = []
    errors = empty_errors()
    result = {"updates": updates, "errors": errors}
    try:
        watchlist = load_watchlist(watchlist_path)
    except Exception as exc:
        errors["run"].append(run_error_record("load_watchlist", exc))
        raise CheckRunError("load_watchlist", exc, result) from exc

    try:
        state = load_state()
    except Exception as exc:
        errors["run"].append(run_error_record("load_state", exc))
        raise CheckRunError("load_state", exc, result) from exc

    works_state = state.setdefault("works", {})
    now = int(time.time())

    for entry in watchlist["works"]:
        if not entry["enabled"]:
            continue

        item_id = str(entry["id"])
        item = None
        try:
            item = normalize_item(str(entry["seed_url"]), adapters=adapters)
            ensure_watchlist_contract(entry, item)
            item["workId"] = item_id
            latest = compute_latest(item, adapters=adapters, http_client=http_client)
        except Exception as exc:
            phase = "normalize" if item is None else "fetch_latest"
            errors["sources"].append(
                source_error_record(
                    str(entry["seed_url"]),
                    item_id=item_id,
                    phase=phase,
                    exc=exc,
                )
            )
            works_state[item_id] = failure_entry(
                works_state.get(item_id),
                seen_at=now,
                history_retention=history_retention_for_work(entry),
            )
            continue

        next_entry, update = apply_item_transition(
            item_id,
            works_state.get(item_id),
            latest,
            seen_at=now,
            history_retention=history_retention_for_work(entry),
        )
        works_state[item_id] = next_entry
        if update is not None:
            updates.append(update)

    state["last_run_at"] = now
    try:
        save_state(state)
    except Exception as exc:
        errors["run"].append(run_error_record("save_state", exc))
        raise CheckRunError("save_state", exc, result) from exc

    return result


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: check.py <watchlist.json>", file=sys.stderr)
        return 2

    try:
        result = run_check(argv[0])
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except CheckRunError as exc:
        print(json.dumps(exc.result, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
