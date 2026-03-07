#!/usr/bin/env python3
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import json
import os
import sys
import time
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

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

DEFAULT_STATE_PATH = os.path.join(os.path.dirname(__file__), "state.json")
DEFAULT_REQUEST_TIMEOUT = 25
DEFAULT_RETRY_COUNT = 2
DEFAULT_RETRY_BACKOFF = 0.5
DEFAULT_MAX_WORKERS = 4
DEFAULT_MAX_WORKERS_PER_HOST = 2


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
    item_id: Optional[str] = None
    latest: Optional[Dict[str, object]] = None
    error: Optional[Dict[str, str]] = None


def get_state_path():
    return os.environ.get("MANGA_WATCH_STATE", DEFAULT_STATE_PATH)


def load_state():
    state_path = get_state_path()
    if not os.path.exists(state_path):
        return {"version": 1, "items": {}}
    with open(state_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    state_path = get_state_path()
    tmp = state_path + ".tmp"
    state_dir = os.path.dirname(state_path) or "."
    os.makedirs(state_dir, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, state_path)


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


def apply_item_transition(
    item_id: str,
    previous_entry: Optional[Mapping[str, object]],
    latest: Mapping[str, object],
    *,
    seen_at: int,
) -> Tuple[Dict[str, object], Optional[Dict[str, object]]]:
    latest_copy = dict(latest)
    if not previous_entry:
        return {"latest": latest_copy, "seenAt": seen_at}, None

    previous_latest = dict(previous_entry.get("latest", {}) or {})
    previous_latest_id = latest_id_for_state(previous_latest)
    latest_id = latest_id_for_state(latest_copy)
    if previous_latest_id != latest_id:
        return (
            {"latest": latest_copy, "seenAt": seen_at},
            {"id": item_id, "from": previous_latest, "to": latest_copy},
        )

    return (
        {"latest": merge_latest_metadata(previous_latest, latest_copy), "seenAt": seen_at},
        None,
    )


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


def _check_single_url(
    url: str,
    *,
    adapters: Optional[Sequence[SourceAdapter]],
    http_client: Optional[HttpClient],
) -> SourceResult:
    item_id = None
    try:
        item = normalize_item(url, adapters=adapters)
        item_id = item_id_for_state(item)
        latest = compute_latest(item, adapters=adapters, http_client=http_client)
        return SourceResult(url=url, item_id=item_id, latest=latest)
    except Exception as exc:
        phase = "normalize" if item_id is None else "fetch_latest"
        return SourceResult(
            url=url,
            item_id=item_id,
            error=source_error_record(url, item_id=item_id, phase=phase, exc=exc),
        )


def _collect_source_results(
    urls: Sequence[str],
    *,
    adapters: Optional[Sequence[SourceAdapter]],
    http_client: Optional[HttpClient],
    max_workers: int,
) -> List[SourceResult]:
    if not urls:
        return []
    if len(urls) == 1 or max_workers == 1:
        return [
            _check_single_url(url, adapters=adapters, http_client=http_client)
            for url in urls
        ]

    ordered_results: List[Optional[SourceResult]] = [None] * len(urls)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as executor:
        futures: Dict[Future[SourceResult], int] = {}
        for index, url in enumerate(urls):
            futures[executor.submit(
                _check_single_url,
                url,
                adapters=adapters,
                http_client=http_client,
            )] = index

        for future, index in futures.items():
            ordered_results[index] = future.result()

    return [result for result in ordered_results if result is not None]


def run_check(
    urls_path: str,
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
        with open(urls_path, "r", encoding="utf-8") as f:
            urls = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
    except Exception as exc:
        errors["run"].append(run_error_record("read_urls", exc))
        raise CheckRunError("read_urls", exc, result) from exc

    try:
        state = load_state()
    except Exception as exc:
        errors["run"].append(run_error_record("load_state", exc))
        raise CheckRunError("load_state", exc, result) from exc

    items_state = state.setdefault("items", {})
    now = int(time.time())
    effective_http_client = http_client or RequestsHttpClient(
        timeout=http_config.request_timeout,
        retry_count=http_config.retry_count,
        retry_backoff=http_config.retry_backoff,
        max_requests_per_host=http_config.max_workers_per_host,
    )
    source_results = _collect_source_results(
        urls,
        adapters=adapters,
        http_client=effective_http_client,
        max_workers=http_config.max_workers,
    )

    for source_result in source_results:
        if source_result.error is not None:
            errors["sources"].append(source_result.error)
            continue

        item_id = source_result.item_id or source_result.url
        latest = source_result.latest or {}
        next_entry, update = apply_item_transition(
            item_id,
            items_state.get(item_id),
            latest,
            seen_at=now,
        )
        items_state[item_id] = next_entry
        if update is not None:
            updates.append(update)

    state["lastRunAt"] = now
    try:
        save_state(state)
    except Exception as exc:
        errors["run"].append(run_error_record("save_state", exc))
        raise CheckRunError("save_state", exc, result) from exc

    return result


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: check.py <urls.txt>", file=sys.stderr)
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
