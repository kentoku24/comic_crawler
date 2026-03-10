import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Mapping, Optional, Protocol, Sequence, TextIO, Tuple

import requests

from manga_watch.secret_redaction import redact_secret_text

DEFAULT_WEBHOOK_TIMEOUT = 10
SUPPORTED_NOTIFIER_BACKENDS = {"stdout", "webhook"}


def _coerce_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _snapshot_latest_key(snapshot: Mapping[str, object]) -> Optional[str]:
    return _coerce_text(
        snapshot.get("latest_key")
        or snapshot.get("latestKey")
        or snapshot.get("episode_code")
        or snapshot.get("episodeCode")
        or snapshot.get("url")
    )


def normalize_update_snapshot(snapshot: object) -> Dict[str, object]:
    if not isinstance(snapshot, Mapping):
        return {}

    normalized: Dict[str, object] = {}

    source = _coerce_text(snapshot.get("source"))
    if source:
        normalized["source"] = source

    latest_key = _snapshot_latest_key(snapshot)
    if latest_key:
        normalized["latest_key"] = latest_key

    series_title = _coerce_text(
        snapshot.get("series_title") or snapshot.get("seriesTitle") or snapshot.get("series")
    )
    if series_title:
        normalized["series_title"] = series_title

    episode_title = _coerce_text(snapshot.get("episode_title") or snapshot.get("episodeTitle"))
    if episode_title:
        normalized["episode_title"] = episode_title

    episode_code = _coerce_text(snapshot.get("episode_code") or snapshot.get("episodeCode"))
    if episode_code:
        normalized["episode_code"] = episode_code

    url = _coerce_text(snapshot.get("url"))
    if url:
        normalized["url"] = url

    update_type = _coerce_text(snapshot.get("update_type"))
    if update_type:
        normalized["update_type"] = update_type

    classification_reason = _coerce_text(snapshot.get("classification_reason"))
    if classification_reason:
        normalized["classification_reason"] = classification_reason

    if "default_notify" in snapshot and snapshot.get("default_notify") is not None:
        normalized["default_notify"] = bool(snapshot.get("default_notify"))

    return normalized


def normalize_notification_metadata(notification: object) -> Dict[str, object]:
    if not isinstance(notification, Mapping):
        return {}

    normalized: Dict[str, object] = {}

    mode = _coerce_text(notification.get("mode"))
    if mode:
        normalized["mode"] = mode

    if "allowed_update_types" in notification:
        allowed_update_types = notification.get("allowed_update_types")
        if allowed_update_types is None:
            normalized["allowed_update_types"] = None
        elif isinstance(allowed_update_types, list):
            normalized_allowed_update_types = []
            seen_update_types = set()
            for item in allowed_update_types:
                normalized_update_type = _coerce_text(item)
                if not normalized_update_type or normalized_update_type in seen_update_types:
                    continue
                seen_update_types.add(normalized_update_type)
                normalized_allowed_update_types.append(normalized_update_type)
            normalized["allowed_update_types"] = normalized_allowed_update_types

    if "should_notify" in notification and notification.get("should_notify") is not None:
        normalized["should_notify"] = bool(notification.get("should_notify"))

    applied_via = _coerce_text(notification.get("applied_via"))
    if applied_via:
        normalized["applied_via"] = applied_via

    reason = _coerce_text(notification.get("reason"))
    if reason:
        normalized["reason"] = reason

    return normalized


def derive_event_id(work_id: str, latest_key: str) -> str:
    digest = hashlib.sha256(f"{work_id}\n{latest_key}".encode("utf-8")).hexdigest()
    return f"{work_id}:{digest}"


def detected_at_for_timestamp(unix_ts: float) -> str:
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class UpdateEvent:
    event_id: str
    work_id: str
    latest_key: str
    series_title: str
    update_type: str
    detected_at: str
    before: Dict[str, object]
    after: Dict[str, object]
    notification: Dict[str, object]

    def as_payload(self) -> Dict[str, object]:
        payload = {
            "schema_version": 1,
            "event_id": self.event_id,
            "work_id": self.work_id,
            "latest_key": self.latest_key,
            "series_title": self.series_title,
            "update_type": self.update_type,
            "detected_at": self.detected_at,
            "from": dict(self.before),
            "to": dict(self.after),
        }
        if self.notification:
            payload["notification"] = dict(self.notification)
        return payload


def build_update_event(update: Mapping[str, object], *, detected_at: str) -> UpdateEvent:
    work_id = _coerce_text(update.get("work_id") or update.get("id"))
    if not work_id:
        raise ValueError("update event is missing work_id")

    before = normalize_update_snapshot(update.get("from") or {})
    after = normalize_update_snapshot(update.get("to") or {})

    latest_key = _coerce_text(after.get("latest_key"))
    if not latest_key:
        raise ValueError(f"update event {work_id} is missing latest_key")

    series_title = _coerce_text(after.get("series_title") or before.get("series_title")) or work_id
    update_type = _coerce_text(update.get("update_type") or after.get("update_type")) or "unknown"
    notification = normalize_notification_metadata(update.get("notification"))

    return UpdateEvent(
        event_id=derive_event_id(work_id, latest_key),
        work_id=work_id,
        latest_key=latest_key,
        series_title=series_title,
        update_type=update_type,
        detected_at=detected_at,
        before=before,
        after=after,
        notification=notification,
    )


def event_from_payload(payload: Mapping[str, object]) -> UpdateEvent:
    if not isinstance(payload, Mapping):
        raise ValueError("notification event payload must be an object")

    work_id = _coerce_text(payload.get("work_id"))
    latest_key = _coerce_text(payload.get("latest_key"))
    detected_at = _coerce_text(payload.get("detected_at"))
    if not work_id:
        raise ValueError("notification event payload is missing work_id")
    if not latest_key:
        raise ValueError("notification event payload is missing latest_key")
    if not detected_at:
        raise ValueError("notification event payload is missing detected_at")

    before = normalize_update_snapshot(payload.get("from"))
    after = normalize_update_snapshot(payload.get("to"))
    series_title = _coerce_text(payload.get("series_title")) or work_id
    update_type = _coerce_text(payload.get("update_type")) or "unknown"
    notification = normalize_notification_metadata(payload.get("notification"))

    return UpdateEvent(
        event_id=_coerce_text(payload.get("event_id")) or derive_event_id(work_id, latest_key),
        work_id=work_id,
        latest_key=latest_key,
        series_title=series_title,
        update_type=update_type,
        detected_at=detected_at,
        before=before,
        after=after,
        notification=notification,
    )


class Notifier(Protocol):
    def send(self, event: UpdateEvent) -> None:
        ...


@dataclass(frozen=True)
class NotifierConfig:
    backends: Tuple[str, ...]
    webhook_url: Optional[str] = None
    webhook_timeout: int = DEFAULT_WEBHOOK_TIMEOUT

    @classmethod
    def from_env(cls) -> "NotifierConfig":
        raw_backends = _coerce_text(os.environ.get("MANGA_WATCH_NOTIFIER_BACKENDS"))
        if not raw_backends:
            raise ValueError("MANGA_WATCH_NOTIFIER_BACKENDS is required")

        backends: List[str] = []
        for backend in raw_backends.split(","):
            normalized = backend.strip().lower()
            if not normalized or normalized in backends:
                continue
            backends.append(normalized)

        if not backends:
            raise ValueError("MANGA_WATCH_NOTIFIER_BACKENDS must include at least one backend")

        invalid = [backend for backend in backends if backend not in SUPPORTED_NOTIFIER_BACKENDS]
        if invalid:
            supported = ", ".join(sorted(SUPPORTED_NOTIFIER_BACKENDS))
            raise ValueError(
                f"MANGA_WATCH_NOTIFIER_BACKENDS contains unsupported backends: {', '.join(invalid)}; "
                f"supported: {supported}"
            )

        webhook_timeout = int(
            os.environ.get("MANGA_WATCH_WEBHOOK_TIMEOUT", str(DEFAULT_WEBHOOK_TIMEOUT))
        )
        if webhook_timeout <= 0:
            raise ValueError("MANGA_WATCH_WEBHOOK_TIMEOUT must be a positive integer (seconds)")

        webhook_url = _coerce_text(os.environ.get("MANGA_WATCH_WEBHOOK_URL"))
        if "webhook" in backends and not webhook_url:
            raise ValueError(
                "MANGA_WATCH_WEBHOOK_URL is required when MANGA_WATCH_NOTIFIER_BACKENDS includes webhook"
            )

        return cls(
            backends=tuple(backends),
            webhook_url=webhook_url,
            webhook_timeout=webhook_timeout,
        )


class StdoutNotifier:
    def __init__(self, stream: Optional[TextIO] = None):
        self.stream = stream or sys.stdout

    def send(self, event: UpdateEvent) -> None:
        self.stream.write(json.dumps(event.as_payload(), ensure_ascii=False) + "\n")
        self.stream.flush()


class WebhookNotifier:
    def __init__(
        self,
        webhook_url: str,
        *,
        timeout: int = DEFAULT_WEBHOOK_TIMEOUT,
        session: Optional[requests.Session] = None,
    ):
        self.webhook_url = webhook_url
        self.timeout = timeout
        self.session = session or requests.Session()

    def send(self, event: UpdateEvent) -> None:
        try:
            response = self.session.post(
                self.webhook_url,
                json=event.as_payload(),
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Webhook delivery failed: {redact_secret_text(exc, secrets=(self.webhook_url,))}"
            ) from exc

        if 200 <= response.status_code < 300:
            return

        detail = redact_secret_text(
            response.text.strip().replace("\n", " "),
            secrets=(self.webhook_url,),
        )
        raise RuntimeError(f"Webhook returned HTTP {response.status_code}: {detail[:300]}")


class FanoutNotifier:
    def __init__(self, notifiers: Sequence[tuple[str, Notifier]]):
        self.notifiers = list(notifiers)

    def send(self, event: UpdateEvent) -> None:
        failures = []
        for backend_name, notifier in self.notifiers:
            try:
                notifier.send(event)
            except Exception as exc:
                failures.append(f"{backend_name}: {exc}")

        if failures:
            raise RuntimeError("notification backends failed: " + "; ".join(failures))


def build_named_notifiers(
    config: NotifierConfig,
    *,
    stream: Optional[TextIO] = None,
    session: Optional[requests.Session] = None,
) -> Dict[str, Notifier]:
    notifiers: Dict[str, Notifier] = {}
    for backend in config.backends:
        if backend == "stdout":
            notifiers["stdout"] = StdoutNotifier(stream=stream)
            continue
        if backend == "webhook":
            notifiers["webhook"] = WebhookNotifier(
                config.webhook_url or "",
                timeout=config.webhook_timeout,
                session=session,
            )
            continue
        supported = ", ".join(sorted(SUPPORTED_NOTIFIER_BACKENDS))
        raise ValueError(f"unsupported notifier backend: {backend}; supported: {supported}")
    return notifiers


def build_notifier(
    config: NotifierConfig,
    *,
    stream: Optional[TextIO] = None,
    session: Optional[requests.Session] = None,
) -> Notifier:
    named_notifiers = build_named_notifiers(
        config,
        stream=stream,
        session=session,
    )
    notifiers = list(named_notifiers.items())

    if len(notifiers) == 1:
        return notifiers[0][1]
    return FanoutNotifier(notifiers)
