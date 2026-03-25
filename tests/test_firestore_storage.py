import json
import os
import unittest
from unittest import mock

from manga_watch.firestore_storage import FirestoreStorageConfig, FirestoreStorageRepository
from manga_watch.storage import (
    load_state,
    load_watchlist,
    record_run_summary,
    save_state,
    save_watchlist,
    validate_state,
)


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


class FirestoreStorageTests(unittest.TestCase):
    def make_repository(self):
        return FirestoreStorageRepository(
            config=FirestoreStorageConfig(project="star-light-breaker"),
            client=FakeFirestoreClient(),
        )

    def test_storage_backend_round_trips_watchlist_and_state_and_syncs_shadow_docs(self):
        repository = self.make_repository()
        watchlist = make_watchlist()
        state = make_state()
        expected_state = validate_state(state)

        with mock.patch("manga_watch.storage.get_firestore_repository", return_value=repository):
            save_watchlist(watchlist, backend="firestore")
            save_state(state, backend="firestore")

            self.assertEqual(watchlist, load_watchlist(backend="firestore"))
            self.assertEqual(expected_state, load_state(backend="firestore"))

        client = repository.client
        self.assertIn("current", client.store["watchlists"])
        self.assertIn("runtime", client.store["states"])
        self.assertEqual(
            {
                "work_id": "work-1",
                "latest_key": "episode-2",
                "delivered_at": None,
                "state_document_id": "runtime",
            },
            client.store["notification_dedupe"]["work-1"],
        )
        self.assertEqual(2, len(client.store["delivery_backlog"]))

    def test_record_run_summary_writes_runs_collection(self):
        repository = self.make_repository()

        with mock.patch("manga_watch.storage.get_firestore_repository", return_value=repository):
            run_id = record_run_summary(
                {
                    "ok": True,
                    "timestamp": "2026-03-25 10:00:00 JST",
                    "triggerSource": "scheduled",
                },
                backend="firestore",
            )

        self.assertIsNotNone(run_id)
        self.assertIn(run_id, repository.client.store["runs"])
        self.assertTrue(repository.client.store["runs"][run_id]["ok"])
        self.assertEqual(run_id, repository.client.store["runs"][run_id]["runId"])

    def test_env_selected_firestore_backend_is_used_without_explicit_backend_arg(self):
        repository = self.make_repository()
        watchlist = make_watchlist()

        with mock.patch.dict(os.environ, {"MANGA_WATCH_STORAGE_BACKEND": "firestore"}, clear=False):
            with mock.patch("manga_watch.storage.get_firestore_repository", return_value=repository):
                save_watchlist(watchlist)
                loaded = load_watchlist("/tmp/ignored-by-firestore.json")

        self.assertEqual("work-1", loaded["works"][0]["id"])
