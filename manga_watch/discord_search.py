from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional

from manga_watch.discord_add import WatchlistAddError, format_watchlist_add_error
from manga_watch.source_search import SearchResult, UnsupportedSourceSearchError, search_source
from manga_watch.watchlist import add_watchlist_url

SEARCH_COMMAND = "search"
SEARCH_SELECT_CUSTOM_ID_PREFIX = "search_select"
SEARCH_MISSING_SOURCE_MESSAGE = "検索したい媒体を `source` で指定してください。"
SEARCH_MISSING_QUERY_MESSAGE = "検索したい文字列を `query` で指定してください。"
SEARCH_FAILURE_MESSAGE = "作品検索に失敗しました。サーバーログを確認してください。"
SEARCH_NO_RESULTS_MESSAGE = "検索結果が見つかりませんでした。"


def _coerce_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_visibility(value: object) -> str:
    visibility = str(value or "").strip().lower()
    if visibility == "hidden":
        return "hidden"
    return "visible"


def _format_search_add_response(result: Mapping[str, object]) -> str:
    action = str(result.get("action") or "").strip()
    entry = result.get("entry")
    existing = result.get("existing")
    entry_payload = entry if isinstance(entry, Mapping) else {}
    existing_payload = existing if isinstance(existing, Mapping) else {}

    work_id = str(entry_payload.get("id") or existing_payload.get("id") or "").strip()
    seed_url = str(entry_payload.get("seed_url") or existing_payload.get("seed_url") or "").strip()
    hidden = bool(entry_payload.get("hidden") or existing_payload.get("hidden"))

    lines = []
    if action == "added":
        prefix = "追加しました"
        if hidden:
            prefix += " (非表示)"
        lines.append(f"{prefix}: {work_id}")
    elif action == "duplicate":
        prefix = "既に登録済みです"
        if hidden:
            prefix += " (非表示)"
        lines.append(f"{prefix}: {work_id}")
    else:
        lines.append("作品追加を受け付けました。")
    if seed_url:
        lines.append(f"seed_url: {seed_url}")
    return "\n".join(lines)


@dataclass
class SearchCommandHandler:
    search_source: Callable[..., List[SearchResult]] = search_source
    add_subscription: Callable[..., Mapping[str, object]] = add_watchlist_url

    def start(
        self,
        *,
        source: Optional[str],
        query: Optional[str],
        visibility: Optional[str] = None,
        watchlist_path: Optional[str] = None,
        http_client: object = None,
    ) -> Dict[str, object]:
        del watchlist_path
        normalized_source = _coerce_text(source)
        normalized_query = _coerce_text(query)
        if not normalized_source:
            return {"content": SEARCH_MISSING_SOURCE_MESSAGE}
        if not normalized_query:
            return {"content": SEARCH_MISSING_QUERY_MESSAGE}

        normalized_visibility = _normalize_visibility(visibility)
        try:
            results = self.search_source(
                normalized_source,
                normalized_query,
                http_client=http_client,
                limit=10,
            )
        except UnsupportedSourceSearchError:
            return {"content": f"検索未対応の媒体です: {normalized_source}", "components": []}
        except Exception:
            return {"content": SEARCH_FAILURE_MESSAGE}

        if not results:
            return {"content": SEARCH_NO_RESULTS_MESSAGE, "components": []}

        options = [
            {
                "label": result.title,
                "value": result.seed_url,
                "description": result.subtitle or result.source,
            }
            for result in results[:25]
        ]

        return {
            "content": f"{normalized_source} の検索結果です。1件選んでください。",
            "components": [
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 3,
                            "custom_id": f"{SEARCH_SELECT_CUSTOM_ID_PREFIX}:{normalized_visibility}",
                            "placeholder": "追加する作品を選択",
                            "min_values": 1,
                            "max_values": 1,
                            "options": options,
                        }
                    ],
                }
            ],
        }

    def handle_component(
        self,
        data: Mapping[str, object],
        *,
        watchlist_path: Optional[str] = None,
    ) -> Dict[str, object]:
        custom_id = str(data.get("custom_id") or "").strip()
        if not custom_id.startswith(f"{SEARCH_SELECT_CUSTOM_ID_PREFIX}:"):
            return {"content": "画面の有効期限が切れたため、もう一度 `/search` を実行してください。", "components": []}

        visibility = _normalize_visibility(custom_id.partition(":")[2])
        values = data.get("values") or []
        selected_url = _coerce_text(values[0]) if values else None
        if not selected_url:
            return {"content": "選択された作品URLが見つかりませんでした。", "components": []}

        hidden = visibility == "hidden"
        try:
            result = self.add_subscription(
                selected_url,
                watchlist_path=watchlist_path,
                hidden=hidden,
            )
        except WatchlistAddError as exc:
            return {"content": format_watchlist_add_error(exc), "components": []}
        except Exception:
            return {"content": SEARCH_FAILURE_MESSAGE, "components": []}

        return {"content": _format_search_add_response(result), "components": []}
