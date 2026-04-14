from __future__ import annotations

import base64
import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from manga_watch.discord_add import WatchlistAddError, format_watchlist_add_error
from manga_watch.source_search import (
    SearchResult,
    UnsupportedSourceSearchError,
    search_source,
    supported_search_sources,
)
from manga_watch.watchlist import add_watchlist_url

SEARCH_COMMAND = "search"
SEARCH_SELECT_CUSTOM_ID_PREFIX = "search_select"
SEARCH_MISSING_SOURCE_MESSAGE = "検索したい媒体を `source` で指定してください。"
SEARCH_MISSING_QUERY_MESSAGE = "検索したい文字列を `query` で指定してください。"
SEARCH_FAILURE_MESSAGE = "作品検索に失敗しました。サーバーログを確認してください。"
SEARCH_NO_RESULTS_MESSAGE = "検索結果が見つかりませんでした。"
SEARCH_CROSS_SOURCE_MESSAGE = "横断検索結果です。1件選んでください。"
MAX_COMPONENT_TEXT = 100
MAX_COMPONENT_VALUE = 100
MAX_SELECT_URL_CACHE_SIZE = 256
MAX_SELECT_OPTIONS = 25
DEFAULT_CROSS_SOURCE_LIMIT = 3
SELECT_URL_TOKEN_PREFIX = "u:"

_SEARCH_SELECT_URL_CACHE: "OrderedDict[str, str]" = OrderedDict()


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


def _truncate_component_text(text: object, *, max_length: int = MAX_COMPONENT_TEXT) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= max_length:
        return normalized
    if max_length <= 1:
        return "…"
    return normalized[: max_length - 1] + "…"


def _remember_search_result_url(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).digest()
    token = SELECT_URL_TOKEN_PREFIX + base64.urlsafe_b64encode(digest[:9]).decode("ascii").rstrip("=")
    _SEARCH_SELECT_URL_CACHE[token] = url
    _SEARCH_SELECT_URL_CACHE.move_to_end(token)
    while len(_SEARCH_SELECT_URL_CACHE) > MAX_SELECT_URL_CACHE_SIZE:
        _SEARCH_SELECT_URL_CACHE.popitem(last=False)
    return token


def _select_option_value(url: object) -> str:
    normalized = _coerce_text(url) or ""
    if len(normalized) <= MAX_COMPONENT_VALUE:
        return normalized
    return _remember_search_result_url(normalized)


def _resolve_select_option_value(value: object) -> Optional[str]:
    normalized = _coerce_text(value)
    if not normalized:
        return None
    cached = _SEARCH_SELECT_URL_CACHE.get(normalized)
    if cached is not None:
        _SEARCH_SELECT_URL_CACHE.move_to_end(normalized)
        return cached
    if normalized.startswith(SELECT_URL_TOKEN_PREFIX):
        return None
    return normalized


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


def _dedupe_bucket_results(results: Sequence[SearchResult], *, default_source: str) -> List[SearchResult]:
    unique_results: List[SearchResult] = []
    seen_keys = set()
    for result in results:
        source_name = _coerce_text(result.source) or default_source
        seed_url = _coerce_text(result.seed_url)
        title = _coerce_text(result.title)
        if not seed_url or not title:
            continue
        dedupe_key = (source_name, seed_url)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        unique_results.append(
            SearchResult(
                source=source_name,
                title=title,
                seed_url=seed_url,
                subtitle=_coerce_text(result.subtitle),
            )
        )
    return unique_results


def _interleave_result_buckets(
    result_buckets: Sequence[Sequence[SearchResult]],
    *,
    max_results: int,
) -> List[SearchResult]:
    interleaved: List[SearchResult] = []
    max_bucket_size = max((len(bucket) for bucket in result_buckets), default=0)
    for index in range(max_bucket_size):
        for bucket in result_buckets:
            if index >= len(bucket):
                continue
            interleaved.append(bucket[index])
            if len(interleaved) >= max_results:
                return interleaved
    return interleaved


def _build_select_options(
    results: Sequence[SearchResult],
    *,
    cross_source: bool,
) -> List[Dict[str, str]]:
    return [
        {
            "label": _truncate_component_text(result.title),
            "value": _select_option_value(result.seed_url),
            "description": _truncate_component_text(
                result.source if cross_source else (result.subtitle or result.source)
            ),
        }
        for result in results[:MAX_SELECT_OPTIONS]
    ]


def _build_search_response(
    *,
    content: str,
    results: Sequence[SearchResult],
    visibility: str,
    cross_source: bool,
) -> Dict[str, object]:
    return {
        "content": content,
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 3,
                        "custom_id": f"{SEARCH_SELECT_CUSTOM_ID_PREFIX}:{visibility}",
                        "placeholder": "追加する作品を選択",
                        "min_values": 1,
                        "max_values": 1,
                        "options": _build_select_options(results, cross_source=cross_source),
                    }
                ],
            }
        ],
    }


@dataclass
class SearchCommandHandler:
    search_source: Callable[..., List[SearchResult]] = search_source
    add_subscription: Callable[..., Mapping[str, object]] = add_watchlist_url
    supported_sources: Callable[[], Sequence[str]] = supported_search_sources

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
        if not normalized_query:
            return {"content": SEARCH_MISSING_QUERY_MESSAGE}

        normalized_visibility = _normalize_visibility(visibility)
        if not normalized_source:
            return self._start_cross_source(
                query=normalized_query,
                visibility=normalized_visibility,
                http_client=http_client,
            )

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

        return _build_search_response(
            content=f"{normalized_source} の検索結果です。1件選んでください。",
            results=results,
            visibility=normalized_visibility,
            cross_source=False,
        )

    def _start_cross_source(
        self,
        *,
        query: str,
        visibility: str,
        http_client: object = None,
    ) -> Dict[str, object]:
        buckets: List[List[SearchResult]] = []
        had_failure = False
        had_completed_lookup = False
        for source_name in self.supported_sources():
            try:
                results = self.search_source(
                    source_name,
                    query,
                    http_client=http_client,
                    limit=DEFAULT_CROSS_SOURCE_LIMIT,
                )
            except Exception:
                had_failure = True
                continue
            had_completed_lookup = True
            deduped_results = _dedupe_bucket_results(results, default_source=source_name)
            if deduped_results:
                buckets.append(deduped_results[:DEFAULT_CROSS_SOURCE_LIMIT])

        if not buckets:
            if had_failure and not had_completed_lookup:
                return {"content": SEARCH_FAILURE_MESSAGE, "components": []}
            return {"content": SEARCH_NO_RESULTS_MESSAGE, "components": []}

        interleaved_results = _interleave_result_buckets(
            buckets,
            max_results=MAX_SELECT_OPTIONS,
        )
        if not interleaved_results:
            return {"content": SEARCH_NO_RESULTS_MESSAGE, "components": []}

        return _build_search_response(
            content=SEARCH_CROSS_SOURCE_MESSAGE,
            results=interleaved_results,
            visibility=visibility,
            cross_source=True,
        )

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
        selected_url = _resolve_select_option_value(values[0]) if values else None
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
