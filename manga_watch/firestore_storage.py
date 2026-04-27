from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Dict, Mapping, Optional, Protocol, Sequence

DEFAULT_FIRESTORE_DATABASE = "(default)"
DEFAULT_WATCHLIST_COLLECTION = "watchlists"
DEFAULT_WATCHLIST_DOCUMENT = "current"
DEFAULT_STATE_COLLECTION = "states"
DEFAULT_STATE_DOCUMENT = "runtime"
DEFAULT_SUPERTWINS_SEARCH_SESSIONS_COLLECTION = "supertwins_search_sessions"
DEFAULT_WHERE_SESSIONS_COLLECTION = "where_sessions"
DEFAULT_RUNS_COLLECTION = "runs"
DEFAULT_NOTIFICATION_DEDUPE_COLLECTION = "notification_dedupe"
DEFAULT_DELIVERY_BACKLOG_COLLECTION = "delivery_backlog"

_INVALID_DOC_ID_RE = re.compile(r"/")


class FirestoreSnapshot(Protocol):
    @property
    def exists(self) -> bool:
        ...

    @property
    def id(self) -> str:
        ...

    def to_dict(self) -> Optional[Mapping[str, object]]:
        ...


class FirestoreDocument(Protocol):
    def get(self) -> FirestoreSnapshot:
        ...

    def set(self, payload: Mapping[str, object]) -> None:
        ...

    def delete(self) -> None:
        ...


class FirestoreCollection(Protocol):
    def document(self, doc_id: str) -> FirestoreDocument:
        ...

    def stream(self) -> Sequence[FirestoreSnapshot]:
        ...


class FirestoreClient(Protocol):
    def collection(self, name: str) -> FirestoreCollection:
        ...


@dataclass(frozen=True)
class FirestoreStorageConfig:
    project: Optional[str] = None
    database: str = DEFAULT_FIRESTORE_DATABASE
    watchlist_collection: str = DEFAULT_WATCHLIST_COLLECTION
    watchlist_document: str = DEFAULT_WATCHLIST_DOCUMENT
    state_collection: str = DEFAULT_STATE_COLLECTION
    state_document: str = DEFAULT_STATE_DOCUMENT
    supertwins_search_sessions_collection: str = DEFAULT_SUPERTWINS_SEARCH_SESSIONS_COLLECTION
    where_sessions_collection: str = DEFAULT_WHERE_SESSIONS_COLLECTION
    runs_collection: str = DEFAULT_RUNS_COLLECTION
    notification_dedupe_collection: str = DEFAULT_NOTIFICATION_DEDUPE_COLLECTION
    delivery_backlog_collection: str = DEFAULT_DELIVERY_BACKLOG_COLLECTION

    @classmethod
    def from_env(
        cls,
        *,
        environ: Optional[Mapping[str, str]] = None,
    ) -> "FirestoreStorageConfig":
        env = os.environ if environ is None else environ
        return cls(
            project=(
                _normalize_optional_text(env.get("MANGA_WATCH_FIRESTORE_PROJECT"))
                or _normalize_optional_text(env.get("MANGA_WATCH_GCP_PROJECT"))
                or _normalize_optional_text(env.get("GOOGLE_CLOUD_PROJECT"))
                or _normalize_optional_text(env.get("GCLOUD_PROJECT"))
            ),
            database=_normalize_optional_text(env.get("MANGA_WATCH_FIRESTORE_DATABASE"))
            or DEFAULT_FIRESTORE_DATABASE,
            watchlist_collection=_normalize_optional_text(
                env.get("MANGA_WATCH_FIRESTORE_WATCHLIST_COLLECTION")
            )
            or DEFAULT_WATCHLIST_COLLECTION,
            watchlist_document=_normalize_optional_text(
                env.get("MANGA_WATCH_FIRESTORE_WATCHLIST_DOCUMENT")
            )
            or DEFAULT_WATCHLIST_DOCUMENT,
            state_collection=_normalize_optional_text(env.get("MANGA_WATCH_FIRESTORE_STATE_COLLECTION"))
            or DEFAULT_STATE_COLLECTION,
            state_document=_normalize_optional_text(env.get("MANGA_WATCH_FIRESTORE_STATE_DOCUMENT"))
            or DEFAULT_STATE_DOCUMENT,
            supertwins_search_sessions_collection=_normalize_optional_text(
                env.get("MANGA_WATCH_FIRESTORE_SUPERTWINS_SEARCH_SESSIONS_COLLECTION")
            )
            or DEFAULT_SUPERTWINS_SEARCH_SESSIONS_COLLECTION,
            where_sessions_collection=_normalize_optional_text(
                env.get("MANGA_WATCH_FIRESTORE_WHERE_SESSIONS_COLLECTION")
            )
            or DEFAULT_WHERE_SESSIONS_COLLECTION,
            runs_collection=_normalize_optional_text(env.get("MANGA_WATCH_FIRESTORE_RUNS_COLLECTION"))
            or DEFAULT_RUNS_COLLECTION,
            notification_dedupe_collection=_normalize_optional_text(
                env.get("MANGA_WATCH_FIRESTORE_NOTIFICATION_DEDUPE_COLLECTION")
            )
            or DEFAULT_NOTIFICATION_DEDUPE_COLLECTION,
            delivery_backlog_collection=_normalize_optional_text(
                env.get("MANGA_WATCH_FIRESTORE_DELIVERY_BACKLOG_COLLECTION")
            )
            or DEFAULT_DELIVERY_BACKLOG_COLLECTION,
        )


class FirestoreStorageRepository:
    def __init__(
        self,
        *,
        config: FirestoreStorageConfig,
        client: Optional[FirestoreClient] = None,
        run_id_factory: Optional[Callable[[Mapping[str, object]], str]] = None,
    ) -> None:
        self.config = config
        self.client = client or build_google_firestore_client(config)
        self.run_id_factory = run_id_factory or build_run_record_id

    def load_watchlist(self) -> Dict[str, object]:
        return self._load_document(
            self.config.watchlist_collection,
            self.config.watchlist_document,
        )

    def save_watchlist(self, watchlist: Mapping[str, object]) -> None:
        self._save_document(
            self.config.watchlist_collection,
            self.config.watchlist_document,
            watchlist,
        )

    def load_state(self) -> Dict[str, object]:
        snapshot = self.client.collection(self.config.state_collection).document(
            self.config.state_document
        ).get()
        if not snapshot.exists:
            from manga_watch.storage import default_state

            return default_state()
        payload = snapshot.to_dict() or {}
        return dict(payload)

    def save_state(self, state: Mapping[str, object]) -> None:
        self._save_document(
            self.config.state_collection,
            self.config.state_document,
            state,
        )
        self._sync_named_documents(
            self.config.notification_dedupe_collection,
            build_notification_dedupe_documents(
                state,
                state_document_id=self.config.state_document,
            ),
            state_document_id=self.config.state_document,
        )
        self._sync_named_documents(
            self.config.delivery_backlog_collection,
            build_delivery_backlog_documents(
                state,
                state_document_id=self.config.state_document,
            ),
            state_document_id=self.config.state_document,
        )

    def load_supertwins_search_session(self, token: str) -> Dict[str, object]:
        snapshot = self.client.collection(self.config.supertwins_search_sessions_collection).document(
            build_shadow_document_id(self.config.state_document, token)
        ).get()
        if not snapshot.exists:
            raise FileNotFoundError(
                f"missing Firestore document: {self.config.supertwins_search_sessions_collection}/{token}"
            )
        payload = snapshot.to_dict() or {}
        return dict(payload)

    def save_supertwins_search_session(self, token: str, payload: Mapping[str, object]) -> None:
        normalized_payload = dict(payload)
        normalized_payload["state_document_id"] = self.config.state_document
        self._save_document(
            self.config.supertwins_search_sessions_collection,
            build_shadow_document_id(self.config.state_document, token),
            normalized_payload,
        )

    def delete_supertwins_search_session(self, token: str) -> None:
        self.client.collection(self.config.supertwins_search_sessions_collection).document(
            build_shadow_document_id(self.config.state_document, token)
        ).delete()

    def load_where_session(self, token: str) -> Dict[str, object]:
        snapshot = self.client.collection(self.config.where_sessions_collection).document(
            build_shadow_document_id(self.config.state_document, token)
        ).get()
        if not snapshot.exists:
            raise FileNotFoundError(
                f"missing Firestore document: {self.config.where_sessions_collection}/{token}"
            )
        payload = snapshot.to_dict() or {}
        return dict(payload)

    def save_where_session(self, token: str, payload: Mapping[str, object]) -> None:
        normalized_payload = dict(payload)
        normalized_payload["state_document_id"] = self.config.state_document
        self._save_document(
            self.config.where_sessions_collection,
            build_shadow_document_id(self.config.state_document, token),
            normalized_payload,
        )

    def delete_where_session(self, token: str) -> None:
        self.client.collection(self.config.where_sessions_collection).document(
            build_shadow_document_id(self.config.state_document, token)
        ).delete()

    def record_run_summary(self, summary: Mapping[str, object]) -> str:
        run_record = dict(summary)
        run_id = str(run_record.get("runId") or run_record.get("run_id") or self.run_id_factory(summary))
        run_record["runId"] = run_id
        self._save_document(
            self.config.runs_collection,
            run_id,
            run_record,
        )
        return run_id

    def save_run_summary(self, summary: Mapping[str, object]) -> str:
        return self.record_run_summary(summary)

    def list_run_summaries(self, *, limit: int = 20) -> list[Dict[str, object]]:
        summaries = []
        for snapshot in self.client.collection(self.config.runs_collection).stream():
            payload = snapshot.to_dict() or {}
            if not isinstance(payload, Mapping):
                continue
            summaries.append(dict(payload))
        summaries.sort(
            key=lambda item: (
                str(item.get("timestamp") or ""),
                str(item.get("runId") or item.get("run_id") or ""),
            ),
            reverse=True,
        )
        return summaries[: max(0, int(limit))]

    def _load_document(self, collection_name: str, doc_id: str) -> Dict[str, object]:
        snapshot = self.client.collection(collection_name).document(doc_id).get()
        if not snapshot.exists:
            raise FileNotFoundError(f"missing Firestore document: {collection_name}/{doc_id}")
        payload = snapshot.to_dict() or {}
        return dict(payload)

    def _save_document(
        self,
        collection_name: str,
        doc_id: str,
        payload: Mapping[str, object],
    ) -> None:
        self.client.collection(collection_name).document(doc_id).set(dict(payload))

    def _sync_named_documents(
        self,
        collection_name: str,
        docs_by_id: Mapping[str, Mapping[str, object]],
        *,
        state_document_id: str,
    ) -> None:
        collection = self.client.collection(collection_name)
        existing_ids = set()
        for snapshot in collection.stream():
            payload = snapshot.to_dict() or {}
            if not isinstance(payload, Mapping):
                continue
            if payload.get("state_document_id") == state_document_id:
                existing_ids.add(snapshot.id)
        for doc_id, payload in docs_by_id.items():
            collection.document(doc_id).set(dict(payload))
        for stale_id in existing_ids - set(docs_by_id.keys()):
            collection.document(stale_id).delete()


@lru_cache(maxsize=4)
def _cached_google_firestore_client(
    project: Optional[str],
    database: str,
):
    from google.cloud import firestore

    return firestore.Client(project=project, database=database)


def build_google_firestore_client(config: FirestoreStorageConfig):
    return _cached_google_firestore_client(config.project, config.database)


def build_notification_dedupe_documents(
    state: Mapping[str, object],
    *,
    state_document_id: str,
) -> Dict[str, Dict[str, object]]:
    delivered_latest_keys = (
        (((state.get("discord_delivery") or {}).get("daily_notification") or {}).get("delivered_latest_keys"))
        or {}
    )
    if not isinstance(delivered_latest_keys, Mapping):
        return {}

    docs: Dict[str, Dict[str, object]] = {}
    for work_id, latest_keys in delivered_latest_keys.items():
        normalized_work_id = str(work_id).strip()
        if not normalized_work_id:
            continue
        if isinstance(latest_keys, Mapping):
            latest_key = str(latest_keys.get("latest_key") or "").strip()
            if not latest_key:
                continue
            docs[build_shadow_document_id(state_document_id, normalized_work_id)] = {
                "work_id": normalized_work_id,
                "latest_key": latest_key,
                "delivered_at": latest_keys.get("delivered_at"),
                "state_document_id": state_document_id,
            }
            continue
        latest_key = str(latest_keys).strip()
        if not latest_key:
            continue
        docs[build_shadow_document_id(state_document_id, normalized_work_id)] = {
            "work_id": normalized_work_id,
            "latest_key": latest_key,
            "delivered_at": None,
            "state_document_id": state_document_id,
        }
    return docs


def build_delivery_backlog_documents(
    state: Mapping[str, object],
    *,
    state_document_id: str,
) -> Dict[str, Dict[str, object]]:
    docs: Dict[str, Dict[str, object]] = {}

    notification_outbox = state.get("notification_outbox") or []
    if isinstance(notification_outbox, list):
        for entry in notification_outbox:
            if not isinstance(entry, Mapping):
                continue
            event = entry.get("event") or {}
            if not isinstance(event, Mapping):
                continue
            event_id = str(event.get("event_id") or "").strip()
            if not event_id:
                continue
            docs[build_shadow_document_id(state_document_id, f"notification_outbox:{event_id}")] = {
                "entry_type": "notification_outbox",
                "state_document_id": state_document_id,
                "event_id": event_id,
                "pending_backends": list(entry.get("pending_backends") or []),
                "attempt_count": int(entry.get("attempt_count") or 0),
                "last_attempted_at": entry.get("last_attempted_at"),
                "last_error": entry.get("last_error"),
                "event": dict(event),
            }

    pending_messages = (
        (((state.get("discord_delivery") or {}).get("daily_notification") or {}).get("pending_messages"))
        or []
    )
    if isinstance(pending_messages, list):
        for index, message in enumerate(pending_messages):
            if not isinstance(message, Mapping):
                continue
            channel_id = str(message.get("channel_id") or "").strip()
            content = str(message.get("content") or "").strip()
            message_keys = message.get("message_keys") or []
            created_at = str(message.get("created_at") or "").strip()
            stable_key = "|".join([channel_id, created_at, content, *[str(item) for item in message_keys]])
            digest = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:16]
            docs[build_shadow_document_id(state_document_id, f"discord_daily_notification:{digest}")] = {
                "entry_type": "discord_daily_notification",
                "state_document_id": state_document_id,
                "channel_id": channel_id,
                "content": content,
                "message_keys": list(message_keys) if isinstance(message_keys, list) else [],
                "created_at": message.get("created_at"),
                "attempt_count": int(message.get("attempt_count") or 0),
                "last_attempted_at": message.get("last_attempted_at"),
                "last_error": message.get("last_error"),
            }
    return docs


def build_run_record_id(summary: Mapping[str, object]) -> str:
    trigger_source = str(summary.get("triggerSource") or "run").strip() or "run"
    timestamp = str(summary.get("timestamp") or "unknown").strip() or "unknown"
    normalized_timestamp = re.sub(r"[^0-9A-Za-z]+", "-", timestamp).strip("-").lower() or "unknown"
    entropy = hashlib.sha256(
        f"{normalized_timestamp}|{trigger_source}|{time.time_ns()}".encode("utf-8")
    ).hexdigest()[:10]
    return sanitize_document_id(f"{normalized_timestamp}-{trigger_source}-{entropy}")


def sanitize_document_id(value: str) -> str:
    sanitized = _INVALID_DOC_ID_RE.sub("_", str(value).strip())
    return sanitized or "runtime"


def build_shadow_document_id(state_document_id: str, logical_id: str) -> str:
    return sanitize_document_id(f"{state_document_id}:{logical_id}")


def _normalize_optional_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class FirestoreRepository(FirestoreStorageRepository):
    def __init__(
        self,
        client: Optional[FirestoreClient] = None,
        *,
        project: Optional[str] = None,
        database: str = DEFAULT_FIRESTORE_DATABASE,
        watchlist_collection: str = DEFAULT_WATCHLIST_COLLECTION,
        watchlist_document_id: str = DEFAULT_WATCHLIST_DOCUMENT,
        state_collection: str = DEFAULT_STATE_COLLECTION,
        state_document_id: str = DEFAULT_STATE_DOCUMENT,
        where_sessions_collection: str = DEFAULT_WHERE_SESSIONS_COLLECTION,
        runs_collection: str = DEFAULT_RUNS_COLLECTION,
        notification_dedupe_collection: str = DEFAULT_NOTIFICATION_DEDUPE_COLLECTION,
        delivery_backlog_collection: str = DEFAULT_DELIVERY_BACKLOG_COLLECTION,
        run_id_factory: Optional[Callable[[Mapping[str, object]], str]] = None,
    ) -> None:
        super().__init__(
            config=FirestoreStorageConfig(
                project=project,
                database=database,
                watchlist_collection=watchlist_collection,
                watchlist_document=watchlist_document_id,
                state_collection=state_collection,
                state_document=state_document_id,
                where_sessions_collection=where_sessions_collection,
                runs_collection=runs_collection,
                notification_dedupe_collection=notification_dedupe_collection,
                delivery_backlog_collection=delivery_backlog_collection,
            ),
            client=client,
            run_id_factory=run_id_factory,
        )
