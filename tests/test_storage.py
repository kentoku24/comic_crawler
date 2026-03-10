import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from manga_watch.storage import load_state, save_state


def make_state(*, latest_key: str, last_run_at: int) -> dict:
    return {
        "version": 2,
        "works": {
            "work-1": {
                "latest": {
                    "series_title": "作品A",
                    "episode_title": latest_key,
                    "latest_key": latest_key,
                    "url": f"https://example.com/{latest_key}",
                },
                "history": [],
                "health": {
                    "last_checked_at": last_run_at,
                    "last_success_at": last_run_at,
                    "consecutive_failures": 0,
                },
                "unread": {
                    "event_ids": [latest_key],
                },
            }
        },
        "last_run_at": last_run_at,
        "notification_outbox": [],
        "discord_delivery": {
            "daily_notification": {
                "delivered_latest_keys": {},
                "pending_messages": [],
            }
        },
    }


class StorageTests(unittest.TestCase):
    def test_save_state_keeps_previous_json_when_write_fails_before_replace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            save_state(make_state(latest_key="episode-1", last_run_at=1), path=str(state_path))
            original = load_state(str(state_path))

            def interrupted_dump(payload, fp, **kwargs):
                fp.write('{"version": 2')
                fp.flush()
                raise RuntimeError("simulated crash")

            with mock.patch("manga_watch.storage.json.dump", side_effect=interrupted_dump):
                with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                    save_state(make_state(latest_key="episode-2", last_run_at=2), path=str(state_path))

            self.assertEqual(original, load_state(str(state_path)))
            self.assertEqual(original["last_run_at"], json.loads(state_path.read_text(encoding="utf-8"))["last_run_at"])
            self.assertEqual([], list(Path(tmpdir).glob("*.tmp")))

    def test_load_state_never_observes_partial_json_during_repeated_writes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            save_state(make_state(latest_key="episode-initial", last_run_at=0), path=str(state_path))

            stop_readers = threading.Event()
            observed = []
            reader_errors = []

            def reader():
                while not stop_readers.is_set():
                    try:
                        snapshot = load_state(str(state_path))
                        observed.append(snapshot["works"]["work-1"]["latest"]["latest_key"])
                    except Exception as exc:  # pragma: no cover - asserted via reader_errors
                        reader_errors.append(exc)
                        stop_readers.set()

            reader_threads = [threading.Thread(target=reader, daemon=True) for _ in range(3)]
            for thread in reader_threads:
                thread.start()

            try:
                for index in range(60):
                    save_state(
                        make_state(latest_key=f"episode-{index}", last_run_at=index),
                        path=str(state_path),
                    )
            finally:
                stop_readers.set()
                for thread in reader_threads:
                    thread.join(timeout=1)

            self.assertEqual([], reader_errors)
            self.assertIn("episode-initial", observed)
            self.assertIn(load_state(str(state_path))["works"]["work-1"]["latest"]["latest_key"], observed)

    def test_concurrent_writers_keep_state_parseable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            save_state(make_state(latest_key="episode-initial", last_run_at=0), path=str(state_path))
            written_keys = set()

            def writer(worker_id: int):
                latest_key = f"worker-{worker_id}"
                written_keys.add(latest_key)
                for attempt in range(25):
                    save_state(
                        make_state(
                            latest_key=latest_key,
                            last_run_at=worker_id * 100 + attempt,
                        ),
                        path=str(state_path),
                    )

            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(writer, worker_id) for worker_id in range(4)]
                for future in futures:
                    future.result()

            final_state = load_state(str(state_path))
            final_latest_key = final_state["works"]["work-1"]["latest"]["latest_key"]

            self.assertIn(final_latest_key, written_keys)
            self.assertEqual(final_latest_key, json.loads(state_path.read_text(encoding="utf-8"))["works"]["work-1"]["latest"]["latest_key"])


if __name__ == "__main__":
    unittest.main()
