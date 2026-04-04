from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Mapping, Optional

from manga_watch.watchlist import WatchlistAddError, add_watchlist_url

ADD_COMMAND = "add"
ADD_FAILURE_MESSAGE = "作品追加に失敗しました。サーバーログを確認してください。"
ADD_MISSING_URL_MESSAGE = "追加する作品URLを `url` オプションで指定してください。"


def format_watchlist_add_response(result: Mapping[str, object]) -> str:
    action = str(result.get("action") or "").strip()
    entry = result.get("entry")
    existing = result.get("existing")
    entry_payload = entry if isinstance(entry, Mapping) else {}
    existing_payload = existing if isinstance(existing, Mapping) else {}

    work_id = str(entry_payload.get("id") or existing_payload.get("id") or "").strip()
    seed_url = str(entry_payload.get("seed_url") or existing_payload.get("seed_url") or "").strip()

    lines = []
    if action == "added":
        lines.append(f"追加しました: {work_id}")
    elif action == "duplicate":
        lines.append(f"既に登録済みです: {work_id}")
    else:
        lines.append("作品追加を受け付けました。")
    if seed_url:
        lines.append(f"seed_url: {seed_url}")
    return "\n".join(lines)


def format_watchlist_add_error(exc: WatchlistAddError) -> str:
    return f"追加できませんでした: {exc.message}"


@dataclass
class AddCommandHandler:
    add_subscription: Callable[..., Mapping[str, object]] = add_watchlist_url

    def start(
        self,
        *,
        url: Optional[str],
        watchlist_path: Optional[str] = None,
    ) -> Dict[str, object]:
        normalized_url = str(url or "").strip()
        if not normalized_url:
            return {"content": ADD_MISSING_URL_MESSAGE}
        try:
            result = self.add_subscription(normalized_url, watchlist_path=watchlist_path)
        except WatchlistAddError as exc:
            return {"content": format_watchlist_add_error(exc)}
        except Exception:
            return {"content": ADD_FAILURE_MESSAGE}
        return {"content": format_watchlist_add_response(result)}
