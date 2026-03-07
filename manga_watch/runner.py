#!/usr/bin/env python3
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from manga_watch.check import run_check
from manga_watch.storage import DEFAULT_WATCHLIST_PATH, load_state
from manga_watch.update_classification import DEFAULT_NOTIFY_UPDATE_TYPES

DEFAULT_CRAWL_SCHEDULE = "0 19 * * *"


def parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def format_timestamp(unix_ts: float, timezone_name: str) -> str:
    tz = ZoneInfo(timezone_name)
    return datetime.fromtimestamp(unix_ts, tz=tz).strftime("%Y-%m-%d %H:%M:%S %Z")


def split_message(content: str, limit: int = 2000) -> List[str]:
    if len(content) <= limit:
        return [content]

    chunks: List[str] = []
    current = ""
    for line in content.splitlines(keepends=True):
        if len(line) > limit:
            if current:
                chunks.append(current.rstrip("\n"))
                current = ""
            for idx in range(0, len(line), limit):
                chunks.append(line[idx : idx + limit].rstrip("\n"))
            continue

        if current and len(current) + len(line) > limit:
            chunks.append(current.rstrip("\n"))
            current = line
        else:
            current += line

    if current:
        chunks.append(current.rstrip("\n"))
    return chunks or [content[:limit]]


def latest_label(latest: Dict[str, str], fallback: str) -> str:
    return (
        latest.get("episode_title")
        or latest.get("episodeTitle")
        or latest.get("episode_code")
        or latest.get("episodeCode")
        or latest.get("url")
        or fallback
    )


def current_series_label(item_id: str, latest: Dict[str, str]) -> str:
    return (
        latest.get("series_title")
        or latest.get("seriesTitle")
        or latest.get("series")
        or item_id
    )


def update_type_for_event(update: Dict[str, object]) -> str:
    update_type = update.get("update_type")
    if isinstance(update_type, str) and update_type:
        return update_type

    latest = update.get("to", {}) or {}
    if isinstance(latest, dict):
        latest_type = latest.get("update_type")
        if isinstance(latest_type, str) and latest_type:
            return latest_type

    return "unknown"


def classification_reason_for_event(update: Dict[str, object]) -> Optional[str]:
    reason = update.get("classification_reason")
    if isinstance(reason, str) and reason:
        return reason

    latest = update.get("to", {}) or {}
    if isinstance(latest, dict):
        latest_reason = latest.get("classification_reason")
        if isinstance(latest_reason, str) and latest_reason:
            return latest_reason

    return None


def default_notify_for_event(update: Dict[str, object]) -> bool:
    if "default_notify" in update and update.get("default_notify") is not None:
        return bool(update.get("default_notify"))

    latest = update.get("to", {}) or {}
    if isinstance(latest, dict) and "default_notify" in latest and latest.get("default_notify") is not None:
        return bool(latest.get("default_notify"))

    return update_type_for_event(update) in DEFAULT_NOTIFY_UPDATE_TYPES


def partition_updates_by_default_notify(
    updates: List[Dict[str, object]],
) -> tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    notify = []
    suppressed = []
    for update in updates:
        if default_notify_for_event(update):
            notify.append(update)
        else:
            suppressed.append(update)
    return notify, suppressed


def format_update_message(updates: List[Dict[str, object]]) -> str:
    lines = ["新着エピソードを検知しました"]
    for update in updates:
        previous = update.get("from", {}) or {}
        latest = update.get("to", {}) or {}
        item_id = str(update.get("id") or "unknown")
        series = current_series_label(item_id, latest) or current_series_label(item_id, previous)
        before = latest_label(previous, "未取得")
        after = latest_label(latest, "不明")
        update_type = update_type_for_event(update)
        suffix = "" if update_type == "main_story" else f" [{update_type}]"
        lines.append(f"- {series}：{before} → {after}{suffix}")
        if update_type == "unknown":
            classification_reason = classification_reason_for_event(update)
            if classification_reason:
                lines.append(f"  判定理由: {classification_reason}")
        url = latest.get("url")
        if url:
            lines.append(f"  {url}")
    return "\n".join(lines)


def format_state_lines(state: Dict[str, object]) -> List[str]:
    works = state.get("works", {})
    if not isinstance(works, dict) or not works:
        return ["- まだ監視結果なし"]

    lines: List[str] = []
    for item_id in works.keys():
        latest = (works[item_id] or {}).get("latest", {})
        if not isinstance(latest, dict):
            latest = {}
        series = (
            str(latest.get("series_title") or latest.get("series") or item_id)
        )
        episode = str(latest.get("episode_title") or latest.get("episode_code") or latest.get("url") or "不明")
        lines.append(f"- {series}：{episode}")
    return lines


def normalize_checker_errors(result: Dict[str, object]) -> Dict[str, List[Dict[str, object]]]:
    errors = result.get("errors") or {"sources": [], "run": []}
    if not isinstance(errors, dict):
        raise RuntimeError("checker returned invalid errors payload")

    source_errors = errors.get("sources", [])
    run_errors = errors.get("run", [])
    if not isinstance(source_errors, list) or not isinstance(run_errors, list):
        raise RuntimeError("checker returned invalid errors payload")

    return {"sources": source_errors, "run": run_errors}


def checker_error_count(errors: Dict[str, List[Dict[str, object]]]) -> int:
    return len(errors["sources"]) + len(errors["run"])


def format_checker_error_lines(errors: Dict[str, List[Dict[str, object]]]) -> List[str]:
    total = checker_error_count(errors)
    lines = [f"エラー: {total}件"]
    if total == 0:
        return lines

    lines.append("エラー詳細:")
    for error in errors["sources"]:
        item = str(error.get("id") or error.get("url") or "unknown")
        phase = str(error.get("phase") or "unknown")
        kind = str(error.get("kind") or "runtime")
        message = str(error.get("message") or "unknown error")
        lines.append(f"- source/{kind} [{phase}] {item}: {message}")

    for error in errors["run"]:
        stage = str(error.get("stage") or "unknown")
        kind = str(error.get("kind") or "runtime")
        message = str(error.get("message") or "unknown error")
        lines.append(f"- run/{kind} [{stage}]: {message}")

    return lines


def format_run_report(
    *,
    timestamp: str,
    updates: List[Dict[str, object]],
    errors: Dict[str, List[Dict[str, object]]],
    state: Dict[str, object],
    default_notify_count: int,
    suppressed_update_count: int,
    update_notification_sent: bool,
) -> str:
    degraded = checker_error_count(errors) > 0
    lines = [
        f"{'巡回実行に一部失敗がありました' if degraded else '巡回実行しました'} ({timestamp})",
        f"更新検知: {len(updates)}件",
        f"既定通知対象: {default_notify_count}件",
        f"既定抑制: {suppressed_update_count}件",
        f"通知: {'送信した' if update_notification_sent else '送信なし'}",
    ]
    lines.extend(format_checker_error_lines(errors))
    lines.extend(
        [
        "現在のリスト:",
        ]
    )
    lines.extend(format_state_lines(state))
    return "\n".join(lines)


def format_failure_report(timestamp: str, exc: Exception) -> str:
    return "\n".join(
        [
            f"巡回実行に失敗しました ({timestamp})",
            f"エラー: {exc.__class__.__name__}: {exc}",
        ]
    )


@dataclass(frozen=True)
class RunnerConfig:
    discord_bot_token: str
    discord_main_channel_id: str
    discord_run_report_channel_id: str
    timezone_name: str
    watchlist_path: str
    crawl_schedule: Optional[str]
    crawl_interval: Optional[int]
    run_on_startup: bool
    request_timeout: int

    @classmethod
    def from_env(cls) -> "RunnerConfig":
        missing = [
            name
            for name in (
                "DISCORD_BOT_TOKEN",
                "DISCORD_MAIN_CHANNEL_ID",
                "DISCORD_RUN_REPORT_CHANNEL_ID",
            )
            if not os.environ.get(name)
        ]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        crawl_schedule = os.environ.get("CRAWL_SCHEDULE")
        crawl_interval_raw = os.environ.get("CRAWL_INTERVAL")
        if crawl_schedule and crawl_interval_raw:
            raise ValueError("Set either CRAWL_SCHEDULE or CRAWL_INTERVAL, not both")

        crawl_interval = None
        if crawl_interval_raw:
            crawl_interval = int(crawl_interval_raw)
            if crawl_interval <= 0:
                raise ValueError("CRAWL_INTERVAL must be a positive integer (seconds)")

        timezone_name = os.environ.get("TZ", "Asia/Tokyo")
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown TZ value: {timezone_name}") from exc

        return cls(
            discord_bot_token=os.environ["DISCORD_BOT_TOKEN"],
            discord_main_channel_id=os.environ["DISCORD_MAIN_CHANNEL_ID"],
            discord_run_report_channel_id=os.environ["DISCORD_RUN_REPORT_CHANNEL_ID"],
            timezone_name=timezone_name,
            watchlist_path=os.environ.get(
                "MANGA_WATCH_WATCHLIST",
                os.environ.get("MANGA_WATCH_URLS", DEFAULT_WATCHLIST_PATH),
            ),
            crawl_schedule=crawl_schedule or DEFAULT_CRAWL_SCHEDULE,
            crawl_interval=crawl_interval,
            run_on_startup=parse_bool(os.environ.get("RUN_ON_STARTUP"), default=True),
            request_timeout=int(os.environ.get("DISCORD_REQUEST_TIMEOUT", "30")),
        )


class DiscordClient:
    def __init__(self, token: str, timeout: int = 30, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.headers = {
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
        }

    def send_message(self, channel_id: str, content: str) -> None:
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        for chunk in split_message(content):
            response = self.session.post(
                url,
                headers=self.headers,
                json={"content": chunk, "allowed_mentions": {"parse": []}},
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                detail = response.text.strip().replace("\n", " ")
                raise RuntimeError(f"Discord API error {response.status_code}: {detail[:300]}")


def run_once(
    config: RunnerConfig,
    *,
    messenger: Optional[DiscordClient] = None,
    checker: Callable[[str], Dict[str, object]] = run_check,
    state_loader: Callable[[], Dict[str, object]] = load_state,
    now_fn: Callable[[], float] = time.time,
) -> Dict[str, object]:
    messenger = messenger or DiscordClient(
        token=config.discord_bot_token,
        timeout=config.request_timeout,
    )
    timestamp = format_timestamp(now_fn(), config.timezone_name)

    try:
        result = checker(config.watchlist_path)
        updates = result.get("updates", [])
        if not isinstance(updates, list):
            raise RuntimeError("checker returned invalid updates payload")
        errors = normalize_checker_errors(result)
        default_notify_updates, suppressed_updates = partition_updates_by_default_notify(updates)

        state = state_loader()
        update_notification_sent = False
        if default_notify_updates:
            messenger.send_message(
                config.discord_main_channel_id,
                format_update_message(default_notify_updates),
            )
            update_notification_sent = True

        messenger.send_message(
            config.discord_run_report_channel_id,
            format_run_report(
                timestamp=timestamp,
                updates=updates,
                errors=errors,
                state=state,
                default_notify_count=len(default_notify_updates),
                suppressed_update_count=len(suppressed_updates),
                update_notification_sent=update_notification_sent,
            ),
        )
        return {
            "ok": checker_error_count(errors) == 0,
            "updateCount": len(updates),
            "errorCount": checker_error_count(errors),
            "timestamp": timestamp,
        }
    except Exception as exc:
        try:
            messenger.send_message(
                config.discord_run_report_channel_id,
                format_failure_report(timestamp, exc),
            )
        except Exception as report_exc:
            print(
                f"[runner] failed to post run-report error summary: {report_exc}",
                file=sys.stderr,
                flush=True,
            )
        return {
            "ok": False,
            "updateCount": 0,
            "timestamp": timestamp,
            "error": f"{exc.__class__.__name__}: {exc}",
        }


def compute_next_run(config: RunnerConfig) -> datetime:
    from croniter import croniter

    now = datetime.now(ZoneInfo(config.timezone_name))
    if config.crawl_interval is not None:
        return now + timedelta(seconds=config.crawl_interval)
    iterator = croniter(config.crawl_schedule or DEFAULT_CRAWL_SCHEDULE, now)
    return iterator.get_next(datetime)


def sleep_until(target: datetime) -> None:
    while True:
        remaining = (target - datetime.now(target.tzinfo)).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 60))


def main() -> int:
    try:
        config = RunnerConfig.from_env()
    except Exception as exc:
        print(f"[runner] configuration error: {exc}", file=sys.stderr)
        return 2

    messenger = DiscordClient(
        token=config.discord_bot_token,
        timeout=config.request_timeout,
    )

    if config.run_on_startup:
        outcome = run_once(config, messenger=messenger)
        print(f"[runner] startup run: {outcome}", flush=True)

    while True:
        next_run = compute_next_run(config)
        print(
            f"[runner] next crawl scheduled for {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            flush=True,
        )
        sleep_until(next_run)
        outcome = run_once(config, messenger=messenger)
        print(f"[runner] scheduled run: {outcome}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
