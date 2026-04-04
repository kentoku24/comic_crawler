from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional

from manga_watch.discord_text import series_label_for_snapshot
from manga_watch.storage import load_state, load_watchlist, save_state, save_watchlist

REMOVE_COMMAND = "remove"
ACTION_ROW = 1
BUTTON_COMPONENT = 2
STRING_SELECT_COMPONENT = 3
BUTTON_STYLE_PRIMARY = 1
BUTTON_STYLE_SECONDARY = 2
BUTTON_STYLE_DANGER = 4
MAX_OPTIONS_PER_PAGE = 25
MAX_COMPONENT_TEXT = 100


def _clone_payload(payload: Mapping[str, object]) -> Dict[str, object]:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def build_remove_token(work_id: str) -> str:
    return hashlib.sha256(work_id.encode("utf-8")).hexdigest()[:24]


def _truncate_component_text(text: object, *, max_length: int = MAX_COMPONENT_TEXT) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 1] + "…"


def _series_label(work_id: str, latest: Mapping[str, object]) -> str:
    return _truncate_component_text(series_label_for_snapshot(work_id, latest))


def _option_description(entry: Mapping[str, object]) -> str:
    source = str(entry.get("source") or "").strip()
    seed_url = str(entry.get("seed_url") or "").strip()
    if source:
        return _truncate_component_text(source)
    if len(seed_url) <= MAX_COMPONENT_TEXT:
        return seed_url
    return _truncate_component_text(seed_url[-MAX_COMPONENT_TEXT:])


def _call_loader(
    loader: Callable[..., Dict[str, object]],
    path: Optional[str],
    *,
    backend: Optional[str],
) -> Dict[str, object]:
    return loader(path, backend=backend)


def _call_saver(
    saver: Callable[..., None],
    payload: Mapping[str, object],
    path: Optional[str],
    *,
    backend: Optional[str],
) -> None:
    saver(payload, path=path, backend=backend)


def remove_watch_subscription(
    work_id: str,
    *,
    watchlist_path: Optional[str] = None,
    state_path: Optional[str] = None,
    backend: Optional[str] = None,
    watchlist_loader: Callable[..., Dict[str, object]] = load_watchlist,
    state_loader: Callable[..., Dict[str, object]] = load_state,
    watchlist_saver: Callable[..., None] = save_watchlist,
    state_saver: Callable[..., None] = save_state,
) -> Dict[str, object]:
    watchlist = _call_loader(watchlist_loader, watchlist_path, backend=backend)
    state = _call_loader(state_loader, state_path, backend=backend)
    original_watchlist = _clone_payload(watchlist)
    original_state = _clone_payload(state)

    works = watchlist.get("works", [])
    if not isinstance(works, list):
        raise ValueError("watchlist.works must be a list")

    matched_entry = None
    kept_works: List[Dict[str, object]] = []
    for entry in works:
        entry_dict = dict(entry)
        if str(entry_dict.get("id") or "").strip() == work_id:
            matched_entry = entry_dict
            continue
        kept_works.append(entry_dict)

    if matched_entry is None:
        return {"action": "not_found", "work_id": work_id}

    latest = state.get("works", {}).get(work_id, {}) if isinstance(state.get("works"), Mapping) else {}
    if not isinstance(latest, Mapping):
        latest = {}
    series_title = series_label_for_snapshot(work_id, latest.get("latest", latest))

    updated_watchlist = {"version": watchlist.get("version"), "works": kept_works}
    updated_state = _clone_payload(state)
    updated_state.setdefault("works", {})
    if isinstance(updated_state["works"], dict):
        updated_state["works"].pop(work_id, None)

    try:
        _call_saver(watchlist_saver, updated_watchlist, watchlist_path, backend=backend)
        _call_saver(state_saver, updated_state, state_path, backend=backend)
    except Exception as exc:
        try:
            _call_saver(watchlist_saver, original_watchlist, watchlist_path, backend=backend)
        except Exception:
            return {
                "action": "failed",
                "work_id": work_id,
                "series_title": series_title,
                "error": str(exc),
                "rollback_failed": True,
            }
        try:
            _call_saver(state_saver, original_state, state_path, backend=backend)
        except Exception:
            return {
                "action": "failed",
                "work_id": work_id,
                "series_title": series_title,
                "error": str(exc),
                "rollback_failed": True,
            }
        return {
            "action": "failed",
            "work_id": work_id,
            "series_title": series_title,
            "error": str(exc),
        }

    return {
        "action": "removed",
        "work_id": work_id,
        "series_title": series_title,
    }


@dataclass
class RemoveCommandHandler:
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
        page: int = 0,
    ) -> Dict[str, object]:
        items = self._load_items(watchlist_path=watchlist_path, state_path=state_path)
        if not items:
            return {"content": "現在、削除できる購読作品はありません。", "components": []}

        page_count = (len(items) + MAX_OPTIONS_PER_PAGE - 1) // MAX_OPTIONS_PER_PAGE
        page_index = min(max(int(page), 0), page_count - 1)
        start = page_index * MAX_OPTIONS_PER_PAGE
        page_items = items[start : start + MAX_OPTIONS_PER_PAGE]

        components: List[Dict[str, object]] = [
            {
                "type": ACTION_ROW,
                "components": [
                    {
                        "type": STRING_SELECT_COMPONENT,
                        "custom_id": "remove_select",
                        "placeholder": "削除する作品を選択",
                        "min_values": 1,
                        "max_values": 1,
                        "options": [
                            {
                                "label": item["label"],
                                "value": item["token"],
                                "description": item["description"],
                            }
                            for item in page_items
                        ],
                    }
                ],
            }
        ]
        content = "削除する作品を選んでください。\nこのあと確認画面を表示します。"

        if page_count > 1:
            content += f"\nページ {page_index + 1}/{page_count}"
            components.append(
                {
                    "type": ACTION_ROW,
                    "components": [
                        {
                            "type": BUTTON_COMPONENT,
                            "style": BUTTON_STYLE_SECONDARY,
                            "custom_id": f"remove_page:{max(page_index - 1, 0)}",
                            "label": "Prev",
                            "disabled": page_index == 0,
                        },
                        {
                            "type": BUTTON_COMPONENT,
                            "style": BUTTON_STYLE_PRIMARY,
                            "custom_id": f"remove_page:{min(page_index + 1, page_count - 1)}",
                            "label": "Next",
                            "disabled": page_index >= page_count - 1,
                        },
                    ],
                }
            )
        return {"content": content, "components": components}

    def handle_component(
        self,
        data: Mapping[str, object],
        *,
        watchlist_path: Optional[str] = None,
        state_path: Optional[str] = None,
    ) -> Dict[str, object]:
        custom_id = str(data.get("custom_id") or "").strip()
        if custom_id == "remove_select":
            values = data.get("values") or []
            token = str(values[0]) if values else ""
            item = self._find_item(token, watchlist_path=watchlist_path, state_path=state_path)
            if item is None:
                return {"content": "対象が見つかりませんでした。もう一度 `/remove` を実行してください。", "components": []}
            return {
                "content": f"「{item['label']}」を削除しますか？\nwatchlist と保存済み state から完全に削除します。",
                "components": [
                    {
                        "type": ACTION_ROW,
                        "components": [
                            {
                                "type": BUTTON_COMPONENT,
                                "style": BUTTON_STYLE_DANGER,
                                "custom_id": f"remove_confirm:{token}",
                                "label": "削除する",
                            },
                            {
                                "type": BUTTON_COMPONENT,
                                "style": BUTTON_STYLE_SECONDARY,
                                "custom_id": f"remove_cancel:{token}",
                                "label": "キャンセル",
                            },
                        ],
                    }
                ],
            }
        if custom_id.startswith("remove_page:"):
            _, _, raw_page = custom_id.partition(":")
            try:
                page = int(raw_page)
            except ValueError:
                return {"content": "画面の有効期限が切れたため、もう一度 `/remove` を実行してください。", "components": []}
            return self.start(watchlist_path=watchlist_path, state_path=state_path, page=page)
        if custom_id.startswith("remove_confirm:"):
            token = custom_id.partition(":")[2]
            item = self._find_item(token, watchlist_path=watchlist_path, state_path=state_path)
            if item is None:
                return {"content": "すでに削除済みです。", "components": []}
            result = remove_watch_subscription(
                item["work_id"],
                watchlist_path=watchlist_path,
                state_path=state_path,
                backend=self.backend,
                watchlist_loader=self.watchlist_loader,
                state_loader=self.state_loader,
                watchlist_saver=self.watchlist_saver,
                state_saver=self.state_saver,
            )
            if result["action"] == "removed":
                return {"content": f"削除しました: {item['label']}", "components": []}
            if result["action"] == "not_found":
                return {"content": "すでに削除済みです。", "components": []}
            return {"content": "削除に失敗しました。あとでもう一度試してください。", "components": []}
        if custom_id.startswith("remove_cancel:"):
            return {"content": "削除を取り消しました。", "components": []}
        return {"content": "画面の有効期限が切れたため、もう一度 `/remove` を実行してください。", "components": []}

    def _load_items(
        self,
        *,
        watchlist_path: Optional[str],
        state_path: Optional[str],
    ) -> List[Dict[str, str]]:
        watchlist = _call_loader(self.watchlist_loader, watchlist_path, backend=self.backend)
        state = _call_loader(self.state_loader, state_path, backend=self.backend)
        works = watchlist.get("works", [])
        state_works = state.get("works", {})
        items: List[Dict[str, str]] = []
        for entry in works:
            if not isinstance(entry, Mapping) or not bool(entry.get("enabled")):
                continue
            work_id = str(entry.get("id") or "").strip()
            if not work_id:
                continue
            state_entry = state_works.get(work_id, {}) if isinstance(state_works, Mapping) else {}
            latest = state_entry.get("latest", {}) if isinstance(state_entry, Mapping) else {}
            if latest is None or not isinstance(latest, Mapping):
                latest = {}
            items.append(
                {
                    "work_id": work_id,
                    "token": build_remove_token(work_id),
                    "label": _series_label(work_id, latest),
                    "description": _option_description(entry),
                }
            )
        return items

    def _find_item(
        self,
        token: str,
        *,
        watchlist_path: Optional[str],
        state_path: Optional[str],
    ) -> Optional[Dict[str, str]]:
        for item in self._load_items(watchlist_path=watchlist_path, state_path=state_path):
            if item["token"] == token:
                return item
        return None
