from __future__ import annotations

from typing import Dict, Optional

from manga_watch.status import build_status_report
from manga_watch.storage import load_run_summaries, load_state, load_watchlist

from .capabilities import capability_report


def get_watchlist_data(*, watchlist_path: Optional[str] = None, backend: Optional[str] = None) -> Dict[str, object]:
    return load_watchlist(watchlist_path, backend=backend)


def get_state_data(*, state_path: Optional[str] = None, backend: Optional[str] = None) -> Dict[str, object]:
    return load_state(state_path, backend=backend)


def get_health_report(
    *,
    watchlist_path: Optional[str] = None,
    state_path: Optional[str] = None,
    backend: Optional[str] = None,
) -> Dict[str, object]:
    return build_status_report(watchlist_path=watchlist_path, state_path=state_path, backend=backend)


def get_capabilities(*, backend: Optional[str] = None) -> Dict[str, object]:
    return capability_report(backend=backend).to_dict()


def get_run_history(*, limit: int = 20, backend: Optional[str] = None) -> Dict[str, object]:
    capabilities = capability_report(backend=backend)
    if not capabilities.run_history_supported:
        return {
            "supported": False,
            "reason": capabilities.run_history_reason,
            "items": [],
        }
    return {
        "supported": True,
        "reason": None,
        "items": load_run_summaries(limit=limit, backend=backend) or [],
    }


def get_dashboard_snapshot(
    *,
    watchlist_path: Optional[str] = None,
    state_path: Optional[str] = None,
    backend: Optional[str] = None,
) -> Dict[str, object]:
    return {
        "watchlist": get_watchlist_data(watchlist_path=watchlist_path, backend=backend),
        "state": get_state_data(state_path=state_path, backend=backend),
        "health": get_health_report(watchlist_path=watchlist_path, state_path=state_path, backend=backend),
        "capabilities": get_capabilities(backend=backend),
        "run_history": get_run_history(backend=backend),
    }
