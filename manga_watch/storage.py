import json
import os
import re
from typing import Dict, Mapping, Optional

DEFAULT_WATCHLIST_PATH = os.path.join(os.path.dirname(__file__), "watchlist.json")
DEFAULT_STATE_PATH = os.path.join(os.path.dirname(__file__), "state.json")

WATCHLIST_VERSION = 2
STATE_VERSION = 2

_LATEST_RUNTIME_TO_STORAGE = {
    "workId": "work_id",
    "latestKey": "latest_key",
    "seriesTitle": "series_title",
    "episodeCode": "episode_code",
    "episodeTitle": "episode_title",
    "pageTitle": "page_title",
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
    return {"version": STATE_VERSION, "works": {}, "last_run_at": None}


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
    normalized = {
        "id": work_id,
        "source": source,
        "seed_url": seed_url,
        "enabled": enabled,
        "notification_policy": policy,
    }
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
    allowed_update_types = policy.get("allowed_update_types")
    if allowed_update_types is not None:
        if not isinstance(allowed_update_types, list):
            raise ValueError(
                f"watchlist entry {work_id} notification_policy.allowed_update_types must be a list or null"
            )
        allowed_update_types = [str(item) for item in allowed_update_types]
    return {
        "mode": mode,
        "allowed_update_types": allowed_update_types,
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

    health = normalize_health(entry.get("health"), work_id)
    normalized: Dict[str, object] = {
        "latest": dict(latest),
        "history": list(history),
        "health": health,
    }
    for key, value in entry.items():
        if key in normalized or value is None:
            continue
        normalized[key] = value
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


def normalize_optional_int(value: object) -> Optional[int]:
    if value is None:
        return None
    return int(value)


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
