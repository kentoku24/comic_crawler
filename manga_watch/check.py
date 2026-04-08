#!/usr/bin/env python3
import argparse
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import json
import os
import re
import sys
import time
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from manga_watch.sources import (
    HttpClient,
    REGISTERED_ADAPTERS,
    RequestsHttpClient,
    SourceAdapter,
    WorkDescriptor,
    fetch_latest_for_work,
    normalize_seed_url,
)
from manga_watch.sources.base import SourceParseError
from manga_watch.sources.champion_cross import (
    extract_champion_cross_series_hash,
    extract_champion_cross_series_hash_from_seed_url,
)
from manga_watch.sources.comic_action import (
    extract_comic_action_series_id,
    extract_comic_action_series_id_from_seed_url,
)
from manga_watch.sources.comic_earthstar import (
    canonical_comic_earthstar_series_feed_url,
    extract_comic_earthstar_series_feed_url,
    extract_comic_earthstar_series_id,
    extract_comic_earthstar_series_id_from_seed_url,
)
from manga_watch.sources.comicborder import (
    canonical_comicborder_series_feed_url,
    extract_comicborder_series_feed_url,
    extract_comicborder_series_id,
    extract_comicborder_series_id_from_seed_url,
)
from manga_watch.sources.firecross import extract_firecross_series_id
from manga_watch.sources.shonenjumpplus import (
    canonical_shonenjumpplus_series_feed_url,
    extract_shonenjumpplus_series_feed_url,
    extract_shonenjumpplus_series_id,
    extract_shonenjumpplus_series_id_from_seed_url,
)
from manga_watch.storage import (
    NOTIFICATION_POLICY_MODE_ALL,
    evaluate_notification_policy,
    history_retention_for_work,
    latest_runtime_to_storage,
    latest_storage_to_runtime,
    load_state,
    load_watchlist,
    save_state,
    trim_history,
    unread_event_ids_in_order,
)
from manga_watch.update_classification import DEFAULT_NOTIFY_UPDATE_TYPES, SUPPRESSED_UPDATE_TYPES

DEFAULT_REQUEST_TIMEOUT = 25
DEFAULT_RETRY_COUNT = 2
DEFAULT_RETRY_BACKOFF = 0.5
DEFAULT_MAX_WORKERS = 4
DEFAULT_MAX_WORKERS_PER_HOST = 2
DEFAULT_NOTIFICATION_POLICY = {
    "mode": NOTIFICATION_POLICY_MODE_ALL,
    "allowed_update_types": None,
}
EPISODE_NUMBER_PATTERNS = (
    re.compile(r"第\s*(\d+)\s*話"),
    re.compile(r"\bEpisode\s+(\d+)\b", re.IGNORECASE),
    re.compile(r"\bEp\.?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"#\s*(\d+)"),
)


class CheckRunError(RuntimeError):
    def __init__(self, stage: str, exc: Exception, result: Mapping[str, object]):
        super().__init__(f"{stage}: {exc}")
        self.stage = stage
        self.result = dict(result)
        self.original_error = exc


def _read_int_env(name: str, default: int, *, minimum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = int(raw)
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _read_float_env(name: str, default: float, *, minimum: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = float(raw)
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


@dataclass(frozen=True)
class HttpConfig:
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT
    retry_count: int = DEFAULT_RETRY_COUNT
    retry_backoff: float = DEFAULT_RETRY_BACKOFF
    max_workers: int = DEFAULT_MAX_WORKERS
    max_workers_per_host: int = DEFAULT_MAX_WORKERS_PER_HOST

    @classmethod
    def from_env(cls) -> "HttpConfig":
        return cls(
            request_timeout=_read_int_env(
                "MANGA_WATCH_HTTP_TIMEOUT",
                DEFAULT_REQUEST_TIMEOUT,
                minimum=1,
            ),
            retry_count=_read_int_env(
                "MANGA_WATCH_HTTP_RETRIES",
                DEFAULT_RETRY_COUNT,
                minimum=0,
            ),
            retry_backoff=_read_float_env(
                "MANGA_WATCH_HTTP_RETRY_BACKOFF",
                DEFAULT_RETRY_BACKOFF,
                minimum=0.0,
            ),
            max_workers=_read_int_env(
                "MANGA_WATCH_HTTP_WORKERS",
                DEFAULT_MAX_WORKERS,
                minimum=1,
            ),
            max_workers_per_host=_read_int_env(
                "MANGA_WATCH_HTTP_WORKERS_PER_HOST",
                DEFAULT_MAX_WORKERS_PER_HOST,
                minimum=1,
            ),
        )


@dataclass(frozen=True)
class SourceResult:
    url: str
    item_id: str
    latest: Optional[Dict[str, object]] = None
    error: Optional[Dict[str, str]] = None


def _selected_adapters(adapters: Optional[Sequence[SourceAdapter]]) -> Sequence[SourceAdapter]:
    return REGISTERED_ADAPTERS if adapters is None else adapters


def item_id_for_state(item: Mapping[str, object]) -> str:
    return str(item.get("workId") or item.get("series") or item["seedUrl"])


def latest_id_for_state(latest: Mapping[str, object]) -> str:
    return str(latest.get("latestKey") or latest.get("latest_key") or "")


def update_type_for_latest(latest: Mapping[str, object]) -> str:
    update_type = latest.get("update_type")
    if isinstance(update_type, str) and update_type:
        return update_type
    return "unknown"


def default_notify_for_latest(latest: Mapping[str, object]) -> Optional[bool]:
    if "default_notify" in latest and latest.get("default_notify") is not None:
        return bool(latest.get("default_notify"))

    update_type = latest.get("update_type")
    if update_type in DEFAULT_NOTIFY_UPDATE_TYPES:
        return True
    if update_type in SUPPRESSED_UPDATE_TYPES:
        return False
    return None


def notification_metadata(
    latest: Mapping[str, object],
    *,
    notification_policy: Optional[Mapping[str, object]],
) -> Dict[str, object]:
    effective_policy = DEFAULT_NOTIFICATION_POLICY if notification_policy is None else notification_policy
    if not isinstance(effective_policy, Mapping):
        raise ValueError("notification_policy must be an object")
    return evaluate_notification_policy(
        effective_policy,
        update_type=update_type_for_latest(latest),
    )


def update_event_metadata(latest: Mapping[str, object]) -> Dict[str, object]:
    metadata: Dict[str, object] = {}
    update_type = latest.get("update_type")
    if update_type:
        metadata["update_type"] = str(update_type)

    classification_reason = latest.get("classification_reason")
    if classification_reason:
        metadata["classification_reason"] = str(classification_reason)

    default_notify = default_notify_for_latest(latest)
    if default_notify is not None:
        metadata["default_notify"] = default_notify

    return metadata


def merge_latest_metadata(
    previous_latest: Mapping[str, object],
    latest: Mapping[str, object],
) -> Dict[str, object]:
    merged = dict(previous_latest)
    for key, value in latest.items():
        if value is None:
            continue
        if key in (
            "seriesTitle",
            "episodeTitle",
            "pageTitle",
            "update_type",
            "classification_reason",
        ):
            if value and value != merged.get(key):
                merged[key] = value
            continue
        if key == "default_notify":
            if value != merged.get(key):
                merged[key] = bool(value)
            continue
        if not merged.get(key):
            merged[key] = value

    next_update_label = latest.get("nextUpdateLabel")
    if next_update_label is None and "nextUpdateLabel" not in latest:
        next_update_label = latest.get("next_update_label")

    if "nextUpdateLabel" in latest or "next_update_label" in latest:
        merged.pop("nextUpdateLabel", None)
        merged.pop("next_update_label", None)
        normalized_next_update_label = str(next_update_label or "").strip()
        if normalized_next_update_label:
            merged["nextUpdateLabel"] = normalized_next_update_label
    else:
        merged.pop("nextUpdateLabel", None)
        merged.pop("next_update_label", None)

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


def previous_series_metadata(previous_entry: Optional[Mapping[str, object]]) -> Dict[str, str]:
    if not isinstance(previous_entry, Mapping):
        return {}

    latest = latest_storage_to_runtime(previous_entry.get("latest", {}) or {})
    series_title = latest.get("seriesTitle") or latest.get("series_title")
    series = latest.get("series")
    result: Dict[str, str] = {}
    if isinstance(series_title, str) and series_title:
        result["seriesTitle"] = series_title
    if isinstance(series, str) and series:
        result["series"] = series

    history = previous_entry.get("history", [])
    if not isinstance(history, list):
        return result

    for event in reversed(history):
        if not isinstance(event, Mapping):
            continue
        candidates = [event.get("latest")]
        gap = event.get("gap")
        if isinstance(gap, Mapping):
            candidates.append(gap.get("from_latest"))
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            runtime_candidate = latest_storage_to_runtime(candidate)
            candidate_series_title = runtime_candidate.get("seriesTitle") or runtime_candidate.get("series_title")
            candidate_series = runtime_candidate.get("series")
            if "seriesTitle" not in result and isinstance(candidate_series_title, str) and candidate_series_title:
                result["seriesTitle"] = candidate_series_title
            if "series" not in result and isinstance(candidate_series, str) and candidate_series:
                result["series"] = candidate_series
            if "seriesTitle" in result and "series" in result:
                return result
    return result


def backfill_series_metadata(
    latest: Mapping[str, object],
    previous_entry: Optional[Mapping[str, object]],
) -> Dict[str, object]:
    merged = dict(latest)
    for key, value in previous_series_metadata(previous_entry).items():
        if not merged.get(key):
            merged[key] = value
    return merged


def episode_label_candidates(latest: Mapping[str, object]) -> List[str]:
    candidates: List[str] = []
    for key in ("episodeTitle", "pageTitle", "episode_title", "page_title"):
        value = latest.get(key)
        if not isinstance(value, str):
            continue
        label = value.strip()
        if label and label not in candidates:
            candidates.append(label)
    return candidates


def episode_number_for_latest(latest: Mapping[str, object]) -> Optional[int]:
    for label in episode_label_candidates(latest):
        for pattern in EPISODE_NUMBER_PATTERNS:
            match = pattern.search(label)
            if match:
                return int(match.group(1))
    return None


def build_history_gap(
    previous_latest: Mapping[str, object],
    latest: Mapping[str, object],
) -> Dict[str, object]:
    gap: Dict[str, object] = {
        "from_latest": latest_runtime_to_storage(previous_latest),
        "multiple_updates": None,
        "estimation_basis": "previous_latest_only",
    }

    previous_episode_number = episode_number_for_latest(previous_latest)
    latest_episode_number = episode_number_for_latest(latest)
    if previous_episode_number is None or latest_episode_number is None:
        return gap
    if latest_episode_number <= previous_episode_number:
        return gap

    estimated_new_episode_count = latest_episode_number - previous_episode_number
    gap["estimated_new_episode_count"] = estimated_new_episode_count
    gap["multiple_updates"] = estimated_new_episode_count > 1
    gap["estimation_basis"] = "episode_title_number"
    return gap


def sync_history_event(
    history,
    latest: Mapping[str, object],
    *,
    seen_at: int,
    insert_if_missing: bool,
    new_event: Optional[Mapping[str, object]] = None,
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
        dict(
            new_event
            or {
            "event_id": event_id,
            "seen_at": seen_at,
            "latest": latest_runtime_to_storage(latest),
            }
        )
    )
    return updated_history, True


def apply_item_transition(
    item_id: str,
    previous_entry: Optional[Mapping[str, object]],
    latest: Mapping[str, object],
    *,
    seen_at: int,
    history_retention: int,
    notification_policy: Optional[Mapping[str, object]] = None,
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
        merged_latest = backfill_series_metadata(latest_copy, previous_entry)
        next_event = {
            "event_id": latest_id,
            "seen_at": seen_at,
            "latest": latest_runtime_to_storage(merged_latest),
            "gap": build_history_gap(previous_latest, latest_copy),
        }
        history, inserted = sync_history_event(
            history,
            latest_copy,
            seen_at=seen_at,
            insert_if_missing=True,
            new_event=next_event,
        )
        if inserted and latest_id not in unread_event_ids:
            unread_event_ids.append(latest_id)
        history, unread_event_ids = trim_history(history, unread_event_ids, history_retention)
        update = {"id": item_id, "from": previous_latest, "to": latest_copy}
        update["notification"] = notification_metadata(
            latest_copy,
            notification_policy=notification_policy,
        )
        update.update(update_event_metadata(latest_copy))
        return (
            {
                "latest": latest_runtime_to_storage(merged_latest),
                "history": history,
                "unread": {"event_ids": unread_event_ids},
                "health": success_health(previous_entry, seen_at=seen_at),
            },
            update,
        )

    merged_latest = backfill_series_metadata(
        merge_latest_metadata(previous_latest, latest_copy),
        previous_entry,
    )
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
    if source == "firecross":
        stable_series = str(item.get("series") or "")
        if stable_series.startswith("firecross:"):
            return stable_series

        seed_url = str(item.get("seedUrl") or "")
        if not seed_url:
            raise RuntimeError("firecross: seedUrl is required to derive work_id")

        client = http_client or RequestsHttpClient()
        html = client.get_text(seed_url)
        series_id = extract_firecross_series_id(html)
        if not series_id:
            raise RuntimeError("firecross: series id not found")
        return f"firecross:{series_id}"

    if source == "champion-cross":
        stable_series = str(item.get("series") or "")
        if stable_series.startswith("champion-cross:"):
            return stable_series

        seed_url = str(item.get("seedUrl") or "")
        if not seed_url:
            raise RuntimeError("champion-cross: seedUrl is required to derive work_id")

        series_hash = str(item.get("seriesHash") or "") or extract_champion_cross_series_hash_from_seed_url(seed_url)
        if series_hash:
            return f"champion-cross:{series_hash}"

        client = http_client or RequestsHttpClient()
        html = client.get_text(seed_url)
        series_hash = extract_champion_cross_series_hash(html)
        if not series_hash:
            raise RuntimeError("champion-cross: series hash not found")
        return f"champion-cross:{series_hash}"

    if source == "comic-earthstar":
        stable_series = str(item.get("series") or "")
        if stable_series.startswith("comic-earthstar:"):
            return stable_series

        seed_url = str(item.get("seedUrl") or "")
        if not seed_url:
            raise RuntimeError("comic-earthstar: seedUrl is required to derive work_id")

        series_id = str(item.get("seriesId") or "") or extract_comic_earthstar_series_id_from_seed_url(seed_url)
        if series_id:
            return f"comic-earthstar:{series_id}"

        client = http_client or RequestsHttpClient()
        html = client.get_text(seed_url)
        series_id = extract_comic_earthstar_series_id(html)
        if not series_id:
            raise RuntimeError("comic-earthstar: series id not found")
        return f"comic-earthstar:{series_id}"

    if source == "comicborder":
        stable_series = str(item.get("series") or "")
        if stable_series.startswith("comicborder:"):
            return stable_series

        seed_url = str(item.get("seedUrl") or "")
        if not seed_url:
            raise RuntimeError("comicborder: seedUrl is required to derive work_id")

        series_id = str(item.get("seriesId") or "") or extract_comicborder_series_id_from_seed_url(seed_url)
        if series_id:
            return f"comicborder:{series_id}"

        client = http_client or RequestsHttpClient()
        html = client.get_text(seed_url)
        series_id = extract_comicborder_series_id(html)
        if not series_id:
            raise RuntimeError("comicborder: series id not found")
        return f"comicborder:{series_id}"

    if source == "shonenjumpplus":
        stable_series = str(item.get("series") or "")
        if stable_series.startswith("shonenjumpplus:"):
            return stable_series

        seed_url = str(item.get("seedUrl") or "")
        if not seed_url:
            raise RuntimeError("shonenjumpplus: seedUrl is required to derive work_id")

        series_id = str(item.get("seriesId") or "") or extract_shonenjumpplus_series_id_from_seed_url(seed_url)
        if series_id:
            return f"shonenjumpplus:{series_id}"

        client = http_client or RequestsHttpClient()
        html = client.get_text(seed_url)
        series_id = extract_shonenjumpplus_series_id(html)
        if not series_id:
            raise RuntimeError("shonenjumpplus: series id not found")
        return f"shonenjumpplus:{series_id}"

    if source != "comic-action":
        return item_id_for_state(item)

    stable_series = str(item.get("series") or "")
    if stable_series.startswith("comic-action:"):
        return stable_series

    seed_url = str(item.get("seedUrl") or "")
    if not seed_url:
        raise RuntimeError("comic-action: seedUrl is required to derive work_id")

    series_id = str(item.get("seriesId") or "") or extract_comic_action_series_id_from_seed_url(seed_url)
    if series_id:
        return f"comic-action:{series_id}"

    client = http_client or RequestsHttpClient()
    html = client.get_text(seed_url)
    series_id = extract_comic_action_series_id(html)
    if not series_id:
        raise RuntimeError("comic-action: series_id not found")
    return f"comic-action:{series_id}"


def canonical_seed_url_for_item(
    item: Mapping[str, object],
    *,
    http_client: Optional[HttpClient] = None,
) -> str:
    source = str(item.get("source") or "")
    seed_url = str(item.get("seedUrl") or "")
    if source == "comic-earthstar":
        series_id = str(item.get("seriesId") or "") or extract_comic_earthstar_series_id_from_seed_url(seed_url)
        if series_id:
            return canonical_comic_earthstar_series_feed_url(series_id)

        client = http_client or RequestsHttpClient()
        html = client.get_text(seed_url)
        feed_url = extract_comic_earthstar_series_feed_url(html)
        if feed_url:
            return feed_url

        series_id = extract_comic_earthstar_series_id(html)
        if not series_id:
            raise RuntimeError("comic-earthstar: series id not found")
        return canonical_comic_earthstar_series_feed_url(series_id)

    if source == "comicborder":
        series_id = str(item.get("seriesId") or "") or extract_comicborder_series_id_from_seed_url(seed_url)
        if series_id:
            return canonical_comicborder_series_feed_url(series_id)

        client = http_client or RequestsHttpClient()
        html = client.get_text(seed_url)
        feed_url = extract_comicborder_series_feed_url(html)
        if feed_url:
            return feed_url

        series_id = extract_comicborder_series_id(html)
        if not series_id:
            raise RuntimeError("comicborder: series id not found")
        return canonical_comicborder_series_feed_url(series_id)

    if source != "shonenjumpplus":
        return seed_url

    series_id = str(item.get("seriesId") or "") or extract_shonenjumpplus_series_id_from_seed_url(seed_url)
    if series_id:
        return canonical_shonenjumpplus_series_feed_url(series_id)

    client = http_client or RequestsHttpClient()
    html = client.get_text(seed_url)
    feed_url = extract_shonenjumpplus_series_feed_url(html)
    if feed_url:
        return feed_url

    series_id = extract_shonenjumpplus_series_id(html)
    if not series_id:
        raise RuntimeError("shonenjumpplus: series id not found")
    return canonical_shonenjumpplus_series_feed_url(series_id)


def build_watchlist_entry(
    url: str,
    adapters: Optional[Sequence[SourceAdapter]] = None,
    http_client: Optional[HttpClient] = None,
) -> Dict[str, object]:
    item = normalize_item(url, adapters=adapters)
    canonical_seed_url = canonical_seed_url_for_item(item, http_client=http_client)
    return {
        "id": stable_work_id_for_item(item, http_client=http_client),
        "source": str(item["source"]),
        "seed_url": canonical_seed_url,
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


def _check_watchlist_entry(
    entry: Mapping[str, object],
    *,
    adapters: Optional[Sequence[SourceAdapter]],
    http_client: Optional[HttpClient],
) -> SourceResult:
    item_id = str(entry["id"])
    seed_url = str(entry["seed_url"])
    item = None
    try:
        item = normalize_item(seed_url, adapters=adapters)
        ensure_watchlist_contract(entry, item)
        item["workId"] = item_id
        latest = compute_latest(item, adapters=adapters, http_client=http_client)
        return SourceResult(url=seed_url, item_id=item_id, latest=latest)
    except Exception as exc:
        phase = "normalize" if item is None else "fetch_latest"
        return SourceResult(
            url=seed_url,
            item_id=item_id,
            error=source_error_record(seed_url, item_id=item_id, phase=phase, exc=exc),
        )


def _collect_source_results(
    entries: Sequence[Mapping[str, object]],
    *,
    adapters: Optional[Sequence[SourceAdapter]],
    http_client: Optional[HttpClient],
    max_workers: int,
) -> List[SourceResult]:
    if not entries:
        return []
    if len(entries) == 1 or max_workers == 1:
        return [
            _check_watchlist_entry(entry, adapters=adapters, http_client=http_client)
            for entry in entries
        ]

    ordered_results: List[Optional[SourceResult]] = [None] * len(entries)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(entries))) as executor:
        futures: Dict[Future[SourceResult], int] = {}
        for index, entry in enumerate(entries):
            futures[executor.submit(
                _check_watchlist_entry,
                entry,
                adapters=adapters,
                http_client=http_client,
            )] = index

        for future, index in futures.items():
            ordered_results[index] = future.result()

    return [result for result in ordered_results if result is not None]


def run_check(
    watchlist_path: str,
    *,
    adapters: Optional[Sequence[SourceAdapter]] = None,
    http_client: Optional[HttpClient] = None,
    http_config: Optional[HttpConfig] = None,
):
    updates = []
    errors = empty_errors()
    result = {"updates": updates, "errors": errors}
    try:
        http_config = http_config or HttpConfig.from_env()
    except Exception as exc:
        errors["run"].append(run_error_record("http_config", exc))
        raise CheckRunError("http_config", exc, result) from exc

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
    effective_http_client = http_client or RequestsHttpClient(
        timeout=http_config.request_timeout,
        retry_count=http_config.retry_count,
        retry_backoff=http_config.retry_backoff,
        max_requests_per_host=http_config.max_workers_per_host,
    )
    enabled_entries = [entry for entry in watchlist["works"] if entry["enabled"]]
    source_results = _collect_source_results(
        enabled_entries,
        adapters=adapters,
        http_client=effective_http_client,
        max_workers=http_config.max_workers,
    )

    for entry, source_result in zip(enabled_entries, source_results):
        history_retention = history_retention_for_work(entry)
        if source_result.error is not None:
            errors["sources"].append(source_result.error)
            works_state[source_result.item_id] = failure_entry(
                works_state.get(source_result.item_id),
                seen_at=now,
                history_retention=history_retention,
            )
            continue

        next_entry, update = apply_item_transition(
            source_result.item_id,
            works_state.get(source_result.item_id),
            source_result.latest or {},
            seen_at=now,
            history_retention=history_retention,
            notification_policy=entry.get("notification_policy"),
        )
        works_state[source_result.item_id] = next_entry
        if update is not None:
            updates.append(update)

    state["last_run_at"] = now
    try:
        # Persist source observations before control returns to the runner's delivery phase.
        save_state(state)
    except Exception as exc:
        errors["run"].append(run_error_record("save_state", exc))
        raise CheckRunError("save_state", exc, result) from exc

    return result


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description="Run the checker or inspect persisted monitoring status.")
    parser.add_argument("watchlist_path", nargs="?", help="watchlist path for crawl mode")
    parser.add_argument("--status", action="store_true", help="show current monitoring status without crawling")
    parser.add_argument("--format", choices=("text", "json"), help="status output format")
    parser.add_argument("--watchlist", dest="status_watchlist_path", help="watchlist path for status mode")
    parser.add_argument("--state", dest="status_state_path", help="state path for status mode")
    parser.add_argument("--now", type=int, help="override current UNIX timestamp for status mode")
    args = parser.parse_args(argv)

    if args.status:
        from manga_watch.status import build_status_report, render_status_report

        if args.watchlist_path and args.status_watchlist_path:
            parser.error("use either positional watchlist_path or --watchlist with --status")
        watchlist_path = args.status_watchlist_path or args.watchlist_path
        try:
            report = build_status_report(
                watchlist_path=watchlist_path,
                state_path=args.status_state_path,
                now=args.now,
            )
            output = render_status_report(report, output_format=args.format or "text")
        except Exception as exc:
            print(f"[status] error: {exc}", file=sys.stderr)
            return 1
        print(output)
        return 0

    if args.watchlist_path is None:
        print("usage: check.py <watchlist.json>", file=sys.stderr)
        return 2
    if args.format or args.status_watchlist_path or args.status_state_path or args.now:
        parser.error("--format, --watchlist, --state, and --now require --status")

    try:
        result = run_check(args.watchlist_path)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except CheckRunError as exc:
        print(json.dumps(exc.result, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
