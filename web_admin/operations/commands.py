from __future__ import annotations

from typing import Dict, Optional, Sequence

from manga_watch.runner import RunCoordinator, RunnerConfig
from manga_watch.storage import get_watchlist_path, load_watchlist, save_watchlist
from manga_watch.watchlist import (
    HttpClient,
    SourceAdapter,
    WatchlistAddError,
    build_watchlist_preview,
    find_duplicate_entry,
    normalize_input_url,
)

WEB_ADMIN_TRIGGER_SOURCE = "web_admin"


def add_watchlist_url_command(
    url: str,
    *,
    watchlist_path: Optional[str] = None,
    backend: Optional[str] = None,
    adapters: Optional[Sequence[SourceAdapter]] = None,
    http_client: Optional[HttpClient] = None,
) -> Dict[str, object]:
    target_path = watchlist_path or get_watchlist_path()
    normalized_input = normalize_input_url(url)
    entry = build_watchlist_preview(
        normalized_input,
        adapters=adapters,
        http_client=http_client,
    )
    watchlist = load_watchlist(target_path, backend=backend)
    existing = find_duplicate_entry(watchlist["works"], str(entry["id"]))
    if existing is not None:
        return {
            "action": "duplicate",
            "input_url": normalized_input,
            "watchlist_path": target_path,
            "entry": entry,
            "existing": existing,
            "work_count": len(watchlist["works"]),
        }

    works = list(watchlist["works"])
    works.append(entry)
    save_watchlist(
        {
            "version": watchlist["version"],
            "works": works,
        },
        path=target_path,
        backend=backend,
    )
    return {
        "action": "added",
        "input_url": normalized_input,
        "watchlist_path": target_path,
        "entry": entry,
        "work_count": len(works),
    }


def update_watchlist_work_command(
    work_id: str,
    *,
    enabled: Optional[bool] = None,
    watchlist_path: Optional[str] = None,
    backend: Optional[str] = None,
) -> Dict[str, object]:
    if enabled is None:
        raise ValueError("At least one field must be updated")

    target_path = watchlist_path or get_watchlist_path()
    watchlist = load_watchlist(target_path, backend=backend)
    works = []
    updated_entry = None
    for entry in watchlist["works"]:
        candidate = dict(entry)
        if str(candidate.get("id")) == work_id:
            candidate["enabled"] = bool(enabled)
            updated_entry = candidate
        works.append(candidate)

    if updated_entry is None:
        raise WatchlistAddError(
            "missing_work",
            f"Unknown watchlist work id: {work_id}",
            "Refresh the watchlist and retry the operation with an existing work id.",
        )

    save_watchlist(
        {
            "version": watchlist["version"],
            "works": works,
        },
        path=target_path,
        backend=backend,
    )
    return {
        "action": "updated",
        "entry": updated_entry,
        "work_id": work_id,
    }


def build_run_coordinator(*, require_discord: bool = False) -> RunCoordinator:
    return RunCoordinator(RunnerConfig.from_env(require_discord=require_discord))


def trigger_manual_run_command(
    *,
    coordinator: Optional[RunCoordinator] = None,
    trigger_source: str = WEB_ADMIN_TRIGGER_SOURCE,
) -> Dict[str, object]:
    resolved = coordinator or build_run_coordinator(require_discord=False)
    return resolved.start_background(trigger_source)
