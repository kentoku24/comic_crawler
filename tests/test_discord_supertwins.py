import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from manga_watch.discord_supertwins_manage import (
    SUPERTWINS_MANAGE_ACTION_SELECT_PREFIX,
    SUPERTWINS_MANAGE_CONFIRM_DELETE_PREFIX,
    SUPERTWINS_MANAGE_GROUP_SELECT,
    SUPERTWINS_MANAGE_MEMBER_SELECT_PREFIX,
    ManageSupertwinsCommandHandler,
)
from manga_watch.discord_supertwins_search import (
    SUPERTWINS_SEARCH_RESULT_SELECT_PREFIX,
    SUPERTWINS_SEARCH_WORK_SELECT,
    SearchSupertwinsCommandHandler,
)
from manga_watch.source_search import SearchResult


def make_watchlist():
    return {
        "version": 2,
        "works": [
            {
                "id": "root-1",
                "source": "champion-cross",
                "seed_url": "https://championcross.jp/series/root-1",
                "enabled": True,
                "hidden": False,
                "notification_policy": {"mode": "all", "allowed_update_types": None},
            },
            {
                "id": "work-2",
                "source": "kakuyomu",
                "seed_url": "https://kakuyomu.jp/works/222",
                "enabled": True,
                "hidden": True,
                "notification_policy": {"mode": "all", "allowed_update_types": None},
            },
        ],
    }


def make_state():
    return {
        "version": 2,
        "works": {
            "root-1": {
                "latest": {"series_title": "作品A", "episode_title": "第1話"},
                "history": [],
                "unread": {"event_ids": []},
                "health": {},
            },
            "work-2": {
                "latest": {"series_title": "作品B", "episode_title": "第2話"},
                "history": [],
                "unread": {"event_ids": []},
                "health": {},
            },
        },
        "last_run_at": None,
        "notification_outbox": [],
        "discord_delivery": {
            "daily_notification": {
                "delivered_latest_keys": {},
                "pending_messages": [],
            }
        },
        "supertwins": {
            "groups": {
                "group-1": {"member_work_ids": ["root-1", "work-2"]},
            }
        },
    }


def write_json(path: Path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class FakeSearchSource:
    def __init__(self, results_by_source):
        self.results_by_source = results_by_source
        self.calls = []

    def __call__(self, source, query, *, http_client=None, limit=10):
        self.calls.append(
            {
                "source": source,
                "query": query,
                "http_client": http_client,
                "limit": limit,
            }
        )
        return list(self.results_by_source.get(source, []))


class DiscordSupertwinsSearchTests(unittest.TestCase):
    def test_start_lists_existing_watchlist_works(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            watchlist_path = tmpdir / "watchlist.json"
            state_path = tmpdir / "state.json"
            write_json(watchlist_path, make_watchlist())
            write_json(state_path, make_state())

            handler = SearchSupertwinsCommandHandler(search_source=FakeSearchSource({}))
            payload = handler.start(
                watchlist_path=str(watchlist_path),
                state_path=str(state_path),
            )

        select = payload["components"][0]["components"][0]
        self.assertEqual(SUPERTWINS_SEARCH_WORK_SELECT, select["custom_id"])
        self.assertEqual(["作品A", "作品B"], [option["label"] for option in select["options"]])

    def test_work_selection_searches_other_supported_sources_using_current_title(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            watchlist_path = tmpdir / "watchlist.json"
            state_path = tmpdir / "state.json"
            write_json(watchlist_path, make_watchlist())
            write_json(state_path, make_state())

            search_source = FakeSearchSource(
                {
                    "kakuyomu": [
                        SearchResult(
                            source="kakuyomu",
                            title="作品A",
                            seed_url="https://kakuyomu.jp/works/123",
                            subtitle="kakuyomu",
                        )
                    ]
                }
            )
            handler = SearchSupertwinsCommandHandler(search_source=search_source)
            payload = handler.handle_component(
                {"custom_id": SUPERTWINS_SEARCH_WORK_SELECT, "values": ["root-1"]},
                watchlist_path=str(watchlist_path),
                state_path=str(state_path),
            )

        self.assertEqual(
            [
                {
                    "source": "kakuyomu",
                    "query": "作品A",
                    "http_client": None,
                    "limit": 10,
                }
            ],
            search_source.calls,
        )
        select = payload["components"][0]["components"][0]
        self.assertEqual(f"{SUPERTWINS_SEARCH_RESULT_SELECT_PREFIX}root-1", select["custom_id"])
        self.assertEqual("作品A", select["options"][0]["label"])

    def test_result_selection_adds_hidden_subscription_and_registers_group(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            watchlist_path = tmpdir / "watchlist.json"
            state_path = tmpdir / "state.json"
            write_json(watchlist_path, make_watchlist())
            write_json(state_path, make_state())

            handler = SearchSupertwinsCommandHandler(search_source=FakeSearchSource({}))
            with mock.patch(
                "manga_watch.discord_supertwins_search.build_watchlist_preview",
                return_value={
                    "id": "kakuyomu:123",
                    "source": "kakuyomu",
                    "seed_url": "https://kakuyomu.jp/works/123",
                    "enabled": True,
                    "hidden": False,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                },
            ):
                payload = handler.handle_component(
                    {
                        "custom_id": f"{SUPERTWINS_SEARCH_RESULT_SELECT_PREFIX}root-1",
                        "values": ["https://kakuyomu.jp/works/123"],
                    },
                    watchlist_path=str(watchlist_path),
                    state_path=str(state_path),
                )

            saved_watchlist = json.loads(watchlist_path.read_text(encoding="utf-8"))
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertIn("hidden で追加", payload["content"])
        self.assertTrue(
            next(entry for entry in saved_watchlist["works"] if entry["id"] == "kakuyomu:123")["hidden"]
        )
        self.assertEqual(
            ["kakuyomu:123", "root-1"],
            saved_state["supertwins"]["groups"]["root-1"]["member_work_ids"],
        )

    def test_result_selection_hides_existing_duplicate_and_registers_group(self):
        watchlist = make_watchlist()
        watchlist["works"].append(
            {
                "id": "kakuyomu:123",
                "source": "kakuyomu",
                "seed_url": "https://kakuyomu.jp/works/123",
                "enabled": True,
                "hidden": False,
                "notification_policy": {"mode": "all", "allowed_update_types": None},
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            watchlist_path = tmpdir / "watchlist.json"
            state_path = tmpdir / "state.json"
            write_json(watchlist_path, watchlist)
            write_json(state_path, make_state())

            handler = SearchSupertwinsCommandHandler(search_source=FakeSearchSource({}))
            with mock.patch(
                "manga_watch.discord_supertwins_search.build_watchlist_preview",
                return_value={
                    "id": "kakuyomu:123",
                    "source": "kakuyomu",
                    "seed_url": "https://kakuyomu.jp/works/123",
                    "enabled": True,
                    "hidden": False,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                },
            ):
                handler.handle_component(
                    {
                        "custom_id": f"{SUPERTWINS_SEARCH_RESULT_SELECT_PREFIX}root-1",
                        "values": ["https://kakuyomu.jp/works/123"],
                    },
                    watchlist_path=str(watchlist_path),
                    state_path=str(state_path),
                )

            saved_watchlist = json.loads(watchlist_path.read_text(encoding="utf-8"))

        self.assertTrue(
            next(entry for entry in saved_watchlist["works"] if entry["id"] == "kakuyomu:123")["hidden"]
        )


class DiscordSupertwinsManageTests(unittest.TestCase):
    def test_start_lists_groups_and_selection_returns_members(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            state_path = tmpdir / "state.json"
            write_json(state_path, make_state())

            handler = ManageSupertwinsCommandHandler()
            payload = handler.start(state_path=str(state_path))
            select = payload["components"][0]["components"][0]
            self.assertEqual(SUPERTWINS_MANAGE_GROUP_SELECT, select["custom_id"])

            payload = handler.handle_component(
                {"custom_id": SUPERTWINS_MANAGE_GROUP_SELECT, "values": ["group-1"]},
                state_path=str(state_path),
            )

        select = payload["components"][0]["components"][0]
        self.assertEqual(f"{SUPERTWINS_MANAGE_MEMBER_SELECT_PREFIX}group-1", select["custom_id"])
        self.assertEqual(["作品A", "作品B"], [option["label"] for option in select["options"]])

    def test_keep_hidden_removes_member_from_group_without_unhiding(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            watchlist_path = tmpdir / "watchlist.json"
            state_path = tmpdir / "state.json"
            write_json(watchlist_path, make_watchlist())
            write_json(state_path, make_state())

            handler = ManageSupertwinsCommandHandler()
            handler.handle_component(
                {"custom_id": SUPERTWINS_MANAGE_GROUP_SELECT, "values": ["group-1"]},
                state_path=str(state_path),
            )
            payload = handler.handle_component(
                {
                    "custom_id": f"{SUPERTWINS_MANAGE_MEMBER_SELECT_PREFIX}group-1",
                    "values": ["work-2"],
                },
                state_path=str(state_path),
            )
            action_select = payload["components"][0]["components"][0]
            token = action_select["custom_id"][len(SUPERTWINS_MANAGE_ACTION_SELECT_PREFIX) :]
            payload = handler.handle_component(
                {
                    "custom_id": f"{SUPERTWINS_MANAGE_ACTION_SELECT_PREFIX}{token}",
                    "values": ["keep_hidden"],
                },
                watchlist_path=str(watchlist_path),
                state_path=str(state_path),
            )
            saved_watchlist = json.loads(watchlist_path.read_text(encoding="utf-8"))
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertIn("hidden のまま", payload["content"])
        self.assertTrue(
            next(entry for entry in saved_watchlist["works"] if entry["id"] == "work-2")["hidden"]
        )
        self.assertEqual(["root-1"], saved_state["supertwins"]["groups"]["group-1"]["member_work_ids"])

    def test_unhide_removes_member_from_group_and_clears_hidden_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            watchlist_path = tmpdir / "watchlist.json"
            state_path = tmpdir / "state.json"
            write_json(watchlist_path, make_watchlist())
            write_json(state_path, make_state())

            handler = ManageSupertwinsCommandHandler()
            handler.handle_component(
                {"custom_id": SUPERTWINS_MANAGE_GROUP_SELECT, "values": ["group-1"]},
                state_path=str(state_path),
            )
            payload = handler.handle_component(
                {
                    "custom_id": f"{SUPERTWINS_MANAGE_MEMBER_SELECT_PREFIX}group-1",
                    "values": ["work-2"],
                },
                state_path=str(state_path),
            )
            action_select = payload["components"][0]["components"][0]
            token = action_select["custom_id"][len(SUPERTWINS_MANAGE_ACTION_SELECT_PREFIX) :]
            handler.handle_component(
                {
                    "custom_id": f"{SUPERTWINS_MANAGE_ACTION_SELECT_PREFIX}{token}",
                    "values": ["unhide"],
                },
                watchlist_path=str(watchlist_path),
                state_path=str(state_path),
            )
            saved_watchlist = json.loads(watchlist_path.read_text(encoding="utf-8"))
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertFalse(
            next(entry for entry in saved_watchlist["works"] if entry["id"] == "work-2")["hidden"]
        )
        self.assertEqual(["root-1"], saved_state["supertwins"]["groups"]["group-1"]["member_work_ids"])

    def test_delete_requires_confirm_and_removes_subscription(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            watchlist_path = tmpdir / "watchlist.json"
            state_path = tmpdir / "state.json"
            write_json(watchlist_path, make_watchlist())
            write_json(state_path, make_state())

            handler = ManageSupertwinsCommandHandler()
            handler.handle_component(
                {"custom_id": SUPERTWINS_MANAGE_GROUP_SELECT, "values": ["group-1"]},
                state_path=str(state_path),
            )
            payload = handler.handle_component(
                {
                    "custom_id": f"{SUPERTWINS_MANAGE_MEMBER_SELECT_PREFIX}group-1",
                    "values": ["work-2"],
                },
                state_path=str(state_path),
            )
            action_select = payload["components"][0]["components"][0]
            token = action_select["custom_id"][len(SUPERTWINS_MANAGE_ACTION_SELECT_PREFIX) :]
            confirm_payload = handler.handle_component(
                {
                    "custom_id": f"{SUPERTWINS_MANAGE_ACTION_SELECT_PREFIX}{token}",
                    "values": ["delete"],
                },
                watchlist_path=str(watchlist_path),
                state_path=str(state_path),
            )
            self.assertEqual("選択した subscription を削除します。よければ confirm を押してください。", confirm_payload["content"])
            self.assertEqual(
                f"{SUPERTWINS_MANAGE_CONFIRM_DELETE_PREFIX}{token}",
                confirm_payload["components"][0]["components"][0]["custom_id"],
            )

            handler.handle_component(
                {
                    "custom_id": f"{SUPERTWINS_MANAGE_CONFIRM_DELETE_PREFIX}{token}",
                },
                watchlist_path=str(watchlist_path),
                state_path=str(state_path),
            )
            saved_watchlist = json.loads(watchlist_path.read_text(encoding="utf-8"))
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertNotIn("work-2", [entry["id"] for entry in saved_watchlist["works"]])
        self.assertEqual(["root-1"], saved_state["supertwins"]["groups"]["group-1"]["member_work_ids"])
        self.assertNotIn("work-2", saved_state["works"])


if __name__ == "__main__":
    unittest.main()
