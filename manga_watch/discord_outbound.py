from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from manga_watch.secret_redaction import redact_secret_text
from manga_watch.secret_resolver import resolve_env_value
from manga_watch.storage import state_daily_notification_delivery
from manga_watch.discord_text import (
    episode_label_for_snapshot,
    series_label_for_snapshot,
    truncate_episode_label,
)

DEFAULT_DISCORD_API_BASE_URL = "https://discord.com/api/v10"
DEFAULT_DISCORD_TIMEOUT = 10
DEFAULT_TIMEZONE = "Asia/Tokyo"
DISCORD_DELIVERY_STATE_KEY = "discord_delivery"
DAILY_NOTIFICATION_STATE_KEY = "daily_notification"
RUN_REPORT_FAILURE_HEADLINE = "run report 自体の送信に失敗しました"


def _coerce_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def validated_timezone_name(timezone_name: str) -> str:
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown TZ value: {timezone_name}") from exc
    return timezone_name


class DiscordTransport(Protocol):
    def send_message(self, channel_id: str, content: str) -> None:
        ...


@dataclass(frozen=True)
class DiscordOutboundConfig:
    bot_token: str
    main_channel_id: str
    run_report_channel_id: str
    api_base_url: str = DEFAULT_DISCORD_API_BASE_URL
    timeout: int = DEFAULT_DISCORD_TIMEOUT

    @classmethod
    def from_env(
        cls,
        *,
        secret_resolver: Callable[[str], Optional[str]] = resolve_env_value,
    ) -> "DiscordOutboundConfig":
        bot_token = secret_resolver("DISCORD_BOT_TOKEN")
        if not bot_token:
            raise ValueError("DISCORD_BOT_TOKEN or DISCORD_BOT_TOKEN_SECRET_VERSION is required")

        main_channel_id = _coerce_text(os.environ.get("DISCORD_MAIN_CHANNEL_ID"))
        if not main_channel_id:
            raise ValueError("DISCORD_MAIN_CHANNEL_ID is required")

        run_report_channel_id = _coerce_text(os.environ.get("DISCORD_RUN_REPORT_CHANNEL_ID"))
        if not run_report_channel_id:
            raise ValueError("DISCORD_RUN_REPORT_CHANNEL_ID is required")

        return cls(
            bot_token=bot_token,
            main_channel_id=main_channel_id,
            run_report_channel_id=run_report_channel_id,
        )


class DiscordChannelClient:
    def __init__(
        self,
        config: DiscordOutboundConfig,
        *,
        session: Optional[requests.Session] = None,
    ):
        self.config = config
        self.session = session or requests.Session()

    def send_message(self, channel_id: str, content: str) -> None:
        normalized_channel_id = _coerce_text(channel_id)
        if not normalized_channel_id:
            raise RuntimeError("Discord channel_id is required")

        try:
            response = self.session.post(
                f"{self.config.api_base_url}/channels/{normalized_channel_id}/messages",
                json={
                    "content": str(content),
                    "allowed_mentions": {"parse": []},
                },
                headers={
                    "Authorization": f"Bot {self.config.bot_token}",
                    "Content-Type": "application/json",
                },
                timeout=self.config.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Discord delivery failed: {redact_secret_text(exc, secrets=(self.config.bot_token,))}"
            ) from exc

        if 200 <= response.status_code < 300:
            return

        detail = redact_secret_text(
            response.text.strip().replace("\n", " "),
            secrets=(self.config.bot_token,),
        )
        raise RuntimeError(f"Discord returned HTTP {response.status_code}: {detail[:300]}")

    def get_current_user_id(self) -> str:
        try:
            response = self.session.get(
                f"{self.config.api_base_url}/users/@me",
                headers={
                    "Authorization": f"Bot {self.config.bot_token}",
                },
                timeout=self.config.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                "Discord current-user lookup failed: "
                f"{redact_secret_text(exc, secrets=(self.config.bot_token,))}"
            ) from exc

        if 200 <= response.status_code < 300:
            payload = response.json()
            user_id = _coerce_text(payload.get("id") if isinstance(payload, Mapping) else None)
            if user_id:
                return user_id
            raise RuntimeError("Discord current-user lookup returned no id")

        detail = redact_secret_text(
            response.text.strip().replace("\n", " "),
            secrets=(self.config.bot_token,),
        )
        raise RuntimeError(f"Discord returned HTTP {response.status_code}: {detail[:300]}")

    def list_channel_messages(
        self,
        channel_id: str,
        *,
        after: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, object]]:
        normalized_channel_id = _coerce_text(channel_id)
        if not normalized_channel_id:
            raise RuntimeError("Discord channel_id is required")

        params: Dict[str, object] = {"limit": max(1, min(int(limit), 100))}
        normalized_after = _coerce_text(after)
        if normalized_after:
            params["after"] = normalized_after

        try:
            response = self.session.get(
                f"{self.config.api_base_url}/channels/{normalized_channel_id}/messages",
                params=params,
                headers={
                    "Authorization": f"Bot {self.config.bot_token}",
                },
                timeout=self.config.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Discord channel read failed: {redact_secret_text(exc, secrets=(self.config.bot_token,))}"
            ) from exc

        if 200 <= response.status_code < 300:
            payload = response.json()
            if not isinstance(payload, list):
                raise RuntimeError("Discord channel read returned an invalid payload")
            return [dict(message) for message in payload if isinstance(message, Mapping)]

        detail = redact_secret_text(
            response.text.strip().replace("\n", " "),
            secrets=(self.config.bot_token,),
        )
        raise RuntimeError(f"Discord returned HTTP {response.status_code}: {detail[:300]}")


def _daily_notification_state(state: Dict[str, object]) -> Dict[str, object]:
    return state_daily_notification_delivery(state)


def daily_notification_key(update: Mapping[str, object]) -> Optional[Tuple[str, str]]:
    work_id = _coerce_text(update.get("id") or update.get("work_id"))
    latest = update.get("to", {}) or {}
    if not isinstance(latest, Mapping):
        latest = {}
    latest_key = _coerce_text(latest.get("latest_key") or latest.get("latestKey"))
    if not work_id or not latest_key:
        return None
    return work_id, latest_key


def _pending_daily_notification_keys(state: Mapping[str, object]) -> set[Tuple[str, str]]:
    if not isinstance(state, dict):
        return set()
    pending_messages = _daily_notification_state(state).get("pending_messages", [])

    keys: set[Tuple[str, str]] = set()
    for entry in pending_messages:
        message_keys = entry.get("message_keys", [])
        for message_key in message_keys:
            work_id = _coerce_text(message_key.get("work_id"))
            latest_key = _coerce_text(message_key.get("latest_key"))
            if work_id and latest_key:
                keys.add((work_id, latest_key))
    return keys


def pending_daily_notification_count(state: Mapping[str, object]) -> int:
    if not isinstance(state, dict):
        return 0
    return len(_daily_notification_state(state).get("pending_messages", []))


def _delivered_latest_keys(state: Mapping[str, object]) -> Dict[str, str]:
    if not isinstance(state, dict):
        return {}
    delivered = _daily_notification_state(state).get("delivered_latest_keys", {})

    normalized: Dict[str, str] = {}
    for work_id, entry in delivered.items():
        latest_key = _coerce_text(entry.get("latest_key")) if isinstance(entry, Mapping) else _coerce_text(entry)
        if latest_key:
            normalized[str(work_id)] = latest_key
    return normalized


def format_daily_notification_line(update: Mapping[str, object]) -> str:
    work_id = str(update.get("id") or update.get("work_id") or "")
    before = update.get("from", {}) or {}
    if not isinstance(before, Mapping):
        before = {}
    after = update.get("to", {}) or {}
    if not isinstance(after, Mapping):
        after = {}

    series = series_label_for_snapshot(work_id, after)
    latest_label = truncate_episode_label(episode_label_for_snapshot(after, fallback="未取得"))
    previous_label = truncate_episode_label(episode_label_for_snapshot(before, fallback="未取得"))
    rendered_url = _coerce_text(after.get("url"))
    text = f"{series}：{latest_label}"
    if rendered_url:
        text = f"[{text}](<{rendered_url}>)"
    return f"{text}←{previous_label}"


def build_daily_notification_message(
    updates: Sequence[Mapping[str, object]],
    *,
    now_ts: float,
    timezone_name: str,
) -> str:
    local_date = datetime.fromtimestamp(
        now_ts,
        tz=ZoneInfo(validated_timezone_name(timezone_name or DEFAULT_TIMEZONE)),
    ).strftime("%Y-%m-%d")
    lines = [f"新着エピソードを検知しました（{local_date}）"]
    lines.extend(format_daily_notification_line(update) for update in updates)
    return "\n".join(lines)


def enqueue_daily_notification(
    state: Dict[str, object],
    *,
    updates: Sequence[Mapping[str, object]],
    channel_id: str,
    now_ts: float,
    timezone_name: str,
    created_at: str,
) -> Dict[str, object]:
    delivered = _delivered_latest_keys(state)
    pending_keys = _pending_daily_notification_keys(state)
    queued_updates: List[Mapping[str, object]] = []
    message_keys: List[Dict[str, str]] = []

    for update in updates:
        message_key = daily_notification_key(update)
        if message_key is None:
            continue
        work_id, latest_key = message_key
        if delivered.get(work_id) == latest_key or message_key in pending_keys:
            continue
        queued_updates.append(update)
        message_keys.append({"work_id": work_id, "latest_key": latest_key})

    if not queued_updates:
        return {
            "queued": False,
            "candidateUpdateCount": 0,
        }

    daily_notification = _daily_notification_state(state)
    pending_messages = daily_notification.setdefault("pending_messages", [])
    if not isinstance(pending_messages, list):
        pending_messages = []
        daily_notification["pending_messages"] = pending_messages
    pending_messages.append(
        {
            "channel_id": channel_id,
            "content": build_daily_notification_message(
                queued_updates,
                now_ts=now_ts,
                timezone_name=timezone_name,
            ),
            "message_keys": message_keys,
            "created_at": created_at,
            "attempt_count": 0,
            "last_attempted_at": None,
            "last_error": None,
        }
    )
    return {
        "queued": True,
        "candidateUpdateCount": len(queued_updates),
    }


def deliver_daily_notifications(
    state: Dict[str, object],
    *,
    client: DiscordTransport,
    attempted_at: str,
    redaction_secrets: Sequence[object] = (),
) -> Dict[str, object]:
    daily_notification = _daily_notification_state(state)
    pending_messages = list(daily_notification.get("pending_messages", []) or [])
    delivered_latest_keys = daily_notification.setdefault("delivered_latest_keys", {})
    if not isinstance(delivered_latest_keys, dict):
        delivered_latest_keys = {}
        daily_notification["delivered_latest_keys"] = delivered_latest_keys

    delivered_count = 0
    errors: List[str] = []
    remaining_messages: List[Dict[str, object]] = []
    blocked = False

    for raw_entry in pending_messages:
        entry = dict(raw_entry)
        if blocked:
            remaining_messages.append(entry)
            continue
        try:
            client.send_message(str(entry.get("channel_id") or ""), str(entry.get("content") or ""))
            delivered_count += 1
            for message_key in entry.get("message_keys", []):
                if not isinstance(message_key, Mapping):
                    continue
                work_id = _coerce_text(message_key.get("work_id"))
                latest_key = _coerce_text(message_key.get("latest_key"))
                if work_id and latest_key:
                    delivered_latest_keys[work_id] = {
                        "latest_key": latest_key,
                        "delivered_at": attempted_at,
                    }
        except Exception as exc:
            blocked = True
            entry["attempt_count"] = int(entry.get("attempt_count", 0) or 0) + 1
            entry["last_attempted_at"] = attempted_at
            entry["last_error"] = redact_secret_text(exc, secrets=redaction_secrets)
            remaining_messages.append(entry)
            errors.append(
                "daily_notification: "
                f"{redact_secret_text(exc, secrets=redaction_secrets)}"
            )

    daily_notification["pending_messages"] = remaining_messages
    return {
        "attemptedCount": len(pending_messages),
        "deliveredCount": delivered_count,
        "remainingCount": len(remaining_messages),
        "errors": errors,
    }


def _format_checker_error_lines(errors: Mapping[str, Sequence[Mapping[str, object]]]) -> List[str]:
    lines: List[str] = []

    for error in errors.get("sources", []):
        item = str(error.get("id") or error.get("url") or "unknown")
        phase = str(error.get("phase") or "unknown")
        kind = str(error.get("kind") or "runtime")
        message = str(error.get("message") or "unknown error")
        lines.append(f"- source/{kind} [{phase}] {item}: {message}")

    for error in errors.get("run", []):
        stage = str(error.get("stage") or "unknown")
        kind = str(error.get("kind") or "runtime")
        message = str(error.get("message") or "unknown error")
        lines.append(f"- run/{kind} [{stage}]: {message}")

    return lines


def build_run_report_message(
    *,
    timestamp: str,
    trigger_source: str,
    update_count: int,
    notified_update_count: int,
    suppressed_update_count: int,
    outbox_pending_count: int,
    daily_notification_sent: bool,
    daily_notification_pending_count: int,
    errors: Mapping[str, Sequence[Mapping[str, object]]],
    delivery_failures: Sequence[str],
    state_lines: Sequence[str],
    redaction_secrets: Sequence[object] = (),
) -> str:
    source_failures = len(errors.get("sources", []))
    run_failures = len(errors.get("run", []))
    delivery_failure_count = len(delivery_failures)
    if run_failures > 0 or delivery_failure_count > 0:
        headline = "巡回実行に失敗しました"
    elif source_failures > 0:
        headline = "巡回実行に一部失敗がありました"
    else:
        headline = "巡回実行しました"

    lines = [
        f"{headline} ({timestamp})",
        f"トリガー: {trigger_source}",
        f"更新検知: {update_count}件",
        f"通知対象: {notified_update_count}件",
        f"通知抑制: {suppressed_update_count}件",
        f"daily notification: {'送信した' if daily_notification_sent else '送信なし'}",
        f"generic notifier outbox残件: {outbox_pending_count}件",
        f"Discord daily pending: {daily_notification_pending_count}件",
        f"source failure: {source_failures}件",
        f"run-level failure: {run_failures}件",
        f"delivery failure: {delivery_failure_count}件",
    ]
    checker_error_lines = _format_checker_error_lines(errors)
    if redaction_secrets:
        checker_error_lines = [
            redact_secret_text(line, secrets=redaction_secrets) for line in checker_error_lines
        ]
    if checker_error_lines:
        lines.append("failure details:")
        lines.extend(checker_error_lines)
    if delivery_failures:
        if not checker_error_lines:
            lines.append("failure details:")
        lines.extend(
            f"- delivery: {redact_secret_text(failure, secrets=redaction_secrets)}"
            for failure in delivery_failures
        )
    lines.append("現在のリスト:")
    lines.extend(state_lines)
    return "\n".join(lines)


def format_run_report_delivery_failure(
    *,
    timestamp: str,
    trigger_source: str,
    exc: Exception,
    redaction_secrets: Sequence[object] = (),
) -> str:
    return "\n".join(
        [
            f"{RUN_REPORT_FAILURE_HEADLINE} ({timestamp})",
            f"トリガー: {trigger_source}",
            "エラー: "
            f"{exc.__class__.__name__}: {redact_secret_text(exc, secrets=redaction_secrets)}",
        ]
    )
