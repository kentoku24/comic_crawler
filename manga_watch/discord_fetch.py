from __future__ import annotations

from typing import Dict, Optional

from manga_watch.runner import RunCoordinator, start_fetch_run

FETCH_COMMAND = "fetch"


def handle_fetch_trigger(
    message_content: object,
    *,
    coordinator: RunCoordinator,
) -> Optional[Dict[str, object]]:
    normalized = str(message_content or "").strip()
    if normalized != FETCH_COMMAND:
        return None
    return start_fetch_run(coordinator)
