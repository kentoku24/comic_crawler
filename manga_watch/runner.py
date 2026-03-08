#!/usr/bin/env python3
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from manga_watch.check import run_check
from manga_watch.notifier import (
    Notifier,
    NotifierConfig,
    build_notifier,
    build_update_event,
    detected_at_for_timestamp,
)
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
    timezone_name: str
    watchlist_path: str
    crawl_schedule: Optional[str]
    crawl_interval: Optional[int]
    run_on_startup: bool
    notifier_config: NotifierConfig

    @classmethod
    def from_env(cls) -> "RunnerConfig":
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
            timezone_name=timezone_name,
            watchlist_path=os.environ.get(
                "MANGA_WATCH_WATCHLIST",
                os.environ.get("MANGA_WATCH_URLS", DEFAULT_WATCHLIST_PATH),
            ),
            crawl_schedule=crawl_schedule or DEFAULT_CRAWL_SCHEDULE,
            crawl_interval=crawl_interval,
            run_on_startup=parse_bool(os.environ.get("RUN_ON_STARTUP"), default=True),
            notifier_config=NotifierConfig.from_env(),
        )


def report_to_stdout(content: str) -> None:
    print(content, flush=True)


def report_to_stderr(content: str) -> None:
    print(content, file=sys.stderr, flush=True)


def run_once(
    config: RunnerConfig,
    *,
    notifier: Optional[Notifier] = None,
    checker: Callable[[str], Dict[str, object]] = run_check,
    state_loader: Callable[[], Dict[str, object]] = load_state,
    now_fn: Callable[[], float] = time.time,
    report_logger: Callable[[str], None] = report_to_stdout,
    error_logger: Callable[[str], None] = report_to_stderr,
) -> Dict[str, object]:
    notifier = notifier or build_notifier(config.notifier_config)
    now = now_fn()
    timestamp = format_timestamp(now, config.timezone_name)
    detected_at = detected_at_for_timestamp(now)
    update_count = 0
    error_count = 0

    try:
        result = checker(config.watchlist_path)
        updates = result.get("updates", [])
        if not isinstance(updates, list):
            raise RuntimeError("checker returned invalid updates payload")
        update_count = len(updates)
        errors = normalize_checker_errors(result)
        error_count = checker_error_count(errors)
        default_notify_updates, suppressed_updates = partition_updates_by_default_notify(updates)

        state = state_loader()
        update_notification_sent = False
        delivery_errors: List[str] = []
        for update in default_notify_updates:
            try:
                notifier.send(build_update_event(update, detected_at=detected_at))
                update_notification_sent = True
            except Exception as exc:
                delivery_errors.append(str(exc))

        if delivery_errors:
            raise RuntimeError("notification delivery failed: " + "; ".join(delivery_errors))

        report_logger(
            format_run_report(
                timestamp=timestamp,
                updates=updates,
                errors=errors,
                state=state,
                default_notify_count=len(default_notify_updates),
                suppressed_update_count=len(suppressed_updates),
                update_notification_sent=update_notification_sent,
            )
        )
        return {
            "ok": error_count == 0,
            "updateCount": update_count,
            "errorCount": error_count,
            "timestamp": timestamp,
        }
    except Exception as exc:
        error_logger(format_failure_report(timestamp, exc))
        return {
            "ok": False,
            "updateCount": update_count,
            "errorCount": error_count,
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

    notifier = build_notifier(config.notifier_config)

    if config.run_on_startup:
        outcome = run_once(config, notifier=notifier)
        print(f"[runner] startup run: {outcome}", flush=True)

    while True:
        next_run = compute_next_run(config)
        print(
            f"[runner] next crawl scheduled for {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            flush=True,
        )
        sleep_until(next_run)
        outcome = run_once(config, notifier=notifier)
        print(f"[runner] scheduled run: {outcome}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
