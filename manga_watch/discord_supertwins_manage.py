from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional

from manga_watch.discord_text import series_label_for_snapshot
from manga_watch.storage import load_state, load_watchlist, save_state, save_watchlist
from manga_watch.supertwins import (
    clear_pending_action,
    get_pending_action,
    list_group_members,
    list_groups,
    prune_empty_groups,
    remove_group_members,
    set_pending_action,
    upsert_watchlist_entry,
)

SUPERTWINS_MANAGE_COMMAND = "supertwins-manage"
SUPERTWINS_MANAGE_COMPONENT_PREFIX = "supertwins_manage:"
SUPERTWINS_MANAGE_GROUP_SELECT = "supertwins_manage_group_select"
SUPERTWINS_MANAGE_MEMBER_SELECT_PREFIX = f"{SUPERTWINS_MANAGE_COMPONENT_PREFIX}members:"
SUPERTWINS_MANAGE_ACTION_SELECT_PREFIX = f"{SUPERTWINS_MANAGE_COMPONENT_PREFIX}action:"
SUPERTWINS_MANAGE_CONFIRM_DELETE_PREFIX = f"{SUPERTWINS_MANAGE_COMPONENT_PREFIX}confirm_delete:"
SUPERTWINS_MANAGE_CANCEL_PREFIX = f"{SUPERTWINS_MANAGE_COMPONENT_PREFIX}cancel:"
SUPERTWINS_MANAGE_EMPTY_MESSAGE = "まだ supertwins グループはありません。"
SUPERTWINS_MANAGE_GROUP_PROMPT = "編集する supertwins グループを選んでください。"
SUPERTWINS_MANAGE_MEMBER_PROMPT = "解除する member を選んでください。"
SUPERTWINS_MANAGE_ACTION_PROMPT = "member を group から外したあと、どう扱うか選んでください。"
SUPERTWINS_MANAGE_DELETE_CONFIRM_PROMPT = "選択した subscription を削除します。よければ confirm を押してください。"
SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE = (
    "画面の有効期限が切れたため、もう一度 `/supertwins-manage` を実行してください。"
)
SUPERTWINS_MANAGE_DELETE_CANCEL_MESSAGE = "削除を取り消しました。"
SUPERTWINS_MANAGE_DELETE_CONFIRM_MESSAGE = "選択した subscription を削除しました。"
SUPERTWINS_MANAGE_KEEP_HIDDEN_MESSAGE = "member を group から外し、subscription は hidden のまま残しました。"
SUPERTWINS_MANAGE_UNHIDE_MESSAGE = "member を group から外し、subscription の hidden を解除しました。"

ACTION_ROW = 1
BUTTON_COMPONENT = 2
STRING_SELECT_COMPONENT = 3
BUTTON_STYLE_PRIMARY = 1
BUTTON_STYLE_SECONDARY = 2
BUTTON_STYLE_DANGER = 4
MAX_OPTIONS_PER_PAGE = 25
MAX_COMPONENT_TEXT = 100


def is_supertwins_manage_component(custom_id: object) -> bool:
    normalized = str(custom_id or "").strip()
    return normalized.startswith(SUPERTWINS_MANAGE_COMPONENT_PREFIX) or normalized == SUPERTWINS_MANAGE_GROUP_SELECT


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


def _state_works(state: Mapping[str, object]) -> Mapping[str, object]:
    works = state.get("works", {})
    return works if isinstance(works, Mapping) else {}


def _group_options(groups: List[Dict[str, object]]) -> List[Dict[str, str]]:
    options: List[Dict[str, str]] = []
    for group in groups[:MAX_OPTIONS_PER_PAGE]:
        group_id = str(group["group_id"])
        member_count = len(group["member_work_ids"])
        options.append(
            {
                "label": _truncate_component_text(f"{group_id} ({member_count}件)"),
                "value": group_id,
                "description": _truncate_component_text(
                    " / ".join(group["member_work_ids"][:3]) if group["member_work_ids"] else "member なし"
                ),
            }
        )
    return options


def _member_options(state: Mapping[str, object], group_id: str) -> List[Dict[str, str]]:
    options: List[Dict[str, str]] = []
    works = _state_works(state)
    for member_work_id in list_group_members(state, group_id)[:MAX_OPTIONS_PER_PAGE]:
        state_entry = works.get(member_work_id, {}) if isinstance(works, Mapping) else {}
        latest = state_entry.get("latest", {}) if isinstance(state_entry, Mapping) else {}
        if latest is None or not isinstance(latest, Mapping):
            latest = {}
        options.append(
            {
                "label": _truncate_component_text(series_label_for_snapshot(member_work_id, latest)),
                "value": member_work_id,
                "description": _truncate_component_text(member_work_id),
            }
        )
    return options


def _action_options() -> List[Dict[str, str]]:
    return [
        {"label": "hidden のまま残す", "value": "keep_hidden", "description": "group からだけ外します"},
        {"label": "hidden を解除", "value": "unhide", "description": "group から外して表示対象に戻します"},
        {"label": "subscription を削除", "value": "delete", "description": "watchlist と state から削除します"},
    ]


def _pending_token(custom_id: str, prefix: str) -> str:
    return custom_id[len(prefix) :]


def _session_token(group_id: str, member_work_ids: List[str]) -> str:
    material = f"{group_id}:{','.join(sorted(member_work_ids))}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _clone_payload(payload: Mapping[str, object]) -> Dict[str, object]:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _notification_event_work_id(entry: object) -> Optional[str]:
    if not isinstance(entry, Mapping):
        return None
    event = entry.get("event")
    if not isinstance(event, Mapping):
        return None
    work_id = str(event.get("work_id") or event.get("workId") or "").strip()
    return work_id or None


def _pending_message_mentions_work(entry: object, work_id: str) -> bool:
    if not isinstance(entry, Mapping):
        return False
    message_keys = entry.get("message_keys", [])
    if not isinstance(message_keys, list):
        return False
    for message_key in message_keys:
        if not isinstance(message_key, Mapping):
            continue
        current_work_id = str(message_key.get("work_id") or message_key.get("workId") or "").strip()
        if current_work_id == work_id:
            return True
    return False


def _prune_delivery_state_for_works(
    state: Mapping[str, object],
    work_ids: List[str],
) -> Dict[str, object]:
    updated_state = _clone_payload(state)
    works = updated_state.setdefault("works", {})
    if isinstance(works, dict):
        for work_id in work_ids:
            works.pop(work_id, None)

    notification_outbox = updated_state.get("notification_outbox", [])
    if isinstance(notification_outbox, list):
        updated_state["notification_outbox"] = [
            entry
            for entry in notification_outbox
            if _notification_event_work_id(entry) not in work_ids
        ]

    discord_delivery = updated_state.get("discord_delivery")
    if isinstance(discord_delivery, dict):
        daily_notification = discord_delivery.get("daily_notification")
        if isinstance(daily_notification, dict):
            delivered_latest_keys = daily_notification.get("delivered_latest_keys")
            if isinstance(delivered_latest_keys, dict):
                for work_id in work_ids:
                    delivered_latest_keys.pop(work_id, None)
            pending_messages = daily_notification.get("pending_messages", [])
            if isinstance(pending_messages, list):
                daily_notification["pending_messages"] = [
                    entry
                    for entry in pending_messages
                    if all(not _pending_message_mentions_work(entry, work_id) for work_id in work_ids)
                ]
    return updated_state


def _update_hidden_flags(
    watchlist: Mapping[str, object],
    work_ids: List[str],
    *,
    hidden: bool,
) -> Dict[str, object]:
    updated_watchlist = dict(watchlist)
    for work_id in work_ids:
        works = updated_watchlist.get("works", [])
        if not isinstance(works, list):
            raise ValueError("watchlist.works must be a list")
        entry = None
        for candidate in works:
            if str(candidate.get("id")) == work_id:
                entry = candidate
                break
        if entry is None:
            raise ValueError(f"watchlist entry not found: {work_id}")
        result = upsert_watchlist_entry(updated_watchlist, entry, hidden=hidden)
        updated_watchlist = result["watchlist"]
    return updated_watchlist


def _delete_subscriptions(
    watchlist: Mapping[str, object],
    state: Mapping[str, object],
    work_ids: List[str],
) -> tuple[Dict[str, object], Dict[str, object]]:
    updated_watchlist = _clone_payload(watchlist)
    updated_state = _clone_payload(state)
    works = updated_watchlist.get("works", [])
    if not isinstance(works, list):
        raise ValueError("watchlist.works must be a list")

    updated_watchlist["works"] = [
        dict(entry)
        for entry in works
        if str(entry.get("id") or "").strip() not in set(work_ids)
    ]
    updated_state = _prune_delivery_state_for_works(updated_state, work_ids)
    return updated_watchlist, updated_state


@dataclass
class ManageSupertwinsCommandHandler:
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
        del watchlist_path
        state = _call_loader(self.state_loader, state_path, backend=self.backend)
        groups = list_groups(state)
        if not groups:
            return {"content": SUPERTWINS_MANAGE_EMPTY_MESSAGE, "components": []}

        return {
            "content": SUPERTWINS_MANAGE_GROUP_PROMPT,
            "components": [
                {
                    "type": ACTION_ROW,
                    "components": [
                        {
                            "type": STRING_SELECT_COMPONENT,
                            "custom_id": SUPERTWINS_MANAGE_GROUP_SELECT,
                            "placeholder": "編集する group を選択",
                            "min_values": 1,
                            "max_values": 1,
                            "options": _group_options(groups),
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
        state_path: Optional[str] = None,
    ) -> Dict[str, object]:
        custom_id = str(data.get("custom_id") or "").strip()
        if custom_id == SUPERTWINS_MANAGE_GROUP_SELECT:
            return self._handle_group_selection(data, state_path=state_path)
        if custom_id.startswith(SUPERTWINS_MANAGE_MEMBER_SELECT_PREFIX):
            return self._handle_member_selection(custom_id, data, state_path=state_path)
        if custom_id.startswith(SUPERTWINS_MANAGE_ACTION_SELECT_PREFIX):
            return self._handle_action_selection(
                custom_id,
                data,
                watchlist_path=watchlist_path,
                state_path=state_path,
            )
        if custom_id.startswith(SUPERTWINS_MANAGE_CONFIRM_DELETE_PREFIX):
            return self._handle_confirm_delete(
                custom_id,
                watchlist_path=watchlist_path,
                state_path=state_path,
            )
        if custom_id.startswith(SUPERTWINS_MANAGE_CANCEL_PREFIX):
            return self._handle_cancel(custom_id, state_path=state_path)
        return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}

    def _handle_group_selection(
        self,
        data: Mapping[str, object],
        *,
        state_path: Optional[str],
    ) -> Dict[str, object]:
        values = [str(value).strip() for value in data.get("values") or [] if str(value).strip()]
        group_id = values[0] if values else ""
        if not group_id:
            return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}

        state = _call_loader(self.state_loader, state_path, backend=self.backend)
        try:
            member_options = _member_options(state, group_id)
        except ValueError:
            return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}
        if not member_options:
            return {"content": "この group には member がありません。", "components": []}

        return {
            "content": SUPERTWINS_MANAGE_MEMBER_PROMPT,
            "components": [
                {
                    "type": ACTION_ROW,
                    "components": [
                        {
                            "type": STRING_SELECT_COMPONENT,
                            "custom_id": f"{SUPERTWINS_MANAGE_MEMBER_SELECT_PREFIX}{group_id}",
                            "placeholder": "解除する member を選択",
                            "min_values": 1,
                            "max_values": min(len(member_options), MAX_OPTIONS_PER_PAGE),
                            "options": member_options,
                        }
                    ],
                }
            ],
        }

    def _handle_member_selection(
        self,
        custom_id: str,
        data: Mapping[str, object],
        *,
        state_path: Optional[str],
    ) -> Dict[str, object]:
        group_id = _pending_token(custom_id, SUPERTWINS_MANAGE_MEMBER_SELECT_PREFIX)
        selected_members = [str(value).strip() for value in data.get("values") or [] if str(value).strip()]
        if not group_id or not selected_members:
            return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}

        state = _call_loader(self.state_loader, state_path, backend=self.backend)
        try:
            pending_token = _session_token(group_id, selected_members)
            updated = set_pending_action(
                state,
                pending_token,
                {
                    "group_id": group_id,
                    "member_work_ids": selected_members,
                },
            )
            _call_saver(self.state_saver, updated, state_path, backend=self.backend)
        except Exception:
            return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}

        return {
            "content": SUPERTWINS_MANAGE_ACTION_PROMPT,
            "components": [
                {
                    "type": ACTION_ROW,
                    "components": [
                        {
                            "type": STRING_SELECT_COMPONENT,
                            "custom_id": f"{SUPERTWINS_MANAGE_ACTION_SELECT_PREFIX}{pending_token}",
                            "placeholder": "処理を選択",
                            "min_values": 1,
                            "max_values": 1,
                            "options": _action_options(),
                        }
                    ],
                }
            ],
        }

    def _handle_action_selection(
        self,
        custom_id: str,
        data: Mapping[str, object],
        *,
        watchlist_path: Optional[str],
        state_path: Optional[str],
    ) -> Dict[str, object]:
        token = _pending_token(custom_id, SUPERTWINS_MANAGE_ACTION_SELECT_PREFIX)
        action = _coerce_text((data.get("values") or [None])[0]) or ""
        if not token or not action:
            return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}

        state = _call_loader(self.state_loader, state_path, backend=self.backend)
        try:
            pending = get_pending_action(state, token)
        except ValueError:
            return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}

        if action == "delete":
            return {
                "content": SUPERTWINS_MANAGE_DELETE_CONFIRM_PROMPT,
                "components": [
                    {
                        "type": ACTION_ROW,
                        "components": [
                            {
                                "type": BUTTON_COMPONENT,
                                "style": BUTTON_STYLE_DANGER,
                                "custom_id": f"{SUPERTWINS_MANAGE_CONFIRM_DELETE_PREFIX}{token}",
                                "label": "confirm",
                            },
                            {
                                "type": BUTTON_COMPONENT,
                                "style": BUTTON_STYLE_SECONDARY,
                                "custom_id": f"{SUPERTWINS_MANAGE_CANCEL_PREFIX}{token}",
                                "label": "cancel",
                            },
                        ],
                    }
                ],
            }

        return self._apply_action(
            token,
            pending,
            action=action,
            watchlist_path=watchlist_path,
            state_path=state_path,
        )

    def _handle_confirm_delete(
        self,
        custom_id: str,
        *,
        watchlist_path: Optional[str],
        state_path: Optional[str],
    ) -> Dict[str, object]:
        token = _pending_token(custom_id, SUPERTWINS_MANAGE_CONFIRM_DELETE_PREFIX)
        if not token:
            return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}
        state = _call_loader(self.state_loader, state_path, backend=self.backend)
        try:
            pending = get_pending_action(state, token)
        except ValueError:
            return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}
        return self._delete_action(token, pending, watchlist_path=watchlist_path, state_path=state_path)

    def _handle_cancel(
        self,
        custom_id: str,
        *,
        state_path: Optional[str],
    ) -> Dict[str, object]:
        token = _pending_token(custom_id, SUPERTWINS_MANAGE_CANCEL_PREFIX)
        if not token:
            return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}

        state = _call_loader(self.state_loader, state_path, backend=self.backend)
        try:
            updated = clear_pending_action(state, token)
            _call_saver(self.state_saver, updated, state_path, backend=self.backend)
        except Exception:
            return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}
        return {"content": SUPERTWINS_MANAGE_DELETE_CANCEL_MESSAGE, "components": []}

    def _apply_action(
        self,
        token: str,
        pending: Mapping[str, object],
        *,
        action: str,
        watchlist_path: Optional[str],
        state_path: Optional[str],
    ) -> Dict[str, object]:
        group_id = str(pending.get("group_id") or "").strip()
        member_work_ids = [str(value).strip() for value in pending.get("member_work_ids") or [] if str(value).strip()]
        if not group_id or not member_work_ids:
            return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}

        original_state = _call_loader(self.state_loader, state_path, backend=self.backend)
        original_watchlist = _call_loader(self.watchlist_loader, watchlist_path, backend=self.backend)

        try:
            updated_state = remove_group_members(original_state, group_id, member_work_ids)
            updated_state = prune_empty_groups(updated_state)
        except ValueError:
            return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}

        if action == "keep_hidden":
            try:
                updated_watchlist = _update_hidden_flags(original_watchlist, member_work_ids, hidden=True)
            except Exception:
                return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}
            message = SUPERTWINS_MANAGE_KEEP_HIDDEN_MESSAGE
        elif action == "unhide":
            try:
                updated_watchlist = _update_hidden_flags(original_watchlist, member_work_ids, hidden=False)
            except Exception:
                return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}
            message = SUPERTWINS_MANAGE_UNHIDE_MESSAGE
        else:
            return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}

        cleaned_state = clear_pending_action(updated_state, token)
        try:
            _call_saver(self.watchlist_saver, updated_watchlist, watchlist_path, backend=self.backend)
            _call_saver(self.state_saver, cleaned_state, state_path, backend=self.backend)
        except Exception as exc:
            try:
                _call_saver(self.watchlist_saver, original_watchlist, watchlist_path, backend=self.backend)
            except Exception:
                pass
            try:
                _call_saver(self.state_saver, original_state, state_path, backend=self.backend)
            except Exception:
                pass
            return {"content": f"supertwins 操作に失敗しました: {exc}", "components": []}

        return {"content": message, "components": []}

    def _delete_action(
        self,
        token: str,
        pending: Mapping[str, object],
        *,
        watchlist_path: Optional[str],
        state_path: Optional[str],
    ) -> Dict[str, object]:
        group_id = str(pending.get("group_id") or "").strip()
        member_work_ids = [str(value).strip() for value in pending.get("member_work_ids") or [] if str(value).strip()]
        if not group_id or not member_work_ids:
            return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}

        original_state = _call_loader(self.state_loader, state_path, backend=self.backend)
        original_watchlist = _call_loader(self.watchlist_loader, watchlist_path, backend=self.backend)

        try:
            updated_state = remove_group_members(original_state, group_id, member_work_ids)
            updated_state = prune_empty_groups(updated_state)
            updated_watchlist, updated_state = _delete_subscriptions(original_watchlist, updated_state, member_work_ids)
        except Exception:
            return {"content": SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE, "components": []}

        cleaned_state = clear_pending_action(updated_state, token)
        try:
            _call_saver(self.watchlist_saver, updated_watchlist, watchlist_path, backend=self.backend)
            _call_saver(self.state_saver, cleaned_state, state_path, backend=self.backend)
        except Exception as exc:
            try:
                _call_saver(self.watchlist_saver, original_watchlist, watchlist_path, backend=self.backend)
            except Exception:
                pass
            try:
                _call_saver(self.state_saver, original_state, state_path, backend=self.backend)
            except Exception:
                pass
            return {"content": f"{SUPERTWINS_MANAGE_COMPONENT_STALE_MESSAGE}\n削除に失敗しました: {exc}", "components": []}

        return {"content": SUPERTWINS_MANAGE_DELETE_CONFIRM_MESSAGE, "components": []}
