from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Mapping, Optional, Protocol

from manga_watch.github_issue_reporting import build_unsupported_source_issue_reporter_from_env
from manga_watch.watchlist import WatchlistAddError, add_watchlist_url

ADD_COMMAND = "add"
ADD_FAILURE_MESSAGE = "作品追加に失敗しました。サーバーログを確認してください。"
ADD_MISSING_URL_MESSAGE = "追加する作品URLを `url` オプションで指定してください。"
UNSUPPORTED_SOURCE_REPORTED_MESSAGE = "未対応媒体として記録しました"
UNSUPPORTED_SOURCE_ALREADY_REPORTED_MESSAGE = "未対応媒体として既に記録済みです"
UNSUPPORTED_SOURCE_REPORT_FAILURE_MESSAGE = "未対応媒体の記録に失敗しました。サーバーログを確認してください。"


class UnsupportedSourceReporter(Protocol):
    def report_unsupported_source(self, *, url: str, error: WatchlistAddError) -> Mapping[str, object]:
        ...


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
    unsupported_source_reporter: Optional[UnsupportedSourceReporter] = None

    @classmethod
    def from_env(cls) -> "AddCommandHandler":
        return cls(
            add_subscription=add_watchlist_url,
            unsupported_source_reporter=build_unsupported_source_issue_reporter_from_env(),
        )

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
            if exc.kind == "unsupported_source" and self.unsupported_source_reporter is not None:
                return self._report_unsupported_source(normalized_url, exc)
            return {"content": format_watchlist_add_error(exc)}
        except Exception:
            return {"content": ADD_FAILURE_MESSAGE}
        return {"content": format_watchlist_add_response(result)}

    def _report_unsupported_source(self, url: str, exc: WatchlistAddError) -> Dict[str, object]:
        lines = [format_watchlist_add_error(exc)]
        try:
            outcome = self.unsupported_source_reporter.report_unsupported_source(url=url, error=exc)
        except Exception:
            lines.append(UNSUPPORTED_SOURCE_REPORT_FAILURE_MESSAGE)
            return {"content": "\n".join(lines)}

        issue_number = str(outcome.get("issue_number") or "").strip()
        issue_url = str(outcome.get("issue_url") or "").strip()
        action = str(outcome.get("action") or "").strip().lower()
        if action == "duplicate":
            message = UNSUPPORTED_SOURCE_ALREADY_REPORTED_MESSAGE
        else:
            message = UNSUPPORTED_SOURCE_REPORTED_MESSAGE
        if issue_number:
            lines.append(f"{message}: #{issue_number}")
        else:
            lines.append(message)
        if issue_url:
            lines.append(issue_url)
        return {"content": "\n".join(lines)}
