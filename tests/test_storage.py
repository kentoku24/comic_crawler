import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from manga_watch.storage import (
    delete_supertwins_search_session,
    load_state,
    load_supertwins_search_session,
    save_state,
    save_supertwins_search_session,
    state_daily_notification_delivery,
    state_notification_outbox,
    validate_watchlist,
)


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
    def test_state_notification_outbox_normalizes_entries_in_place(self):
        state = {
            "notification_outbox": [
                {
                    "event": {"event_id": "event-1"},
                    "pendingBackends": ["stdout", "stdout", " webhook "],
                    "attemptCount": "2",
                    "lastAttemptedAt": "2023-11-14T22:13:20Z",
                    "lastError": "timed out",
                    "extraField": "kept",
                }
            ]
        }

        outbox = state_notification_outbox(state)

        self.assertEqual(
            [
                {
                    "event": {"event_id": "event-1"},
                    "pending_backends": ["stdout", "webhook"],
                    "attempt_count": 2,
                    "last_attempted_at": "2023-11-14T22:13:20Z",
                    "last_error": "timed out",
                    "extra_field": "kept",
                }
            ],
            outbox,
        )
        self.assertEqual(outbox, state["notification_outbox"])

    def test_state_daily_notification_delivery_normalizes_legacy_shape_in_place(self):
        state = {
            "discordDelivery": {
                "dailyNotification": {
                    "deliveredLatestKeys": {
                        "work-1": {
                            "latestKey": "episode-2",
                            "deliveredAt": "2023-11-14T22:13:20Z",
                        }
                    },
                    "pendingMessages": [
                        {
                            "channelId": "main-channel",
                            "content": "pending daily message",
                            "messageKeys": [
                                {"workId": "work-1", "latestKey": "episode-2"},
                                {"workId": "work-1", "latestKey": "episode-2"},
                            ],
                            "createdAt": "2023-11-14T22:13:20Z",
                            "attemptCount": "1",
                            "lastAttemptedAt": "2023-11-14T22:14:00Z",
                            "lastError": "discord delivery failed",
                        }
                    ],
                }
            }
        }

        daily_notification = state_daily_notification_delivery(state)

        self.assertEqual(
            {
                "delivered_latest_keys": {
                    "work-1": {
                        "latest_key": "episode-2",
                        "delivered_at": "2023-11-14T22:13:20Z",
                    }
                },
                "pending_messages": [
                    {
                        "channel_id": "main-channel",
                        "content": "pending daily message",
                        "message_keys": [{"work_id": "work-1", "latest_key": "episode-2"}],
                        "created_at": "2023-11-14T22:13:20Z",
                        "attempt_count": 1,
                        "last_attempted_at": "2023-11-14T22:14:00Z",
                        "last_error": "discord delivery failed",
                    }
                ],
            },
            daily_notification,
        )
        self.assertEqual(daily_notification, state["discord_delivery"]["daily_notification"])
        self.assertNotIn("discordDelivery", state)

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

    def test_supertwins_search_sessions_round_trip_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            save_supertwins_search_session(
                "session-a",
                {"root_work_id": "root-1", "selected_urls_by_value": {"u:a": "https://example.com/a"}},
                path=str(state_path),
            )
            save_supertwins_search_session(
                "session-b",
                {"root_work_id": "root-2", "selected_urls_by_value": {"u:b": "https://example.com/b"}},
                path=str(state_path),
            )

            session_a = load_supertwins_search_session("session-a", str(state_path))
            session_b = load_supertwins_search_session("session-b", str(state_path))
            delete_supertwins_search_session("session-a", str(state_path))

        self.assertEqual(
            {"root_work_id": "root-1", "selected_urls_by_value": {"u:a": "https://example.com/a"}},
            session_a,
        )
        self.assertEqual(
            {"root_work_id": "root-2", "selected_urls_by_value": {"u:b": "https://example.com/b"}},
            session_b,
        )
        with self.assertRaises(FileNotFoundError):
            load_supertwins_search_session("session-a", str(state_path))

    def test_validate_watchlist_normalizes_hidden_to_boolean(self):
        normalized = validate_watchlist(
            {
                "version": 2,
                "works": [
                    {
                        "id": "work-visible",
                        "source": "comic-walker",
                        "seed_url": "https://example.com/visible",
                        "enabled": True,
                        "notification_policy": {"mode": "all", "allowed_update_types": None},
                    },
                    {
                        "id": "work-hidden",
                        "source": "comic-walker",
                        "seed_url": "https://example.com/hidden",
                        "enabled": True,
                        "hidden": True,
                        "notification_policy": {"mode": "all", "allowed_update_types": None},
                    },
                ],
            }
        )

        self.assertFalse(normalized["works"][0]["hidden"])
        self.assertTrue(normalized["works"][1]["hidden"])

    def test_validate_watchlist_rejects_non_boolean_hidden(self):
        with self.assertRaisesRegex(ValueError, "watchlist entry work-1 hidden must be boolean"):
            validate_watchlist(
                {
                    "version": 2,
                    "works": [
                        {
                            "id": "work-1",
                            "source": "comic-walker",
                            "seed_url": "https://example.com/work-1",
                            "enabled": True,
                            "hidden": "yes",
                            "notification_policy": {"mode": "all", "allowed_update_types": None},
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
