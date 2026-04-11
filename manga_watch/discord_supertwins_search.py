from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional

from manga_watch.discord_text import series_label_for_snapshot
from manga_watch.source_search import SearchResult, search_source, supported_search_sources
from manga_watch.storage import load_state, load_watchlist, save_state, save_watchlist
from manga_watch.supertwins import (
    clear_pending_search,
    ensure_supertwins_state,
    get_pending_search,
    link_group_members,
    set_pending_search,
    upsert_watchlist_entry,
)
from manga_watch.watchlist import build_watchlist_preview

SUPERTWINS_SEARCH_COMMAND = "supertwins-search"
SUPERTWINS_SEARCH_COMPONENT_PREFIX = "supertwins_search:"
SUPERTWINS_SEARCH_WORK_SELECT = "supertwins_search_work_select"
SUPERTWINS_SEARCH_PAGE_PREFIX = f"{SUPERTWINS_SEARCH_COMPONENT_PREFIX}page:"
SUPERTWINS_SEARCH_RESULT_SELECT_PREFIX = f"{SUPERTWINS_SEARCH_COMPONENT_PREFIX}results:"
SUPERTWINS_SEARCH_EMPTY_MESSAGE = "まだ watchlist に登録された作品がありません。"
SUPERTWINS_SEARCH_WORK_PROMPT = "他媒体候補を探したい作品を選んでください。"
SUPERTWINS_SEARCH_RESULTS_PROMPT = "他媒体候補を選んでください。選択した作品は hidden で追加し、supertwins に登録します。"
SUPERTWINS_SEARCH_RESULTS_EMPTY_MESSAGE = "他媒体候補が見つかりませんでした。"
SUPERTWINS_SEARCH_STALE_MESSAGE = (
    "画面の有効期限が切れたため、もう一度 `/supertwins-search` を実行してください。"
)

ACTION_ROW = 1
BUTTON_COMPONENT = 2
BUTTON_STYLE_PRIMARY = 1
BUTTON_STYLE_SECONDARY = 2
STRING_SELECT_COMPONENT = 3
MAX_OPTIONS_PER_PAGE = 25
MAX_COMPONENT_TEXT = 100
MAX_COMPONENT_VALUE = 100
DEFAULT_SEARCH_LIMIT = 10
SELECT_URL_TOKEN_PREFIX = "u:"


def is_supertwins_search_component(custom_id: object) -> bool:
    normalized = str(custom_id or "").strip()
    return normalized.startswith(SUPERTWINS_SEARCH_COMPONENT_PREFIX) or normalized == SUPERTWINS_SEARCH_WORK_SELECT


def _coerce_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _truncate_component_text(text: object, *, max_length: int = MAX_COMPONENT_TEXT) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 1] + "…"


def _tokenize_select_option_value(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).digest()
    return SELECT_URL_TOKEN_PREFIX + base64.urlsafe_b64encode(digest[:9]).decode("ascii").rstrip("=")


def _select_option_value(url: object) -> str:
    normalized = _coerce_text(url) or ""
    if len(normalized) <= MAX_COMPONENT_VALUE:
        return normalized
    return _tokenize_select_option_value(normalized)


def _search_session_token(root_work_id: str, selected_urls_by_value: Mapping[str, str]) -> str:
    material = "\n".join(
        [
            root_work_id,
            *[
                f"{value}={selected_urls_by_value[value]}"
                for value in sorted(selected_urls_by_value)
            ],
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _state_works(state: Mapping[str, object]) -> Mapping[str, object]:
    works = state.get("works", {})
    return works if isinstance(works, Mapping) else {}


def _watchlist_works(watchlist: Mapping[str, object]) -> List[Mapping[str, object]]:
    works = watchlist.get("works", [])
    return works if isinstance(works, list) else []


def _watchlist_entry_by_id(watchlist: Mapping[str, object], work_id: str) -> Optional[Mapping[str, object]]:
    for entry in _watchlist_works(watchlist):
        if str(entry.get("id")) == work_id:
            return entry
    return None


def _work_options(watchlist: Mapping[str, object], state: Mapping[str, object]) -> List[Dict[str, str]]:
    options: List[Dict[str, str]] = []
    works = _watchlist_works(watchlist)
    runtime_works = _state_works(state)
    for entry in works:
        work_id = str(entry.get("id") or "").strip()
        if not work_id:
            continue
        if entry.get("enabled") is False:
            continue
        latest = runtime_works.get(work_id, {}) if isinstance(runtime_works, Mapping) else {}
        if not isinstance(latest, Mapping):
            latest = {}
        title = series_label_for_snapshot(work_id, latest.get("latest", latest))
        source = str(entry.get("source") or "").strip() or "unknown"
        hidden = "非表示" if bool(entry.get("hidden")) else "表示"
        options.append(
            {
                "label": _truncate_component_text(f"{title}"),
                "value": work_id,
                "description": _truncate_component_text(f"{source} / {hidden}"),
            }
        )
    return sorted(options, key=lambda option: option["label"])


def _page_options(
    options: List[Dict[str, str]],
    *,
    page: int,
) -> tuple[List[Dict[str, str]], int, int]:
    page_count = max((len(options) + MAX_OPTIONS_PER_PAGE - 1) // MAX_OPTIONS_PER_PAGE, 1)
    page_index = min(max(int(page), 0), page_count - 1)
    start = page_index * MAX_OPTIONS_PER_PAGE
    return options[start : start + MAX_OPTIONS_PER_PAGE], page_index, page_count


def _work_components(
    options: List[Dict[str, str]],
    *,
    page: int = 0,
) -> List[Dict[str, object]]:
    page_options, page_index, page_count = _page_options(options, page=page)
    components: List[Dict[str, object]] = [
        {
            "type": ACTION_ROW,
            "components": [
                {
                    "type": STRING_SELECT_COMPONENT,
                    "custom_id": SUPERTWINS_SEARCH_WORK_SELECT,
                    "placeholder": "起点の作品を選択",
                    "min_values": 1,
                    "max_values": 1,
                    "options": page_options,
                }
            ],
        }
    ]
    if page_count > 1:
        components.append(
            {
                "type": ACTION_ROW,
                "components": [
                    {
                        "type": BUTTON_COMPONENT,
                        "style": BUTTON_STYLE_SECONDARY,
                        "custom_id": f"{SUPERTWINS_SEARCH_PAGE_PREFIX}{max(page_index - 1, 0)}",
                        "label": "Prev",
                        "disabled": page_index == 0,
                    },
                    {
                        "type": BUTTON_COMPONENT,
                        "style": BUTTON_STYLE_PRIMARY,
                        "custom_id": f"{SUPERTWINS_SEARCH_PAGE_PREFIX}{min(page_index + 1, page_count - 1)}",
                        "label": "Next",
                        "disabled": page_index >= page_count - 1,
                    },
                ],
            }
        )
    return components


def _search_results(
    root_source: str,
    query: str,
    *,
    search_source_fn: Callable[..., List[SearchResult]],
    search_limit: int = DEFAULT_SEARCH_LIMIT,
) -> List[SearchResult]:
    supported_sources = supported_search_sources()
    results: List[SearchResult] = []
    seen_urls = set()
    for source in supported_sources:
        if root_source and source == root_source:
            continue
        try:
            source_results = search_source_fn(source, query, limit=search_limit)
        except Exception:
            continue
        for result in source_results:
            seed_url = str(result.seed_url).strip()
            if not seed_url or seed_url in seen_urls:
                continue
            seen_urls.add(seed_url)
            results.append(result)
            if len(results) >= MAX_OPTIONS_PER_PAGE:
                return results
    return results


def _search_result_options(results: List[SearchResult]) -> tuple[List[Dict[str, str]], Dict[str, str]]:
    options: List[Dict[str, str]] = []
    selected_urls_by_value: Dict[str, str] = {}
    for result in results[:MAX_OPTIONS_PER_PAGE]:
        value = _select_option_value(result.seed_url)
        options.append(
            {
                "label": _truncate_component_text(result.title),
                "value": value,
                "description": _truncate_component_text(result.source),
            }
        )
        if value != str(result.seed_url):
            selected_urls_by_value[value] = str(result.seed_url)
    return options, selected_urls_by_value


def _get_root_work(
    watchlist: Mapping[str, object],
    state: Mapping[str, object],
    work_id: str,
) -> tuple[Optional[Mapping[str, object]], Mapping[str, object]]:
    entry = _watchlist_entry_by_id(watchlist, work_id)
    if entry is None:
        return None, {}
    runtime_works = _state_works(state)
    latest = runtime_works.get(work_id, {}) if isinstance(runtime_works, Mapping) else {}
    if not isinstance(latest, Mapping):
        latest = {}
    return entry, latest


def _ensure_group_members(
    state: Mapping[str, object],
    member_work_ids: List[str],
) -> Dict[str, object]:
    updated_state = ensure_supertwins_state(state)
    linked_state, _group_id = link_group_members(updated_state, member_work_ids)
    return linked_state


def _build_hidden_upsert_result(
    watchlist: Mapping[str, object],
    selected_url: str,
) -> Dict[str, object]:
    preview = build_watchlist_preview(selected_url)
    return upsert_watchlist_entry(watchlist, preview, hidden=True)


@dataclass
class SearchSupertwinsCommandHandler:
    search_source: Callable[..., List[SearchResult]] = search_source
    watchlist_loader: Callable[..., Dict[str, object]] = load_watchlist
    state_loader: Callable[..., Dict[str, object]] = load_state
    watchlist_saver: Callable[..., None] = save_watchlist
    state_saver: Callable[..., None] = save_state
    backend: Optional[str] = None

    def start(
        self,
        *,
        watchlist_path: Optional[str] = None,
        state_path: Optional[str] = None,
    ) -> Dict[str, object]:
        watchlist = self.watchlist_loader(watchlist_path, backend=self.backend)
        state = self.state_loader(state_path, backend=self.backend)
        options = _work_options(watchlist, state)
        if not options:
            return {"content": SUPERTWINS_SEARCH_EMPTY_MESSAGE, "components": []}

        return {
            "content": SUPERTWINS_SEARCH_WORK_PROMPT,
            "components": _work_components(options, page=0),
        }

    def handle_component(
        self,
        data: Mapping[str, object],
        *,
        watchlist_path: Optional[str] = None,
        state_path: Optional[str] = None,
    ) -> Dict[str, object]:
        custom_id = str(data.get("custom_id") or "").strip()
        if custom_id == SUPERTWINS_SEARCH_WORK_SELECT:
            return self._handle_work_selection(
                data,
                watchlist_path=watchlist_path,
                state_path=state_path,
            )
        if custom_id.startswith(SUPERTWINS_SEARCH_PAGE_PREFIX):
            return self._handle_page_selection(
                data,
                watchlist_path=watchlist_path,
                state_path=state_path,
            )
        if custom_id.startswith(SUPERTWINS_SEARCH_RESULT_SELECT_PREFIX):
            return self._handle_result_selection(
                data,
                watchlist_path=watchlist_path,
                state_path=state_path,
            )
        return {"content": SUPERTWINS_SEARCH_STALE_MESSAGE, "components": []}

    def _handle_page_selection(
        self,
        data: Mapping[str, object],
        *,
        watchlist_path: Optional[str],
        state_path: Optional[str],
    ) -> Dict[str, object]:
        custom_id = str(data.get("custom_id") or "").strip()
        raw_page = custom_id[len(SUPERTWINS_SEARCH_PAGE_PREFIX) :]
        try:
            page = int(raw_page)
        except ValueError:
            return {"content": SUPERTWINS_SEARCH_STALE_MESSAGE, "components": []}

        watchlist = self.watchlist_loader(watchlist_path, backend=self.backend)
        state = self.state_loader(state_path, backend=self.backend)
        options = _work_options(watchlist, state)
        if not options:
            return {"content": SUPERTWINS_SEARCH_EMPTY_MESSAGE, "components": []}
        return {
            "content": SUPERTWINS_SEARCH_WORK_PROMPT,
            "components": _work_components(options, page=page),
        }

    def _handle_work_selection(
        self,
        data: Mapping[str, object],
        *,
        watchlist_path: Optional[str],
        state_path: Optional[str],
    ) -> Dict[str, object]:
        selected_values = [str(value).strip() for value in data.get("values") or [] if str(value).strip()]
        root_work_id = selected_values[0] if selected_values else ""
        if not root_work_id:
            return {"content": SUPERTWINS_SEARCH_STALE_MESSAGE, "components": []}

        watchlist = self.watchlist_loader(watchlist_path, backend=self.backend)
        state = self.state_loader(state_path, backend=self.backend)
        root_entry, latest = _get_root_work(watchlist, state, root_work_id)
        if root_entry is None:
            return {"content": SUPERTWINS_SEARCH_STALE_MESSAGE, "components": []}

        root_title = series_label_for_snapshot(root_work_id, latest.get("latest", latest))
        root_source = str(root_entry.get("source") or "").strip()
        results = _search_results(
            root_source,
            root_title,
            search_source_fn=self.search_source,
        )
        if not results:
            return {
                "content": f"{root_title} の他媒体候補が見つかりませんでした。",
                "components": [],
            }

        result_options, selected_urls_by_value = _search_result_options(results)
        session_token = _search_session_token(root_work_id, selected_urls_by_value)
        updated_state = set_pending_search(
            state,
            session_token,
            {
                "root_work_id": root_work_id,
                "selected_urls_by_value": selected_urls_by_value,
            },
        )
        try:
            self.state_saver(updated_state, state_path, backend=self.backend)
        except Exception:
            return {"content": SUPERTWINS_SEARCH_STALE_MESSAGE, "components": []}

        return {
            "content": SUPERTWINS_SEARCH_RESULTS_PROMPT,
            "components": [
                {
                    "type": ACTION_ROW,
                    "components": [
                        {
                            "type": STRING_SELECT_COMPONENT,
                            "custom_id": f"{SUPERTWINS_SEARCH_RESULT_SELECT_PREFIX}{session_token}",
                            "placeholder": "追加する候補を選択",
                            "min_values": 1,
                            "max_values": min(len(results), MAX_OPTIONS_PER_PAGE),
                            "options": result_options,
                        }
                    ],
                }
            ],
        }

    def _handle_result_selection(
        self,
        data: Mapping[str, object],
        *,
        watchlist_path: Optional[str],
        state_path: Optional[str],
    ) -> Dict[str, object]:
        session_token = str(data.get("custom_id") or "").strip()[len(SUPERTWINS_SEARCH_RESULT_SELECT_PREFIX) :]
        if not session_token:
            return {"content": SUPERTWINS_SEARCH_STALE_MESSAGE, "components": []}

        watchlist = self.watchlist_loader(watchlist_path, backend=self.backend)
        state = self.state_loader(state_path, backend=self.backend)
        try:
            pending_search = get_pending_search(state, session_token)
        except ValueError:
            return {"content": SUPERTWINS_SEARCH_STALE_MESSAGE, "components": []}

        root_work_id = _coerce_text(pending_search.get("root_work_id")) or ""
        selected_urls_by_value = pending_search.get("selected_urls_by_value", {})
        if not isinstance(selected_urls_by_value, Mapping):
            return {"content": SUPERTWINS_SEARCH_STALE_MESSAGE, "components": []}
        resolved_urls: List[str] = []
        for value in data.get("values") or []:
            normalized = _coerce_text(value)
            if not normalized:
                return {"content": SUPERTWINS_SEARCH_STALE_MESSAGE, "components": []}
            resolved = selected_urls_by_value.get(normalized)
            if resolved is None:
                if normalized.startswith(SELECT_URL_TOKEN_PREFIX):
                    return {"content": SUPERTWINS_SEARCH_STALE_MESSAGE, "components": []}
                resolved = normalized
            resolved_urls.append(str(resolved))
        selected_urls = [value for value in resolved_urls if value]
        if not root_work_id or not selected_urls:
            return {"content": SUPERTWINS_SEARCH_STALE_MESSAGE, "components": []}

        root_entry, latest = _get_root_work(watchlist, state, root_work_id)
        if root_entry is None:
            return {"content": SUPERTWINS_SEARCH_STALE_MESSAGE, "components": []}

        original_watchlist = watchlist
        original_state = state
        updated_watchlist = dict(watchlist)
        updated_state = clear_pending_search(state, session_token)
        selected_work_ids: List[str] = []
        duplicate_count = 0
        for selected_url in selected_urls:
            try:
                upsert_result = _build_hidden_upsert_result(updated_watchlist, selected_url)
            except Exception:
                return {"content": SUPERTWINS_SEARCH_STALE_MESSAGE, "components": []}
            updated_watchlist = upsert_result["watchlist"]
            selected_entry = upsert_result["entry"]
            selected_work_id = str(selected_entry.get("id") or "").strip()
            if not selected_work_id or selected_work_id == root_work_id:
                continue
            if upsert_result["action"] == "duplicate":
                duplicate_count += 1
            selected_work_ids.append(selected_work_id)

        if not selected_work_ids:
            return {"content": SUPERTWINS_SEARCH_STALE_MESSAGE, "components": []}

        group_member_ids = [root_work_id, *selected_work_ids]
        updated_state = _ensure_group_members(updated_state, group_member_ids)

        try:
            self.watchlist_saver(updated_watchlist, watchlist_path, backend=self.backend)
            self.state_saver(updated_state, state_path, backend=self.backend)
        except Exception as exc:
            try:
                self.watchlist_saver(original_watchlist, watchlist_path, backend=self.backend)
            except Exception:
                pass
            try:
                self.state_saver(original_state, state_path, backend=self.backend)
            except Exception:
                pass
            raise RuntimeError(f"supertwins-search save failed: {exc}") from exc

        root_title = series_label_for_snapshot(root_work_id, latest.get("latest", latest))
        message = f"{root_title} に {len(selected_work_ids)} 件の他媒体候補を hidden で追加し、supertwins に登録しました。"
        if duplicate_count:
            message += f"\n{duplicate_count} 件は既存登録を hidden 化して group に追加しました。"
        return {"content": message, "components": []}
