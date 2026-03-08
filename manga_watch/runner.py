#!/usr/bin/env python3
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from manga_watch.check import run_check
from manga_watch.notifier import (
    Notifier,
    NotifierConfig,
    build_named_notifiers,
    build_update_event,
    detected_at_for_timestamp,
    event_from_payload,
)
from manga_watch.storage import DEFAULT_WATCHLIST_PATH, load_state, save_state
from manga_watch.update_classification import DEFAULT_NOTIFY_UPDATE_TYPES

DEFAULT_CRAWL_SCHEDULE = "0 19 * * *"
NOTIFICATION_OUTBOX_KEY = "notification_outbox"
INLINE_NOTIFIER_BACKEND = "__inline__"
TRIGGER_SOURCE_STARTUP = "startup"
TRIGGER_SOURCE_SCHEDULED = "scheduled"
TRIGGER_SOURCE_DISCORD_FETCH = "discord_fetch"
RUN_IN_PROGRESS_REASON = "run already in progress"
FETCH_ACCEPTED_MESSAGE = "手動 fetch を受け付けました。結果は daily notification / run report を確認してください。"
FETCH_REJECTED_MESSAGE = "現在巡回実行中であるため新しい fetch は開始しません。"


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


def should_notify_for_event(update: Dict[str, object]) -> bool:
    notification = update.get("notification")
    if isinstance(notification, dict) and notification.get("should_notify") is not None:
        return bool(notification.get("should_notify"))
    return default_notify_for_event(update)


def partition_updates_by_notification_policy(
    updates: List[Dict[str, object]],
) -> tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    notify = []
    suppressed = []
    for update in updates:
        if should_notify_for_event(update):
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


def resolve_named_notifiers(
    config: "RunnerConfig",
    *,
    notifier: Optional[Notifier] = None,
    named_notifiers: Optional[Mapping[str, Notifier]] = None,
) -> Dict[str, Notifier]:
    if named_notifiers is not None:
        return dict(named_notifiers)
    if notifier is not None:
        return {INLINE_NOTIFIER_BACKEND: notifier}
    return build_named_notifiers(config.notifier_config)


def load_notification_outbox(state: Dict[str, object]) -> List[Dict[str, object]]:
    outbox = state.get(NOTIFICATION_OUTBOX_KEY, [])
    if outbox is None:
        return []
    if not isinstance(outbox, list):
        raise RuntimeError("state.notification_outbox must be a list")

    normalized_entries: List[Dict[str, object]] = []
    for index, entry in enumerate(outbox):
        if not isinstance(entry, dict):
            raise RuntimeError(f"state.notification_outbox[{index}] must be an object")
        try:
            event = event_from_payload(entry.get("event") or {})
        except ValueError as exc:
            raise RuntimeError(f"state.notification_outbox[{index}] is invalid: {exc}") from exc

        pending_backends = entry.get("pending_backends", entry.get("pendingBackends", []))
        if pending_backends is None:
            pending_backends = []
        if not isinstance(pending_backends, list):
            raise RuntimeError(f"state.notification_outbox[{index}].pending_backends must be a list")

        normalized_pending_backends: List[str] = []
        seen_backends = set()
        for backend in pending_backends:
            normalized_backend = str(backend).strip()
            if not normalized_backend or normalized_backend in seen_backends:
                continue
            seen_backends.add(normalized_backend)
            normalized_pending_backends.append(normalized_backend)

        if not normalized_pending_backends:
            continue

        normalized_entries.append(
            {
                "event": event.as_payload(),
                "pending_backends": normalized_pending_backends,
                "attempt_count": max(0, int(entry.get("attempt_count", entry.get("attemptCount", 0)) or 0)),
                "last_attempted_at": str(entry.get("last_attempted_at", entry.get("lastAttemptedAt")) or "").strip()
                or None,
                "last_error": str(entry.get("last_error", entry.get("lastError")) or "").strip() or None,
            }
        )
    return normalized_entries


def set_notification_outbox(
    state: Dict[str, object],
    outbox: List[Dict[str, object]],
) -> None:
    state[NOTIFICATION_OUTBOX_KEY] = outbox


def enqueue_notification_events(
    state: Dict[str, object],
    *,
    events: List[object],
    backend_names: List[str],
) -> int:
    outbox = load_notification_outbox(state)
    existing_event_ids = {
        str(entry["event"].get("event_id") or "")
        for entry in outbox
    }
    enqueued = 0
    for event in events:
        event_id = str(event.event_id)
        if event_id in existing_event_ids:
            continue
        outbox.append(
            {
                "event": event.as_payload(),
                "pending_backends": list(backend_names),
                "attempt_count": 0,
                "last_attempted_at": None,
                "last_error": None,
            }
        )
        existing_event_ids.add(event_id)
        enqueued += 1
    set_notification_outbox(state, outbox)
    return enqueued


def deliver_notification_outbox(
    state: Dict[str, object],
    *,
    named_notifiers: Mapping[str, Notifier],
    attempted_at: str,
) -> Dict[str, object]:
    outbox = load_notification_outbox(state)
    remaining: List[Dict[str, object]] = []
    delivered_count = 0
    failures: List[str] = []

    for entry in outbox:
        event = event_from_payload(entry["event"])
        pending_backends: List[str] = []
        entry_failures: List[str] = []
        for backend_name in entry["pending_backends"]:
            backend_notifier = named_notifiers.get(backend_name)
            if backend_notifier is None:
                message = "notifier backend is not configured"
                pending_backends.append(backend_name)
                entry_failures.append(f"{backend_name}: {message}")
                failures.append(f"{event.event_id} {backend_name}: {message}")
                continue
            try:
                backend_notifier.send(event)
                delivered_count += 1
            except Exception as exc:
                pending_backends.append(backend_name)
                entry_failures.append(f"{backend_name}: {exc}")
                failures.append(f"{event.event_id} {backend_name}: {exc}")

        if pending_backends:
            remaining.append(
                {
                    "event": dict(entry["event"]),
                    "pending_backends": pending_backends,
                    "attempt_count": int(entry.get("attempt_count", 0)) + 1,
                    "last_attempted_at": attempted_at,
                    "last_error": "; ".join(entry_failures),
                }
            )

    set_notification_outbox(state, remaining)
    return {
        "attemptedEventCount": len(outbox),
        "deliveredCount": delivered_count,
        "remainingCount": len(remaining),
        "errors": failures,
    }


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
    trigger_source: str,
    updates: List[Dict[str, object]],
    errors: Dict[str, List[Dict[str, object]]],
    state: Dict[str, object],
    notified_update_count: int,
    suppressed_update_count: int,
    outbox_pending_count: int,
    update_notification_sent: bool,
) -> str:
    degraded = checker_error_count(errors) > 0
    lines = [
        f"{'巡回実行に一部失敗がありました' if degraded else '巡回実行しました'} ({timestamp})",
        f"トリガー: {trigger_source}",
        f"更新検知: {len(updates)}件",
        f"通知対象: {notified_update_count}件",
        f"通知抑制: {suppressed_update_count}件",
        f"通知outbox残件: {outbox_pending_count}件",
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


def format_failure_report(timestamp: str, trigger_source: str, exc: Exception) -> str:
    return "\n".join(
        [
            f"巡回実行に失敗しました ({timestamp})",
            f"トリガー: {trigger_source}",
            f"エラー: {exc.__class__.__name__}: {exc}",
        ]
    )


def format_replay_report(
    *,
    timestamp: str,
    attempted_event_count: int,
    remaining_count: int,
    delivered_count: int,
) -> str:
    return "\n".join(
        [
            f"通知 outbox を再送しました ({timestamp})",
            f"再送対象: {attempted_event_count}件",
            f"送信成功: {delivered_count}件",
            f"再送残件: {remaining_count}件",
        ]
    )


def format_replay_failure_report(timestamp: str, exc: Exception) -> str:
    return "\n".join(
        [
            f"通知 outbox の再送に失敗しました ({timestamp})",
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


def rejected_run_outcome(trigger_source: str, *, timestamp: str) -> Dict[str, object]:
    return {
        "ok": False,
        "accepted": False,
        "rejected": True,
        "updateCount": 0,
        "notifiedUpdateCount": 0,
        "suppressedUpdateCount": 0,
        "errorCount": 0,
        "outboxPendingCount": 0,
        "timestamp": timestamp,
        "triggerSource": trigger_source,
        "error": RUN_IN_PROGRESS_REASON,
    }


def run_once(
    config: RunnerConfig,
    *,
    notifier: Optional[Notifier] = None,
    named_notifiers: Optional[Mapping[str, Notifier]] = None,
    checker: Callable[[str], Dict[str, object]] = run_check,
    state_loader: Callable[[], Dict[str, object]] = load_state,
    state_saver: Callable[[Dict[str, object]], None] = save_state,
    now_fn: Callable[[], float] = time.time,
    report_logger: Callable[[str], None] = report_to_stdout,
    error_logger: Callable[[str], None] = report_to_stderr,
    trigger_source: str = TRIGGER_SOURCE_SCHEDULED,
) -> Dict[str, object]:
    named_notifiers = resolve_named_notifiers(
        config,
        notifier=notifier,
        named_notifiers=named_notifiers,
    )
    now = now_fn()
    timestamp = format_timestamp(now, config.timezone_name)
    detected_at = detected_at_for_timestamp(now)
    update_count = 0
    error_count = 0
    notified_update_count = 0
    suppressed_update_count = 0
    outbox_pending_count = 0

    try:
        result = checker(config.watchlist_path)
        updates = result.get("updates", [])
        if not isinstance(updates, list):
            raise RuntimeError("checker returned invalid updates payload")
        update_count = len(updates)
        errors = normalize_checker_errors(result)
        error_count = checker_error_count(errors)
        notify_updates, suppressed_updates = partition_updates_by_notification_policy(updates)
        notified_update_count = len(notify_updates)
        suppressed_update_count = len(suppressed_updates)

        state = state_loader()
        pending_events = []
        event_build_errors: List[str] = []
        for update in notify_updates:
            try:
                pending_events.append(build_update_event(update, detected_at=detected_at))
            except Exception as exc:
                work_id = str(update.get("work_id") or update.get("id") or "<unknown>")
                event_build_errors.append(f"{work_id}: {exc}")
        had_existing_outbox = bool(load_notification_outbox(state))
        enqueued_count = enqueue_notification_events(
            state,
            events=pending_events,
            backend_names=list(named_notifiers.keys()),
        )
        if enqueued_count > 0:
            state_saver(state)

        delivery = deliver_notification_outbox(
            state,
            named_notifiers=named_notifiers,
            attempted_at=detected_at,
        )
        outbox_pending_count = int(delivery["remainingCount"])
        update_notification_sent = int(delivery["deliveredCount"]) > 0
        if had_existing_outbox or enqueued_count > 0 or outbox_pending_count > 0:
            state_saver(state)
        failure_messages = list(event_build_errors)
        if delivery["errors"]:
            failure_messages.extend(delivery["errors"])
        if failure_messages:
            raise RuntimeError("notification delivery failed: " + "; ".join(failure_messages))

        report_logger(
            format_run_report(
                timestamp=timestamp,
                trigger_source=trigger_source,
                updates=updates,
                errors=errors,
                state=state,
                notified_update_count=notified_update_count,
                suppressed_update_count=suppressed_update_count,
                outbox_pending_count=outbox_pending_count,
                update_notification_sent=update_notification_sent,
            )
        )
        return {
            "ok": error_count == 0,
            "updateCount": update_count,
            "notifiedUpdateCount": notified_update_count,
            "suppressedUpdateCount": suppressed_update_count,
            "errorCount": error_count,
            "outboxPendingCount": outbox_pending_count,
            "timestamp": timestamp,
            "triggerSource": trigger_source,
        }
    except Exception as exc:
        error_logger(format_failure_report(timestamp, trigger_source, exc))
        return {
            "ok": False,
            "updateCount": update_count,
            "notifiedUpdateCount": notified_update_count,
            "suppressedUpdateCount": suppressed_update_count,
            "errorCount": error_count,
            "outboxPendingCount": outbox_pending_count,
            "timestamp": timestamp,
            "triggerSource": trigger_source,
            "error": f"{exc.__class__.__name__}: {exc}",
        }


@dataclass
class RunCoordinator:
    config: RunnerConfig
    notifier: Optional[Notifier] = None
    named_notifiers: Optional[Mapping[str, Notifier]] = None
    checker: Callable[[str], Dict[str, object]] = run_check
    state_loader: Callable[[], Dict[str, object]] = load_state
    state_saver: Callable[[Dict[str, object]], None] = save_state
    now_fn: Callable[[], float] = time.time
    report_logger: Callable[[str], None] = report_to_stdout
    error_logger: Callable[[str], None] = report_to_stderr
    thread_factory: Callable[..., threading.Thread] = threading.Thread
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def is_running(self) -> bool:
        return self._lock.locked()

    def _timestamp(self) -> str:
        return format_timestamp(self.now_fn(), self.config.timezone_name)

    def _run_once(self, *, trigger_source: str) -> Dict[str, object]:
        return run_once(
            self.config,
            notifier=self.notifier,
            named_notifiers=self.named_notifiers,
            checker=self.checker,
            state_loader=self.state_loader,
            state_saver=self.state_saver,
            now_fn=self.now_fn,
            report_logger=self.report_logger,
            error_logger=self.error_logger,
            trigger_source=trigger_source,
        )

    def _run_with_lock(self, *, trigger_source: str) -> Dict[str, object]:
        try:
            return self._run_once(trigger_source=trigger_source)
        finally:
            self._lock.release()

    def run(self, trigger_source: str) -> Dict[str, object]:
        if not self._lock.acquire(blocking=False):
            return rejected_run_outcome(trigger_source, timestamp=self._timestamp())
        return self._run_with_lock(trigger_source=trigger_source)

    def start_background(self, trigger_source: str) -> Dict[str, object]:
        if not self._lock.acquire(blocking=False):
            return rejected_run_outcome(trigger_source, timestamp=self._timestamp())

        thread = self.thread_factory(
            target=self._run_with_lock,
            kwargs={"trigger_source": trigger_source},
            daemon=True,
            name=f"manga-watch-{trigger_source}",
        )
        try:
            thread.start()
        except Exception:
            self._lock.release()
            raise

        return {
            "ok": True,
            "accepted": True,
            "background": True,
            "timestamp": self._timestamp(),
            "triggerSource": trigger_source,
        }


def handle_fetch_trigger(coordinator: RunCoordinator) -> Dict[str, object]:
    outcome = coordinator.start_background(TRIGGER_SOURCE_DISCORD_FETCH)
    if outcome.get("rejected"):
        outcome["message"] = FETCH_REJECTED_MESSAGE
        return outcome

    outcome["message"] = FETCH_ACCEPTED_MESSAGE
    return outcome


def replay_outbox_once(
    config: RunnerConfig,
    *,
    notifier: Optional[Notifier] = None,
    named_notifiers: Optional[Mapping[str, Notifier]] = None,
    state_loader: Callable[[], Dict[str, object]] = load_state,
    state_saver: Callable[[Dict[str, object]], None] = save_state,
    now_fn: Callable[[], float] = time.time,
    report_logger: Callable[[str], None] = report_to_stdout,
    error_logger: Callable[[str], None] = report_to_stderr,
) -> Dict[str, object]:
    named_notifiers = resolve_named_notifiers(
        config,
        notifier=notifier,
        named_notifiers=named_notifiers,
    )
    now = now_fn()
    timestamp = format_timestamp(now, config.timezone_name)
    detected_at = detected_at_for_timestamp(now)

    try:
        state = state_loader()
        delivery = deliver_notification_outbox(
            state,
            named_notifiers=named_notifiers,
            attempted_at=detected_at,
        )
        state_saver(state)
        if delivery["errors"]:
            raise RuntimeError("notification replay failed: " + "; ".join(delivery["errors"]))

        report_logger(
            format_replay_report(
                timestamp=timestamp,
                attempted_event_count=int(delivery["attemptedEventCount"]),
                delivered_count=int(delivery["deliveredCount"]),
                remaining_count=int(delivery["remainingCount"]),
            )
        )
        return {
            "ok": True,
            "attemptedEventCount": int(delivery["attemptedEventCount"]),
            "deliveredCount": int(delivery["deliveredCount"]),
            "remainingCount": int(delivery["remainingCount"]),
            "timestamp": timestamp,
        }
    except Exception as exc:
        error_logger(format_replay_failure_report(timestamp, exc))
        return {
            "ok": False,
            "attemptedEventCount": 0,
            "deliveredCount": 0,
            "remainingCount": 0,
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

    named_notifiers = build_named_notifiers(config.notifier_config)
    coordinator = RunCoordinator(
        config,
        named_notifiers=named_notifiers,
    )

    if config.run_on_startup:
        outcome = coordinator.run(TRIGGER_SOURCE_STARTUP)
        print(f"[runner] startup run: {outcome}", flush=True)

    while True:
        next_run = compute_next_run(config)
        print(
            f"[runner] next crawl scheduled for {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            flush=True,
        )
        sleep_until(next_run)
        outcome = coordinator.run(TRIGGER_SOURCE_SCHEDULED)
        print(f"[runner] scheduled run: {outcome}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
