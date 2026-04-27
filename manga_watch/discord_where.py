from __future__ import annotations

import base64
import hashlib
import re
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from manga_watch.availability import (
    resolve_episode_availability,
    source_label,
    status_label,
    supported_availability_sources,
)
from manga_watch.source_search import SearchResult, search_source

WHERE_COMMAND = "where"
WHERE_SELECT_CUSTOM_ID_PREFIX = "where_select"
WHERE_MISSING_QUERY_MESSAGE = "探したい作品名を `query` で指定してください。"
WHERE_MISSING_EPISODE_MESSAGE = "探したい話数を `episode` で指定してください。"
WHERE_FAILURE_MESSAGE = "availability 検索に失敗しました。サーバーログを確認してください。"
WHERE_NO_RESULTS_MESSAGE = "availability 候補が見つかりませんでした。"
WHERE_CROSS_SOURCE_MESSAGE = "availability を確認する候補です。1件選んでください。"
DEFAULT_WHERE_SOURCE_LIMIT = 3
MAX_WHERE_CONTEXT_CACHE_SIZE = 256
MAX_COMPONENT_TEXT = 100

_WHERE_CONTEXT_CACHE: "OrderedDict[str, Dict[str, object]]" = OrderedDict()


def _coerce_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _truncate_component_text(text: object, *, max_length: int = MAX_COMPONENT_TEXT) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= max_length:
        return normalized
    if max_length <= 1:
        return "…"
    return normalized[: max_length - 1] + "…"


def _remember_context(context: Dict[str, object]) -> str:
    raw = repr((context.get("query"), context.get("episode"), context.get("results"))).encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    token = base64.urlsafe_b64encode(digest[:9]).decode("ascii").rstrip("=")
    _WHERE_CONTEXT_CACHE[token] = context
    _WHERE_CONTEXT_CACHE.move_to_end(token)
    while len(_WHERE_CONTEXT_CACHE) > MAX_WHERE_CONTEXT_CACHE_SIZE:
        _WHERE_CONTEXT_CACHE.popitem(last=False)
    return token


def _context_for_token(token: object) -> Optional[Dict[str, object]]:
    normalized = _coerce_text(token)
    if not normalized:
        return None
    context = _WHERE_CONTEXT_CACHE.get(normalized)
    if context is not None:
        _WHERE_CONTEXT_CACHE.move_to_end(normalized)
    return context


def _normalized_title(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", normalized)


def _dedupe_results(results: Sequence[SearchResult]) -> List[SearchResult]:
    deduped: List[SearchResult] = []
    seen = set()
    for result in results:
        key = (result.source, result.seed_url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def _select_candidates_for_title(
    results: Sequence[SearchResult],
    *,
    selected: SearchResult,
) -> Dict[str, SearchResult]:
    selected_title = _normalized_title(selected.title)
    candidates: Dict[str, SearchResult] = {}
    for result in results:
        if result.source in candidates:
            continue
        if _normalized_title(result.title) != selected_title:
            continue
        candidates[result.source] = result
    candidates.setdefault(selected.source, selected)
    return candidates


def _episode_display_label(episode: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(episode or "")).strip()
    match = re.search(r"(?:第\s*)?(\d+)\s*話?", normalized)
    if not match:
        return normalized
    return f"第{int(match.group(1))}話"


def _build_where_response(
    *,
    selected: SearchResult,
    results: Sequence[Mapping[str, object]],
    episode: str,
) -> str:
    lines = [f"「{selected.title}」 {_episode_display_label(episode)}", ""]
    for result in results:
        source = str(result.get("source") or "")
        lines.append(f"{source_label(source)}: {status_label(result.get('status'))}")
        url = _coerce_text(result.get("url"))
        if url:
            lines.append(url)
        lines.append("")
    return "\n".join(lines).rstrip()


@dataclass
class WhereCommandHandler:
    search_source: Callable[..., List[SearchResult]] = search_source
    availability_resolver: Callable[..., Mapping[str, object]] = resolve_episode_availability
    availability_sources: Callable[[], Sequence[str]] = supported_availability_sources

    def start(
        self,
        *,
        query: Optional[str],
        episode: Optional[str],
        http_client: object = None,
    ) -> Dict[str, object]:
        normalized_query = _coerce_text(query)
        normalized_episode = _coerce_text(episode)
        if not normalized_query:
            return {"content": WHERE_MISSING_QUERY_MESSAGE, "components": []}
        if not normalized_episode:
            return {"content": WHERE_MISSING_EPISODE_MESSAGE, "components": []}

        results: List[SearchResult] = []
        had_failure = False
        for source_name in self.availability_sources():
            try:
                results.extend(
                    self.search_source(
                        source_name,
                        normalized_query,
                        http_client=http_client,
                        limit=DEFAULT_WHERE_SOURCE_LIMIT,
                    )
                )
            except Exception:
                had_failure = True

        deduped_results = _dedupe_results(results)
        if not deduped_results:
            if had_failure:
                return {"content": WHERE_FAILURE_MESSAGE, "components": []}
            return {"content": WHERE_NO_RESULTS_MESSAGE, "components": []}

        context_token = _remember_context(
            {
                "query": normalized_query,
                "episode": normalized_episode,
                "results": deduped_results,
            }
        )
        return {
            "content": WHERE_CROSS_SOURCE_MESSAGE,
            "components": [
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 3,
                            "custom_id": f"{WHERE_SELECT_CUSTOM_ID_PREFIX}:{context_token}",
                            "placeholder": "availability を確認する作品を選択",
                            "min_values": 1,
                            "max_values": 1,
                            "options": [
                                {
                                    "label": _truncate_component_text(result.title, max_length=MAX_COMPONENT_TEXT),
                                    "value": str(index),
                                    "description": _truncate_component_text(result.source, max_length=MAX_COMPONENT_TEXT),
                                }
                                for index, result in enumerate(deduped_results[:25])
                            ],
                        }
                    ],
                }
            ],
        }

    def handle_component(
        self,
        data: Mapping[str, object],
        *,
        http_client: object = None,
    ) -> Dict[str, object]:
        custom_id = str(data.get("custom_id") or "").strip()
        if not custom_id.startswith(f"{WHERE_SELECT_CUSTOM_ID_PREFIX}:"):
            return {"content": "画面の有効期限が切れたため、もう一度 `/where` を実行してください。", "components": []}

        context = _context_for_token(custom_id.partition(":")[2])
        if context is None:
            return {"content": "画面の有効期限が切れたため、もう一度 `/where` を実行してください。", "components": []}

        values = data.get("values") or []
        try:
            selected_index = int(values[0])
        except (IndexError, TypeError, ValueError):
            return {"content": "選択された候補が見つかりませんでした。", "components": []}

        results = context.get("results")
        if not isinstance(results, list) or selected_index < 0 or selected_index >= len(results):
            return {"content": "選択された候補が見つかりませんでした。", "components": []}
        selected = results[selected_index]
        if not isinstance(selected, SearchResult):
            return {"content": "選択された候補が見つかりませんでした。", "components": []}

        episode = str(context.get("episode") or "")
        candidate_by_source = _select_candidates_for_title(results, selected=selected)
        availability_results: List[Mapping[str, object]] = []
        for source_name in self.availability_sources():
            candidate = candidate_by_source.get(source_name)
            if candidate is None:
                availability_results.append({"source": source_name, "status": "not_found", "url": None})
                continue
            try:
                availability_results.append(
                    self.availability_resolver(
                        candidate.source,
                        candidate.seed_url,
                        episode,
                        http_client=http_client,
                    )
                )
            except Exception:
                availability_results.append({"source": source_name, "status": "needs_check", "url": candidate.seed_url})

        return {
            "content": _build_where_response(
                selected=selected,
                results=availability_results,
                episode=episode,
            ),
            "components": [],
        }


def is_where_component(custom_id: object) -> bool:
    return str(custom_id or "").strip().startswith(f"{WHERE_SELECT_CUSTOM_ID_PREFIX}:")
