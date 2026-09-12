"""Shared Firestore fakes for tests (test-only helper).

Moved verbatim from tests/test_firestore_storage.py (Todo 10 decoupling).
Import from here instead of tests.test_firestore_storage to avoid
test-to-test imports. stdlib-only; no imports from tests/* (no cycles).
"""

import json


def make_watchlist():
    return {
        "version": 2,
        "works": [
            {
                "id": "work-1",
                "source": "comic-walker",
                "seed_url": "https://comic-walker.com/detail/work-1",
                "enabled": True,
                "notification_policy": {
                    "mode": "all",
                    "allowed_update_types": None,
                },
            }
        ],
    }


def make_state():
    return {
        "version": 2,
        "works": {
            "work-1": {
                "latest": {
                    "series_title": "作品A",
                    "episode_title": "第2話",
                    "latest_key": "episode-2",
                    "url": "https://example.com/episodes/2",
                    "update_type": "main_story",
                    "default_notify": True,
                },
                "history": [
                    {
                        "event_id": "event-1",
                        "detected_at": "2023-11-14T22:13:20Z",
                        "latest": {
                            "series_title": "作品A",
                            "episode_title": "第2話",
                            "latest_key": "episode-2",
                        },
                    }
                ],
                "unread": {"event_ids": ["event-1"]},
            }
        },
        "last_run_at": 1_700_000_000,
        "notification_outbox": [
            {
                "event": {
                    "schema_version": 1,
                    "event_id": "event-1",
                    "work_id": "work-1",
                    "latest_key": "episode-2",
                    "series_title": "作品A",
                    "update_type": "main_story",
                    "detected_at": "2023-11-14T22:13:20Z",
                    "from": {"latest_key": "episode-1"},
                    "to": {"latest_key": "episode-2"},
                },
                "pending_backends": ["stdout", "webhook"],
                "attempt_count": 1,
                "last_attempted_at": "2023-11-14T22:15:00Z",
                "last_error": "webhook timeout",
            }
        ],
        "discord_delivery": {
            "daily_notification": {
                "delivered_latest_keys": {
                    "work-1": {
                        "latest_key": "episode-2",
                        "delivered_at": None,
                    },
                },
                "pending_messages": [
                    {
                        "channel_id": "main-channel",
                        "content": "pending daily message",
                        "message_keys": [
                            {
                                "work_id": "work-1",
                                "latest_key": "episode-2",
                            }
                        ],
                        "created_at": "2023-11-14T22:13:20Z",
                        "attempt_count": 0,
                        "last_attempted_at": None,
                        "last_error": None,
                    }
                ],
            }
        },
    }


class FakeSnapshot:
    def __init__(self, doc_id, payload):
        self.id = doc_id
        self._payload = None if payload is None else json.loads(json.dumps(payload, ensure_ascii=False))

    @property
    def exists(self):
        return self._payload is not None

    def to_dict(self):
        if self._payload is None:
            return None
        return json.loads(json.dumps(self._payload, ensure_ascii=False))


class FakeDocument:
    def __init__(self, store, collection_name, doc_id):
        self.store = store
        self.collection_name = collection_name
        self.doc_id = doc_id

    def get(self):
        return FakeSnapshot(self.doc_id, self.store.get(self.collection_name, {}).get(self.doc_id))

    def set(self, payload):
        self.store.setdefault(self.collection_name, {})[self.doc_id] = json.loads(
            json.dumps(payload, ensure_ascii=False)
        )

    def delete(self):
        self.store.setdefault(self.collection_name, {}).pop(self.doc_id, None)


class FakeCollection:
    def __init__(self, store, collection_name):
        self.store = store
        self.collection_name = collection_name

    def document(self, doc_id):
        return FakeDocument(self.store, self.collection_name, doc_id)

    def stream(self):
        docs = self.store.setdefault(self.collection_name, {})
        return [FakeSnapshot(doc_id, payload) for doc_id, payload in sorted(docs.items())]


class FakeFirestoreClient:
    def __init__(self):
        self.store = {}

    def collection(self, collection_name):
        return FakeCollection(self.store, collection_name)
