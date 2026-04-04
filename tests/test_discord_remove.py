import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from manga_watch.discord_remove import (
    REMOVE_COMMAND,
    RemoveCommandHandler,
    build_remove_token,
    remove_watch_subscription,
)
from tests.test_firestore_storage import FakeFirestoreClient, make_state, make_watchlist


def write_json(path: Path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class FailingSaver:
    def __init__(self):
        self.calls = []

    def __call__(self, payload, path=None, backend=None):
        self.calls.append({"payload": payload, "path": path, "backend": backend})
        raise RuntimeError("save failed")


class DiscordRemoveTests(unittest.TestCase):
    def test_start_response_builds_first_page_with_select_menu_and_next_button(self):
        watchlist = {"version": 2, "works": []}
        state = {"version": 2, "works": {}, "last_run_at": None, "notification_outbox": [], "discord_delivery": {"daily_notification": {"delivered_latest_keys": {}, "pending_messages": []}}}
        for index in range(26):
            work_id = f"work-{index:02d}"
            watchlist["works"].append(
                {
                    "id": work_id,
                    "source": "comic-walker",
                    "seed_url": f"https://example.com/{work_id}",
                    "enabled": True,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                }
            )
            state["works"][work_id] = {
                "latest": {"series_title": f"作品{index:02d}"},
                "history": [],
                "unread": {"event_ids": []},
                "health": {},
            }

        handler = RemoveCommandHandler(
            watchlist_loader=lambda _path, backend=None: watchlist,
            state_loader=lambda _path, backend=None: state,
        )

        payload = handler.start()

        self.assertIn("components", payload)
        self.assertEqual("remove_select", payload["components"][0]["components"][0]["custom_id"])
        self.assertEqual(25, len(payload["components"][0]["components"][0]["options"]))
        next_button = payload["components"][1]["components"][1]
        self.assertEqual("remove_page:1", next_button["custom_id"])

    def test_handle_component_select_returns_confirm_buttons(self):
        watchlist = make_watchlist()
        state = make_state()
        token = build_remove_token("work-1")
        handler = RemoveCommandHandler(
            watchlist_loader=lambda _path, backend=None: watchlist,
            state_loader=lambda _path, backend=None: state,
        )

        payload = handler.handle_component({"custom_id": "remove_select", "values": [token]})

        buttons = payload["components"][0]["components"]
        self.assertEqual(f"remove_confirm:{token}", buttons[0]["custom_id"])
        self.assertEqual(f"remove_cancel:{token}", buttons[1]["custom_id"])
        self.assertIn("作品A", payload["content"])

    def test_remove_watch_subscription_removes_work_from_json_watchlist_and_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            state_path = Path(tmpdir) / "state.json"
            write_json(watchlist_path, make_watchlist())
            write_json(state_path, make_state())

            result = remove_watch_subscription(
                "work-1",
                watchlist_path=str(watchlist_path),
                state_path=str(state_path),
            )

            saved_watchlist = json.loads(watchlist_path.read_text(encoding="utf-8"))
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual("removed", result["action"])
        self.assertEqual([], saved_watchlist["works"])
        self.assertEqual({}, saved_state["works"])
        self.assertEqual([], saved_state["notification_outbox"])
        self.assertEqual({}, saved_state["discord_delivery"]["daily_notification"]["delivered_latest_keys"])
        self.assertEqual([], saved_state["discord_delivery"]["daily_notification"]["pending_messages"])

    def test_remove_watch_subscription_prunes_only_removed_work_delivery_state(self):
        watchlist = {
            "version": 2,
            "works": make_watchlist()["works"]
            + [
                {
                    "id": "work-2",
                    "source": "comic-walker",
                    "seed_url": "https://comic-walker.com/detail/work-2",
                    "enabled": True,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                }
            ],
        }
        state = make_state()
        state["works"]["work-2"] = {
            "latest": {
                "series_title": "作品B",
                "episode_title": "第5話",
                "latest_key": "episode-5",
                "url": "https://example.com/episodes/5",
            },
            "history": [],
            "unread": {"event_ids": []},
            "health": {},
        }
        state["notification_outbox"].append(
            {
                "event": {
                    "schema_version": 1,
                    "event_id": "event-2",
                    "work_id": "work-2",
                    "latest_key": "episode-5",
                    "series_title": "作品B",
                    "update_type": "main_story",
                    "detected_at": "2023-11-14T22:13:20Z",
                    "from": {"latest_key": "episode-4"},
                    "to": {"latest_key": "episode-5"},
                },
                "pending_backends": ["stdout"],
                "attempt_count": 0,
                "last_attempted_at": None,
                "last_error": None,
            }
        )
        state["discord_delivery"]["daily_notification"]["delivered_latest_keys"]["work-2"] = {
            "latest_key": "episode-5",
            "delivered_at": None,
        }
        state["discord_delivery"]["daily_notification"]["pending_messages"].append(
            {
                "channel_id": "main-channel",
                "content": "pending daily message for work-2",
                "message_keys": [{"work_id": "work-2", "latest_key": "episode-5"}],
                "created_at": "2023-11-14T22:16:20Z",
                "attempt_count": 0,
                "last_attempted_at": None,
                "last_error": None,
            }
        )
        state["discord_delivery"]["daily_notification"]["pending_messages"].append(
            {
                "channel_id": "main-channel",
                "content": "mixed daily message",
                "message_keys": [
                    {"work_id": "work-1", "latest_key": "episode-2"},
                    {"work_id": "work-2", "latest_key": "episode-5"},
                ],
                "created_at": "2023-11-14T22:17:20Z",
                "attempt_count": 0,
                "last_attempted_at": None,
                "last_error": None,
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "watchlist.json"
            state_path = Path(tmpdir) / "state.json"
            write_json(watchlist_path, watchlist)
            write_json(state_path, state)

            result = remove_watch_subscription(
                "work-1",
                watchlist_path=str(watchlist_path),
                state_path=str(state_path),
            )

            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual("removed", result["action"])
        self.assertEqual({"work-2"}, set(saved_state["works"].keys()))
        self.assertEqual(["work-2"], [entry["event"]["work_id"] for entry in saved_state["notification_outbox"]])
        self.assertEqual(
            {"work-2"},
            set(saved_state["discord_delivery"]["daily_notification"]["delivered_latest_keys"].keys()),
        )
        self.assertEqual(
            ["work-2"],
            [
                entry["message_keys"][0]["work_id"]
                for entry in saved_state["discord_delivery"]["daily_notification"]["pending_messages"]
            ],
        )

    def test_remove_watch_subscription_supports_firestore_backend(self):
        from manga_watch.firestore_storage import FirestoreStorageConfig, FirestoreStorageRepository
        from manga_watch.storage import load_state, load_watchlist, save_state, save_watchlist

        repository = FirestoreStorageRepository(
            config=FirestoreStorageConfig(project="demo-project"),
            client=FakeFirestoreClient(),
        )
        with mock.patch.dict(os.environ, {"MANGA_WATCH_STORAGE_BACKEND": "firestore"}, clear=False):
            with mock.patch("manga_watch.storage.get_firestore_repository", return_value=repository):
                save_watchlist(make_watchlist())
                save_state(make_state())

                result = remove_watch_subscription("work-1")
                saved_watchlist = load_watchlist()
                saved_state = load_state()

        self.assertEqual("removed", result["action"])
        self.assertEqual([], saved_watchlist["works"])
        self.assertEqual({}, saved_state["works"])
        self.assertEqual([], saved_state["notification_outbox"])
        self.assertEqual({}, saved_state["discord_delivery"]["daily_notification"]["delivered_latest_keys"])
        self.assertEqual([], saved_state["discord_delivery"]["daily_notification"]["pending_messages"])

    def test_remove_watch_subscription_rolls_back_watchlist_when_state_save_fails(self):
        watchlist = make_watchlist()
        state = make_state()
        saved_watchlists = []

        def save_watchlist_recorder(payload, path=None, backend=None):
            saved_watchlists.append(json.loads(json.dumps(payload, ensure_ascii=False)))

        result = remove_watch_subscription(
            "work-1",
            watchlist_loader=lambda _path, backend=None: watchlist,
            state_loader=lambda _path, backend=None: state,
            watchlist_saver=save_watchlist_recorder,
            state_saver=FailingSaver(),
        )

        self.assertEqual("failed", result["action"])
        self.assertEqual(make_watchlist(), saved_watchlists[-1])


if __name__ == "__main__":
    unittest.main()
