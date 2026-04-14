from __future__ import annotations

from typing import Callable, Optional

from manga_watch.source_search import search_source, supported_search_sources

TITLE_COMMAND = "title"
TITLE_USAGE_MESSAGE = "使い方: `title <作品名>`"


def _parse_query(message_content: object) -> Optional[str]:
    normalized = str(message_content or "").strip()
    if normalized == TITLE_COMMAND:
        return ""

    prefix = f"{TITLE_COMMAND} "
    if not normalized.startswith(prefix):
        return None

    return normalized[len(prefix) :].strip()


def handle_title_query(
    message_content: object,
    *,
    search_source_fn: Callable[..., object] = search_source,
    supported_sources_fn: Callable[[], tuple[str, ...]] = supported_search_sources,
) -> Optional[str]:
    query = _parse_query(message_content)
    if query is None:
        return None
    if not query:
        return TITLE_USAGE_MESSAGE

    sources = tuple(supported_sources_fn())
    for source in sources:
        try:
            search_source_fn(source, query, limit=1)
        except Exception:
            continue

    return f"`{query}` の title 検索を開始しました。対象媒体数: {len(sources)}"
