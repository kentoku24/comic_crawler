import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from manga_watch.firestore_storage import FirestoreStorageConfig, FirestoreStorageRepository
from manga_watch.migrate_storage import migrate_storage
from tests.test_firestore_storage import FakeFirestoreClient, make_state, make_watchlist


class MigrateStorageTests(unittest.TestCase):
    def test_migration_happy_path_copies_json_payloads_to_firestore_backend(self):
        repository = FirestoreStorageRepository(
            config=FirestoreStorageConfig(project="star-light-breaker"),
            client=FakeFirestoreClient(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            watchlist_path = tmpdir_path / "watchlist.json"
            state_path = tmpdir_path / "state.json"
            watchlist_path.write_text(json.dumps(make_watchlist(), ensure_ascii=False), encoding="utf-8")
            state_path.write_text(json.dumps(make_state(), ensure_ascii=False), encoding="utf-8")

            with mock.patch("manga_watch.storage.get_firestore_repository", return_value=repository):
                result = migrate_storage(
                    watchlist_json=str(watchlist_path),
                    state_json=str(state_path),
                )

        self.assertTrue(result["ok"])
        self.assertEqual(1, result["work_count"])
        self.assertIn("current", repository.client.store["watchlists"])
        self.assertIn("runtime", repository.client.store["states"])
