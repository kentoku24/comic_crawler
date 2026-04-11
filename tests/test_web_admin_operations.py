from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from manga_watch.firestore_storage import FirestoreStorageConfig, FirestoreStorageRepository
from manga_watch.storage import save_state, save_watchlist
from web_admin.operations import commands, queries
from web_admin.operations.capabilities import machine_auth_policy_from_env


def make_watchlist() -> dict:
    return {
        "version": 2,
        "works": [
            {
                "id": "work-1",
                "source": "comic-walker",
                "seed_url": "https://comic-walker.com/detail/KC_123456_S",
                "enabled": True,
                "notification_policy": {"mode": "all", "allowed_update_types": None},
            }
        ],
    }


def make_state() -> dict:
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
                "history": [],
                "health": {
                    "last_checked_at": 1_700_000_000,
                    "last_success_at": 1_700_000_000,
                    "consecutive_failures": 0,
                },
                "unread": {"event_ids": []},
            }
        },
        "last_run_at": 1_700_000_000,
        "notification_outbox": [],
        "discord_delivery": {"daily_notification": {"delivered_latest_keys": {}, "pending_messages": []}},
    }


class FakeSnapshot:
    def __init__(self, doc_id, payload):
        self.id = doc_id
        self._payload = None if payload is None else json.loads(json.dumps(payload))

    @property
    def exists(self):
        return self._payload is not None

    def to_dict(self):
        if self._payload is None:
            return None
        return json.loads(json.dumps(self._payload))


class FakeDocument:
    def __init__(self, store, collection_name, doc_id):
        self.store = store
        self.collection_name = collection_name
        self.doc_id = doc_id

    def get(self):
        return FakeSnapshot(self.doc_id, self.store.get(self.collection_name, {}).get(self.doc_id))

    def set(self, payload):
        self.store.setdefault(self.collection_name, {})[self.doc_id] = json.loads(json.dumps(payload))

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


class OperationsTests(unittest.TestCase):
    def test_get_run_history_reports_unsupported_for_json_backend(self):
        history = queries.get_run_history(backend="json")
        self.assertFalse(history["supported"])
        self.assertEqual([], history["items"])

    def test_update_watchlist_work_command_toggles_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            watchlist_path = Path(tmp) / "watchlist.json"
            save_watchlist(make_watchlist(), path=str(watchlist_path))

            result = commands.update_watchlist_work_command(
                "work-1",
                enabled=False,
                watchlist_path=str(watchlist_path),
                backend="json",
            )

            self.assertEqual("updated", result["action"])
            loaded = queries.get_watchlist_data(watchlist_path=str(watchlist_path), backend="json")
            self.assertFalse(loaded["works"][0]["enabled"])

    def test_machine_auth_policy_reads_google_oidc_configuration(self):
        with mock.patch.dict(
            "os.environ",
            {
                "WEB_ADMIN_MACHINE_AUTH_MODE": "google_oidc",
                "WEB_ADMIN_MACHINE_AUTH_SERVICE_URL": "https://comic-crawler-web.run.app",
                "WEB_ADMIN_MACHINE_AUTH_PRINCIPALS": "svc@example.com, user@example.com",
            },
            clear=False,
        ):
            policy = machine_auth_policy_from_env()

        self.assertEqual("google_oidc", policy.mode)
        self.assertEqual("https://comic-crawler-web.run.app", policy.audience)
        self.assertEqual(["svc@example.com", "user@example.com"], policy.principals)

    def test_trigger_manual_run_command_uses_shared_run_coordinator(self):
        coordinator = mock.Mock()
        coordinator.start_background.return_value = {"accepted": True, "runId": "run-1"}

        result = commands.trigger_manual_run_command(coordinator=coordinator)

        self.assertEqual({"accepted": True, "runId": "run-1"}, result)
        coordinator.start_background.assert_called_once_with("web_admin")

    def test_get_run_history_reads_firestore_runs(self):
        repository = FirestoreStorageRepository(
            config=FirestoreStorageConfig(project="demo-project"),
            client=FakeFirestoreClient(),
        )
        with mock.patch("manga_watch.storage.get_firestore_repository", return_value=repository):
            save_watchlist(make_watchlist(), backend="firestore")
            save_state(make_state(), backend="firestore")
            repository.record_run_summary({"runId": "run-1", "timestamp": "2026-04-11 10:00:00 JST", "ok": True})
            repository.record_run_summary({"runId": "run-2", "timestamp": "2026-04-11 11:00:00 JST", "ok": False})

            history = queries.get_run_history(backend="firestore")

        self.assertTrue(history["supported"])
        self.assertEqual(["run-2", "run-1"], [item["runId"] for item in history["items"]])
