import os
import unittest
from unittest import mock

from manga_watch.firestore_storage import FirestoreStorageConfig, FirestoreStorageRepository
from manga_watch.storage import (
    delete_supertwins_search_session,
    delete_where_session,
    load_state,
    load_supertwins_search_session,
    load_where_session,
    load_watchlist,
    record_run_summary,
    save_state,
    save_supertwins_search_session,
    save_where_session,
    save_watchlist,
    validate_state,
    validate_watchlist,
)
from tests._firestore_fakes import FakeFirestoreClient, make_state, make_watchlist


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

            self.assertEqual(validate_watchlist(watchlist), load_watchlist(backend="firestore"))
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
            client.store["notification_dedupe"]["runtime:work-1"],
        )
        self.assertEqual(2, len(client.store["delivery_backlog"]))

    def test_shadow_docs_are_namespaced_by_state_document(self):
        client = FakeFirestoreClient()
        runtime_repository = FirestoreStorageRepository(
            config=FirestoreStorageConfig(project="star-light-breaker", state_document="runtime"),
            client=client,
        )
        preview_repository = FirestoreStorageRepository(
            config=FirestoreStorageConfig(project="star-light-breaker", state_document="preview"),
            client=client,
        )

        runtime_repository.save_state(make_state())
        preview_repository.save_state(make_state())

        self.assertIn("runtime:work-1", client.store["notification_dedupe"])
        self.assertIn("preview:work-1", client.store["notification_dedupe"])
        self.assertEqual(4, len(client.store["delivery_backlog"]))

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

    def test_firestore_backend_round_trips_search_sessions_by_token(self):
        session_cases = {
            "supertwins": {
                "save": save_supertwins_search_session,
                "load": load_supertwins_search_session,
                "delete": delete_supertwins_search_session,
                "payload_a": {"root_work_id": "root-1", "selected_urls_by_value": {"u:a": "https://example.com/a"}},
                "payload_b": {"root_work_id": "root-2", "selected_urls_by_value": {"u:b": "https://example.com/b"}},
                "collection": "supertwins_search_sessions",
                "field": "root_work_id",
            },
            "where": {
                "save": save_where_session,
                "load": load_where_session,
                "delete": delete_where_session,
                "payload_a": {"query": "作品A", "episode": "1話", "results": [{"source": "comic-walker"}]},
                "payload_b": {"query": "作品B", "episode": "2話", "results": [{"source": "nicovideo-manga"}]},
                "collection": "where_sessions",
                "field": "query",
            },
        }
        for session_kind, funcs in session_cases.items():
            with self.subTest(session_kind=session_kind):
                repository = self.make_repository()

                with mock.patch("manga_watch.storage.get_firestore_repository", return_value=repository):
                    funcs["save"]("session-a", funcs["payload_a"], backend="firestore")
                    funcs["save"]("session-b", funcs["payload_b"], backend="firestore")
                    session_a = funcs["load"]("session-a", backend="firestore")
                    session_b = funcs["load"]("session-b", backend="firestore")
                    funcs["delete"]("session-a", backend="firestore")

                self.assertEqual(funcs["payload_a"][funcs["field"]], session_a[funcs["field"]])
                self.assertEqual(funcs["payload_b"][funcs["field"]], session_b[funcs["field"]])
                self.assertIn("runtime:session-b", repository.client.store[funcs["collection"]])
                self.assertNotIn("runtime:session-a", repository.client.store[funcs["collection"]])
