import json
import os
import re
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from manga_watch.update_classification import DEFAULT_NOTIFY_UPDATE_TYPES, SUPPORTED_UPDATE_TYPES

DEFAULT_WATCHLIST_PATH = os.path.join(os.path.dirname(__file__), "watchlist.json")
DEFAULT_STATE_PATH = os.path.join(os.path.dirname(__file__), "state.json")

WATCHLIST_VERSION = 2
STATE_VERSION = 2
DEFAULT_HISTORY_RETENTION = 20
NOTIFICATION_POLICY_MODE_ALL = "all"
NOTIFICATION_POLICY_MODE_IMPORTANT_ONLY = "important_only"
NOTIFICATION_POLICY_MODE_MUTE = "mute"
SUPPORTED_NOTIFICATION_POLICY_MODES = {
    NOTIFICATION_POLICY_MODE_ALL,
    NOTIFICATION_POLICY_MODE_IMPORTANT_ONLY,
    NOTIFICATION_POLICY_MODE_MUTE,
}
SUPPORTED_NOTIFICATION_POLICY_UPDATE_TYPES = tuple(SUPPORTED_UPDATE_TYPES)

_LATEST_RUNTIME_TO_STORAGE = {
    "workId": "work_id",
    "latestKey": "latest_key",
    "seriesTitle": "series_title",
    "episodeCode": "episode_code",
    "episodeTitle": "episode_title",
    "pageTitle": "page_title",
    "update_type": "update_type",
    "classification_reason": "classification_reason",
    "default_notify": "default_notify",
}
_LATEST_STORAGE_TO_RUNTIME = {value: key for key, value in _LATEST_RUNTIME_TO_STORAGE.items()}


def get_watchlist_path() -> str:
    return os.environ.get(
        "MANGA_WATCH_WATCHLIST",
        os.environ.get("MANGA_WATCH_URLS", DEFAULT_WATCHLIST_PATH),
    )


def get_state_path() -> str:
    return os.environ.get("MANGA_WATCH_STATE", DEFAULT_STATE_PATH)


def default_watchlist() -> Dict[str, object]:
    return {"version": WATCHLIST_VERSION, "works": []}


def default_state() -> Dict[str, object]:
    return {
        "version": STATE_VERSION,
        "works": {},
        "last_run_at": None,
        "notification_outbox": [],
    }


def load_watchlist(path: Optional[str] = None) -> Dict[str, object]:
    watchlist_path = path or get_watchlist_path()
    with open(watchlist_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return validate_watchlist(payload)


def load_state(path: Optional[str] = None) -> Dict[str, object]:
    state_path = path or get_state_path()
    if not os.path.exists(state_path):
        return default_state()
    with open(state_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return validate_state(payload)


def save_state(state: Mapping[str, object], path: Optional[str] = None) -> None:
    atomic_write_json(path or get_state_path(), validate_state(state))


def save_watchlist(watchlist: Mapping[str, object], path: Optional[str] = None) -> None:
    atomic_write_json(path or get_watchlist_path(), validate_watchlist(watchlist))


def atomic_write_json(path: str, payload: Mapping[str, object]) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def validate_watchlist(payload: Mapping[str, object]) -> Dict[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("watchlist payload must be an object")
    if payload.get("version") != WATCHLIST_VERSION:
        raise ValueError(f"watchlist version must be {WATCHLIST_VERSION}")
    works = payload.get("works")
    if not isinstance(works, list):
        raise ValueError("watchlist.works must be a list")

    normalized_works = []
    seen_ids = set()
    for work in works:
        normalized = normalize_watchlist_entry(work)
        work_id = normalized["id"]
        if work_id in seen_ids:
            raise ValueError(f"duplicate watchlist id: {work_id}")
        seen_ids.add(work_id)
        normalized_works.append(normalized)
    return {"version": WATCHLIST_VERSION, "works": normalized_works}


def normalize_watchlist_entry(entry: Mapping[str, object]) -> Dict[str, object]:
    if not isinstance(entry, Mapping):
        raise ValueError("watchlist entry must be an object")
    work_id = str(entry.get("id") or "").strip()
    source = str(entry.get("source") or "").strip()
    seed_url = str(entry.get("seed_url") or "").strip()
    if not work_id:
        raise ValueError("watchlist entry missing id")
    if not source:
        raise ValueError(f"watchlist entry {work_id} missing source")
    if not seed_url:
        raise ValueError(f"watchlist entry {work_id} missing seed_url")
    enabled = entry.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError(f"watchlist entry {work_id} enabled must be boolean")
    policy = normalize_notification_policy(entry.get("notification_policy"), work_id)
    history_retention = normalize_optional_history_retention(
        entry.get("history_retention"),
        field_name=f"watchlist entry {work_id} history_retention",
    )
    normalized = {
        "id": work_id,
        "source": source,
        "seed_url": seed_url,
        "enabled": enabled,
        "notification_policy": policy,
    }
    if history_retention is not None:
        normalized["history_retention"] = history_retention
    for key, value in entry.items():
        if key in normalized or value is None:
            continue
        normalized[key] = value
    return normalized


def normalize_notification_policy(policy: object, work_id: str) -> Dict[str, object]:
    if not isinstance(policy, Mapping):
        raise ValueError(f"watchlist entry {work_id} notification_policy must be an object")
    mode = str(policy.get("mode") or "").strip()
    if not mode:
        raise ValueError(f"watchlist entry {work_id} notification_policy.mode is required")
    if mode not in SUPPORTED_NOTIFICATION_POLICY_MODES:
        supported_modes = ", ".join(sorted(SUPPORTED_NOTIFICATION_POLICY_MODES))
        raise ValueError(
            f"watchlist entry {work_id} notification_policy.mode must be one of: {supported_modes}"
        )
    allowed_update_types = normalize_allowed_update_types(
        policy.get("allowed_update_types"),
        field_name=f"watchlist entry {work_id} notification_policy.allowed_update_types",
    )
    return {
        "mode": mode,
        "allowed_update_types": allowed_update_types,
    }


def normalize_allowed_update_types(
    allowed_update_types: object,
    *,
    field_name: str,
) -> Optional[List[str]]:
    if allowed_update_types is None:
        return None
    if not isinstance(allowed_update_types, list):
        raise ValueError(f"{field_name} must be a list or null")

    normalized_allowed_update_types: List[str] = []
    seen_update_types = set()
    for item in allowed_update_types:
        normalized_update_type = str(item).strip()
        if not normalized_update_type or normalized_update_type in seen_update_types:
            continue
        if normalized_update_type not in SUPPORTED_NOTIFICATION_POLICY_UPDATE_TYPES:
            supported_update_types = ", ".join(SUPPORTED_NOTIFICATION_POLICY_UPDATE_TYPES)
            raise ValueError(
                f"{field_name} must contain only supported update types: {supported_update_types}"
            )
        seen_update_types.add(normalized_update_type)
        normalized_allowed_update_types.append(normalized_update_type)
    return normalized_allowed_update_types


def evaluate_notification_policy(
    policy: Mapping[str, object],
    *,
    update_type: object,
) -> Dict[str, object]:
    mode = str(policy.get("mode") or "").strip()
    if mode not in SUPPORTED_NOTIFICATION_POLICY_MODES:
        raise ValueError(f"unsupported notification_policy.mode: {mode or '<empty>'}")

    normalized_allowed_update_types = normalize_allowed_update_types(
        policy.get("allowed_update_types"),
        field_name="notification_policy.allowed_update_types",
    )

    normalized_update_type = str(update_type or "").strip() or "unknown"
    if normalized_allowed_update_types is not None:
        should_notify = normalized_update_type in normalized_allowed_update_types
        reason = (
            f"allowed_update_types override matched {normalized_update_type}"
            if should_notify
            else f"allowed_update_types override did not include {normalized_update_type}"
        )
        return {
            "mode": mode,
            "allowed_update_types": normalized_allowed_update_types,
            "should_notify": should_notify,
            "applied_via": "allowed_update_types",
            "reason": reason,
        }

    if mode == NOTIFICATION_POLICY_MODE_ALL:
        return {
            "mode": mode,
            "allowed_update_types": None,
            "should_notify": True,
            "applied_via": "mode",
            "reason": "mode=all notifies every update_type",
        }

    if mode == NOTIFICATION_POLICY_MODE_MUTE:
        return {
            "mode": mode,
            "allowed_update_types": None,
            "should_notify": False,
            "applied_via": "mode",
            "reason": "mode=mute suppresses every update_type",
        }

    should_notify = normalized_update_type in DEFAULT_NOTIFY_UPDATE_TYPES
    return {
        "mode": mode,
        "allowed_update_types": None,
        "should_notify": should_notify,
        "applied_via": "mode",
        "reason": (
            f"mode=important_only allows {normalized_update_type}"
            if should_notify
            else f"mode=important_only suppresses {normalized_update_type}"
        ),
    }


def validate_state(payload: Mapping[str, object]) -> Dict[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("state payload must be an object")
    if payload.get("version") != STATE_VERSION:
        raise ValueError(f"state version must be {STATE_VERSION}")
    works = payload.get("works")
    if not isinstance(works, Mapping):
        raise ValueError("state.works must be an object")

    normalized_works: Dict[str, object] = {}
    for work_id, entry in works.items():
        normalized_works[str(work_id)] = normalize_state_entry(str(work_id), entry)

    state = {
        "version": STATE_VERSION,
        "works": normalized_works,
        "last_run_at": normalize_optional_int(payload.get("last_run_at")),
        "notification_outbox": normalize_notification_outbox(payload.get("notification_outbox")),
    }
    for key, value in payload.items():
        if key in state or value is None:
            continue
        state[key] = value
    return state


def normalize_state_entry(work_id: str, entry: object) -> Dict[str, object]:
    if not isinstance(entry, Mapping):
        raise ValueError(f"state entry {work_id} must be an object")
    latest = entry.get("latest")
    if latest is None:
        latest = {}
    if not isinstance(latest, Mapping):
        raise ValueError(f"state entry {work_id}.latest must be an object")

    history = entry.get("history")
    if history is None:
        history = []
    if not isinstance(history, list):
        raise ValueError(f"state entry {work_id}.history must be a list")
    normalized_history = normalize_history(history, work_id)

    unread = normalize_unread(
        entry.get("unread"),
        work_id,
        normalized_history,
    )

    health = normalize_health(entry.get("health"), work_id)
    normalized: Dict[str, object] = {
        "latest": latest_runtime_to_storage(latest),
        "history": normalized_history,
        "unread": unread,
        "health": health,
    }
    for key, value in entry.items():
        if key in normalized or value is None:
            continue
        normalized[key] = value
    return normalized


def normalize_notification_outbox(outbox: object) -> List[Dict[str, object]]:
    if outbox is None:
        return []
    if not isinstance(outbox, list):
        raise ValueError("state.notification_outbox must be a list")

    normalized_entries: List[Dict[str, object]] = []
    for index, entry in enumerate(outbox):
        normalized_entries.append(normalize_notification_outbox_entry(entry, index=index))
    return normalized_entries


def normalize_notification_outbox_entry(entry: object, *, index: int) -> Dict[str, object]:
    if not isinstance(entry, Mapping):
        raise ValueError(f"state.notification_outbox[{index}] must be an object")

    event = entry.get("event")
    if not isinstance(event, Mapping):
        raise ValueError(f"state.notification_outbox[{index}].event must be an object")

    pending_backends = entry.get("pending_backends", entry.get("pendingBackends", []))
    if pending_backends is None:
        pending_backends = []
    if not isinstance(pending_backends, list):
        raise ValueError(f"state.notification_outbox[{index}].pending_backends must be a list")

    normalized_pending_backends: List[str] = []
    seen_backends = set()
    for backend in pending_backends:
        normalized_backend = str(backend).strip()
        if not normalized_backend or normalized_backend in seen_backends:
            continue
        seen_backends.add(normalized_backend)
        normalized_pending_backends.append(normalized_backend)

    attempt_count = int(entry.get("attempt_count", entry.get("attemptCount", 0)) or 0)
    if attempt_count < 0:
        raise ValueError(f"state.notification_outbox[{index}].attempt_count must be >= 0")

    normalized = {
        "event": dict(event),
        "pending_backends": normalized_pending_backends,
        "attempt_count": attempt_count,
        "last_attempted_at": normalize_optional_text(
            entry.get("last_attempted_at", entry.get("lastAttemptedAt"))
        ),
        "last_error": normalize_optional_text(entry.get("last_error", entry.get("lastError"))),
    }
    for key, value in entry.items():
        if key in {
            "event",
            "pending_backends",
            "pendingBackends",
            "attempt_count",
            "attemptCount",
            "last_attempted_at",
            "lastAttemptedAt",
            "last_error",
            "lastError",
        } or value is None:
            continue
        normalized[camel_to_snake(str(key))] = value
    return normalized


def normalize_health(health: object, work_id: str) -> Dict[str, object]:
    if health is None:
        health = {}
    if not isinstance(health, Mapping):
        raise ValueError(f"state entry {work_id}.health must be an object")
    consecutive_failures = health.get("consecutive_failures", 0)
    if consecutive_failures is None:
        consecutive_failures = 0
    consecutive_failures = int(consecutive_failures)
    if consecutive_failures < 0:
        raise ValueError(f"state entry {work_id}.health.consecutive_failures must be >= 0")
    normalized = {
        "last_checked_at": normalize_optional_int(health.get("last_checked_at")),
        "last_success_at": normalize_optional_int(health.get("last_success_at")),
        "consecutive_failures": consecutive_failures,
    }
    for key, value in health.items():
        if key in normalized or value is None:
            continue
        normalized[key] = value
    return normalized


def normalize_history(history: Sequence[object], work_id: str) -> List[Dict[str, object]]:
    normalized: Dict[str, Dict[str, object]] = {}
    ordered_ids: List[str] = []
    for event in history:
        normalized_event = normalize_history_event(event, work_id)
        event_id = str(normalized_event["event_id"])
        if event_id in normalized:
            ordered_ids.remove(event_id)
        normalized[event_id] = normalized_event
        ordered_ids.append(event_id)
    return [normalized[event_id] for event_id in ordered_ids]


def normalize_history_event(event: object, work_id: str) -> Dict[str, object]:
    if not isinstance(event, Mapping):
        raise ValueError(f"state entry {work_id}.history items must be objects")
    latest = event.get("latest")
    if latest is None:
        latest = {
            key: value
            for key, value in event.items()
            if key not in {"event_id", "eventId", "seen_at", "seenAt"}
        }
    if not isinstance(latest, Mapping):
        raise ValueError(f"state entry {work_id}.history.latest must be an object")
    normalized_latest = latest_runtime_to_storage(latest)
    event_id = str(
        event.get("event_id")
        or event.get("eventId")
        or normalized_latest.get("latest_key")
        or normalized_latest.get("url")
        or ""
    ).strip()
    if not event_id:
        raise ValueError(f"state entry {work_id}.history items require event_id")
    normalized = {
        "event_id": event_id,
        "seen_at": normalize_optional_int(event.get("seen_at", event.get("seenAt"))),
        "latest": normalized_latest,
    }
    for key, value in event.items():
        if key in {"event_id", "eventId", "seen_at", "seenAt", "latest"} or value is None:
            continue
        normalized[camel_to_snake(str(key))] = value
    return normalized


def normalize_unread(
    unread: object,
    work_id: str,
    history: Sequence[Mapping[str, object]],
) -> Dict[str, object]:
    if unread is None:
        unread = {}
    if not isinstance(unread, Mapping):
        raise ValueError(f"state entry {work_id}.unread must be an object")
    event_ids = unread.get("event_ids", unread.get("eventIds", []))
    if event_ids is None:
        event_ids = []
    if not isinstance(event_ids, list):
        raise ValueError(f"state entry {work_id}.unread.event_ids must be a list")
    normalized_ids: List[str] = []
    seen_ids = set()
    for event_id in event_ids:
        normalized_id = str(event_id).strip()
        if not normalized_id or normalized_id in seen_ids:
            continue
        seen_ids.add(normalized_id)
        normalized_ids.append(normalized_id)

    unread_set = set(normalized_ids)
    ordered_ids = [str(event["event_id"]) for event in history if str(event["event_id"]) in unread_set]
    normalized = {"event_ids": ordered_ids}
    for key, value in unread.items():
        if key in {"event_ids", "eventIds"} or value is None:
            continue
        normalized[camel_to_snake(str(key))] = value
    return normalized


def history_retention_for_work(entry: Mapping[str, object]) -> int:
    return int(entry.get("history_retention") or DEFAULT_HISTORY_RETENTION)


def unread_event_ids_in_order(
    history: Sequence[Mapping[str, object]],
    unread_state: Mapping[str, object],
) -> List[str]:
    unread_ids = unread_state.get("event_ids", [])
    if not isinstance(unread_ids, list):
        return []
    unread_set = {str(event_id) for event_id in unread_ids}
    return [str(event["event_id"]) for event in history if str(event["event_id"]) in unread_set]


def trim_history(
    history: Sequence[Mapping[str, object]],
    unread_event_ids: Sequence[str],
    history_retention: int,
) -> Tuple[List[Dict[str, object]], List[str]]:
    limit = max(1, int(history_retention))
    unread_set = {str(event_id) for event_id in unread_event_ids}
    read_events = [event for event in history if str(event["event_id"]) not in unread_set]
    retained_read_ids = {str(event["event_id"]) for event in read_events[-limit:]}
    trimmed_history = [
        dict(event)
        for event in history
        if str(event["event_id"]) in unread_set or str(event["event_id"]) in retained_read_ids
    ]
    ordered_unread_ids = [str(event["event_id"]) for event in trimmed_history if str(event["event_id"]) in unread_set]
    return trimmed_history, ordered_unread_ids


def normalize_optional_int(value: object) -> Optional[int]:
    if value is None:
        return None
    return int(value)


def normalize_optional_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_optional_history_retention(value: object, *, field_name: str) -> Optional[int]:
    if value is None:
        return None
    retention = int(value)
    if retention < 1:
        raise ValueError(f"{field_name} must be >= 1")
    return retention


def latest_runtime_to_storage(latest: Mapping[str, object]) -> Dict[str, object]:
    converted: Dict[str, object] = {}
    for key, value in latest.items():
        if value is None:
            continue
        converted[_latest_storage_key(key)] = value
    return converted


def latest_storage_to_runtime(latest: Mapping[str, object]) -> Dict[str, object]:
    converted: Dict[str, object] = {}
    for key, value in latest.items():
        if value is None:
            continue
        converted[_latest_runtime_key(key)] = value
    return converted


def _latest_storage_key(key: str) -> str:
    return _LATEST_RUNTIME_TO_STORAGE.get(key, camel_to_snake(key))


def _latest_runtime_key(key: str) -> str:
    return _LATEST_STORAGE_TO_RUNTIME.get(key, snake_to_camel(key))


def camel_to_snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def snake_to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)
