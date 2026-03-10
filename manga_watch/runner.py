#!/usr/bin/env python3
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from manga_watch.check import CheckRunError, run_check
from manga_watch.discord_outbound import (
    DiscordChannelClient,
    DiscordOutboundConfig,
    DiscordTransport,
    build_run_report_message,
    deliver_daily_notifications,
    enqueue_daily_notification,
    format_run_report_delivery_failure,
    pending_daily_notification_count,
)
from manga_watch.discord_text import episode_label_for_snapshot, series_label_for_snapshot
from manga_watch.notifier import (
    Notifier,
    NotifierConfig,
    build_named_notifiers,
    build_update_event,
    detected_at_for_timestamp,
    event_from_payload,
)
from manga_watch.storage import DEFAULT_WATCHLIST_PATH, get_state_path, load_state, save_state
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
    if not isinstance(state, Mapping):
        return ["- 最新状態を取得できませんでした"]

    works = state.get("works", {})
    if not isinstance(works, Mapping) or not works:
        return ["- まだ監視結果なし"]

    lines: List[str] = []
    for item_id in works.keys():
        latest = (works[item_id] or {}).get("latest", {})
        if not isinstance(latest, Mapping):
            latest = {}
        series = series_label_for_snapshot(item_id, latest)
        episode = episode_label_for_snapshot(latest, fallback="不明")
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


def runner_error_record(stage: str, exc: Exception) -> Dict[str, str]:
    return {
        "stage": stage,
        "kind": "runtime",
        "errorType": exc.__class__.__name__,
        "message": str(exc),
    }


@dataclass(frozen=True)
class RunnerConfig:
    timezone_name: str
    watchlist_path: str
    crawl_schedule: Optional[str]
    crawl_interval: Optional[int]
    run_on_startup: bool
    notifier_config: NotifierConfig
    discord_outbound_config: Optional[DiscordOutboundConfig] = None

    @classmethod
    def from_env(cls, *, require_discord: bool = True) -> "RunnerConfig":
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
            discord_outbound_config=(
                DiscordOutboundConfig.from_env()
                if require_discord
                else None
            ),
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
    discord_client: Optional[DiscordTransport] = None,
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
    resolved_discord_client = discord_client
    if resolved_discord_client is None and config.discord_outbound_config is not None:
        resolved_discord_client = DiscordChannelClient(config.discord_outbound_config)
    now = now_fn()
    timestamp = format_timestamp(now, config.timezone_name)
    detected_at = detected_at_for_timestamp(now)
    updates: List[Dict[str, object]] = []
    errors: Dict[str, List[Dict[str, object]]] = {"sources": [], "run": []}
    delivery_failures: List[str] = []
    state: Optional[Dict[str, object]] = None
    primary_failure: Optional[Exception] = None
    run_report_delivery_error: Optional[Exception] = None
    update_count = 0
    notified_update_count = 0
    suppressed_update_count = 0
    outbox_pending_count = 0
    daily_notification_sent = False

    try:
        result = checker(config.watchlist_path)
        updates = result.get("updates", [])
        if not isinstance(updates, list):
            raise RuntimeError("checker returned invalid updates payload")
        errors = normalize_checker_errors(result)
    except CheckRunError as exc:
        primary_failure = exc.original_error
        result = exc.result
        raw_updates = result.get("updates", [])
        if isinstance(raw_updates, list):
            updates = raw_updates
        try:
            errors = normalize_checker_errors(result)
        except Exception as normalize_exc:
            errors = {"sources": [], "run": [runner_error_record("normalize_checker_errors", normalize_exc)]}
    except Exception as exc:
        primary_failure = exc
        errors["run"].append(runner_error_record("checker", exc))

    update_count = len(updates)
    notify_updates, suppressed_updates = partition_updates_by_notification_policy(updates)
    notified_update_count = len(notify_updates)
    suppressed_update_count = len(suppressed_updates)
    checker_completed = primary_failure is None

    try:
        state = state_loader()
    except Exception as exc:
        errors["run"].append(runner_error_record("load_runner_state", exc))
        if primary_failure is None:
            primary_failure = exc

    if state is None:
        state = {}

    if checker_completed and isinstance(state, dict):
        try:
            pending_events = []
            for update in notify_updates:
                try:
                    pending_events.append(build_update_event(update, detected_at=detected_at))
                except Exception as exc:
                    work_id = str(update.get("work_id") or update.get("id") or "<unknown>")
                    errors["run"].append(
                        runner_error_record(
                            "build_update_event",
                            RuntimeError(f"{work_id}: {exc}"),
                        )
                    )

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
            if had_existing_outbox or enqueued_count > 0 or outbox_pending_count > 0:
                state_saver(state)
            if delivery["errors"]:
                delivery_failures.extend(delivery["errors"])
        except Exception as exc:
            errors["run"].append(runner_error_record("generic_notification", exc))
            if primary_failure is None:
                primary_failure = exc

        if resolved_discord_client is not None and config.discord_outbound_config is not None:
            try:
                enqueue_result = enqueue_daily_notification(
                    state,
                    updates=notify_updates,
                    channel_id=config.discord_outbound_config.main_channel_id,
                    now_ts=now,
                    timezone_name=config.timezone_name,
                    created_at=detected_at,
                )
                if enqueue_result["queued"]:
                    state_saver(state)

                daily_delivery = deliver_daily_notifications(
                    state,
                    client=resolved_discord_client,
                    attempted_at=detected_at,
                )
                daily_notification_sent = int(daily_delivery["deliveredCount"]) > 0
                if enqueue_result["queued"] or int(daily_delivery["attemptedCount"]) > 0:
                    state_saver(state)
                if daily_delivery["errors"]:
                    delivery_failures.extend(daily_delivery["errors"])
            except Exception as exc:
                errors["run"].append(runner_error_record("discord_daily_notification", exc))
                if primary_failure is None:
                    primary_failure = exc

    error_count = checker_error_count(errors)
    daily_notification_pending_count = pending_daily_notification_count(state)
    run_report = build_run_report_message(
        timestamp=timestamp,
        trigger_source=trigger_source,
        update_count=update_count,
        notified_update_count=notified_update_count,
        suppressed_update_count=suppressed_update_count,
        outbox_pending_count=outbox_pending_count,
        daily_notification_sent=daily_notification_sent,
        daily_notification_pending_count=daily_notification_pending_count,
        errors=errors,
        delivery_failures=delivery_failures,
        state_lines=format_state_lines(state),
    )

    if resolved_discord_client is not None and config.discord_outbound_config is not None:
        try:
            resolved_discord_client.send_message(
                config.discord_outbound_config.run_report_channel_id,
                run_report,
            )
        except Exception as exc:
            run_report_delivery_error = exc
            error_logger(
                format_run_report_delivery_failure(
                    timestamp=timestamp,
                    trigger_source=trigger_source,
                    exc=exc,
                )
            )

    if not errors["run"] and not delivery_failures and run_report_delivery_error is None:
        report_logger(run_report)

    if primary_failure is None and delivery_failures:
        primary_failure = RuntimeError("notification delivery failed: " + "; ".join(delivery_failures))
    if primary_failure is None and errors["run"]:
        first_run_error = errors["run"][0]
        primary_failure = RuntimeError(
            f"{first_run_error.get('stage')}: {first_run_error.get('message')}"
        )
    if primary_failure is not None:
        error_logger(format_failure_report(timestamp, trigger_source, primary_failure))

    outcome = {
        "ok": error_count == 0 and not delivery_failures and run_report_delivery_error is None,
        "updateCount": update_count,
        "notifiedUpdateCount": notified_update_count,
        "suppressedUpdateCount": suppressed_update_count,
        "errorCount": error_count,
        "outboxPendingCount": outbox_pending_count,
        "timestamp": timestamp,
        "triggerSource": trigger_source,
        "dailyNotificationSent": daily_notification_sent,
    }
    if primary_failure is not None:
        outcome["error"] = f"{primary_failure.__class__.__name__}: {primary_failure}"
    elif run_report_delivery_error is not None:
        outcome["error"] = f"{run_report_delivery_error.__class__.__name__}: {run_report_delivery_error}"
    return outcome


@dataclass
class RunCoordinator:
    config: RunnerConfig
    notifier: Optional[Notifier] = None
    named_notifiers: Optional[Mapping[str, Notifier]] = None
    discord_client: Optional[DiscordTransport] = None
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
            discord_client=self.discord_client,
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


def start_fetch_run(coordinator: RunCoordinator) -> Dict[str, object]:
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
    discord_client = (
        DiscordChannelClient(config.discord_outbound_config)
        if config.discord_outbound_config is not None
        else None
    )
    coordinator = RunCoordinator(
        config,
        named_notifiers=named_notifiers,
        discord_client=discord_client,
    )

    if config.discord_outbound_config is not None:
        from manga_watch.discord_inbound import (
            DiscordCommandListener,
            inbound_enabled_from_env,
            parse_poll_interval,
        )

        if inbound_enabled_from_env():
            try:
                listener = DiscordCommandListener(
                    client=DiscordChannelClient(config.discord_outbound_config),
                    channel_id=config.discord_outbound_config.main_channel_id,
                    coordinator=coordinator,
                    timezone_name=config.timezone_name,
                    watchlist_path=config.watchlist_path,
                    state_path=get_state_path(),
                    poll_interval_seconds=parse_poll_interval(
                        os.environ.get("DISCORD_COMMAND_POLL_INTERVAL")
                    ),
                    report_logger=report_to_stdout,
                    error_logger=report_to_stderr,
                )
                listener.start_background()
            except Exception as exc:
                report_to_stderr(f"[discord] command listener startup failed: {exc}")

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
