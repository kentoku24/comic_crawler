import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from manga_watch.discord_supertwins_manage import (
    SUPERTWINS_MANAGE_ACTION_SELECT_PREFIX,
    SUPERTWINS_MANAGE_CONFIRM_DELETE_PREFIX,
    SUPERTWINS_MANAGE_GROUP_SELECT,
    SUPERTWINS_MANAGE_MEMBER_PAGE_PREFIX,
    SUPERTWINS_MANAGE_MEMBER_SELECT_PREFIX,
    ManageSupertwinsCommandHandler,
)
from manga_watch.discord_supertwins_search import (
    SUPERTWINS_SEARCH_RESULT_SELECT_PREFIX,
    SUPERTWINS_SEARCH_WORK_SELECT,
    SearchSupertwinsCommandHandler,
)
from manga_watch.source_search import SearchResult, supported_search_sources
from manga_watch.storage import load_supertwins_search_session


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


def make_state_with_many_supertwins_members(member_count: int = 26):
    state = make_state()
    member_work_ids = [f"work-{index:02d}" for index in range(1, member_count + 1)]
    state["works"] = {
        work_id: {
            "latest": {
                "series_title": f"作品{index:02d}",
                "episode_title": "第1話",
            },
            "history": [],
            "unread": {"event_ids": []},
            "health": {},
        }
        for index, work_id in enumerate(member_work_ids, start=1)
    }
    state["supertwins"] = {
        "groups": {
            "group-1": {
                "member_work_ids": member_work_ids,
            }
        }
    }
    return state, member_work_ids


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

        called_sources = [call["source"] for call in search_source.calls]
        expected_sources = [source for source in supported_search_sources() if source != "champion-cross"]
        self.assertEqual(expected_sources, called_sources)
        self.assertTrue(all(call["query"] == "作品A" for call in search_source.calls))
        self.assertTrue(all(call["limit"] == 10 for call in search_source.calls))
        select = payload["components"][0]["components"][0]
        self.assertTrue(select["custom_id"].startswith(SUPERTWINS_SEARCH_RESULT_SELECT_PREFIX))
        self.assertEqual("作品A", select["options"][0]["label"])

    def test_work_selection_persists_search_session_for_long_candidate_urls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            watchlist_path = tmpdir / "watchlist.json"
            state_path = tmpdir / "state.json"
            write_json(watchlist_path, make_watchlist())
            write_json(state_path, make_state())

            long_url = "https://kakuyomu.jp/works/" + ("1234567890" * 12)
            search_source = FakeSearchSource(
                {
                    "kakuyomu": [
                        SearchResult(
                            source="kakuyomu",
                            title="作品A",
                            seed_url=long_url,
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
            result_select = payload["components"][0]["components"][0]
            custom_id = result_select["custom_id"]
            session_token = custom_id[len(SUPERTWINS_SEARCH_RESULT_SELECT_PREFIX) :]
            selected_value = result_select["options"][0]["value"]
            saved_session = load_supertwins_search_session(session_token, str(state_path))

        self.assertLessEqual(len(selected_value), 100)
        self.assertTrue(custom_id.startswith(SUPERTWINS_SEARCH_RESULT_SELECT_PREFIX))
        self.assertTrue(session_token)
        self.assertEqual(
            {
                "root_work_id": "root-1",
                "selected_urls_by_value": {
                    selected_value: long_url,
                },
            },
            saved_session,
        )

    def test_work_selection_includes_three_real_target_media_when_title_matches(self):
        watchlist = {
            "version": 2,
            "works": [
                {
                    "id": "root-1",
                    "source": "champion-cross",
                    "seed_url": "https://championcross.jp/series/root-1",
                    "enabled": True,
                    "hidden": False,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                }
            ],
        }
        state = make_state()
        state["works"] = {
            "root-1": {
                "latest": {"series_title": "ダンジョンの中のひと", "episode_title": "第1話"},
                "history": [],
                "unread": {"event_ids": []},
                "health": {},
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            watchlist_path = tmpdir / "watchlist.json"
            state_path = tmpdir / "state.json"
            write_json(watchlist_path, watchlist)
            write_json(state_path, state)

            search_source = FakeSearchSource(
                {
                    "comic-action": [
                        SearchResult(
                            source="comic-action",
                            title="ダンジョンの中のひと",
                            seed_url="https://comic-action.com/episode/13933686331665056851",
                            subtitle="comic-action",
                        )
                    ],
                    "nicovideo-manga": [
                        SearchResult(
                            source="nicovideo-manga",
                            title="ダンジョンの中のひと",
                            seed_url="https://manga.nicovideo.jp/comic/53764",
                            subtitle="nicovideo-manga",
                        )
                    ],
                    "gaugau": [
                        SearchResult(
                            source="gaugau",
                            title="ダンジョンの中のひと",
                            seed_url="https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000",
                            subtitle="gaugau",
                        )
                    ],
                }
            )
            handler = SearchSupertwinsCommandHandler(search_source=search_source)
            payload = handler.handle_component(
                {"custom_id": SUPERTWINS_SEARCH_WORK_SELECT, "values": ["root-1"]},
                watchlist_path=str(watchlist_path),
                state_path=str(state_path),
            )

        self.assertTrue(
            {"comic-action", "nicovideo-manga", "gaugau"}.issubset(
                {call["source"] for call in search_source.calls}
            )
        )
        options = payload["components"][0]["components"][0]["options"]
        self.assertTrue(
            {"comic-action", "nicovideo-manga", "gaugau"}.issubset(
                {option["description"] for option in options}
            ),
            msg=str(options),
        )

    def test_work_selection_uses_unique_session_token_per_interaction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            watchlist_path = tmpdir / "watchlist.json"
            state_path = tmpdir / "state.json"
            write_json(watchlist_path, make_watchlist())
            write_json(state_path, make_state())

            long_url = "https://kakuyomu.jp/works/" + ("1234567890" * 12)
            search_source = FakeSearchSource(
                {
                    "kakuyomu": [
                        SearchResult(
                            source="kakuyomu",
                            title="作品A",
                            seed_url=long_url,
                            subtitle="kakuyomu",
                        )
                    ]
                }
            )
            handler = SearchSupertwinsCommandHandler(search_source=search_source)
            first_payload = handler.handle_component(
                {"custom_id": SUPERTWINS_SEARCH_WORK_SELECT, "values": ["root-1"]},
                watchlist_path=str(watchlist_path),
                state_path=str(state_path),
            )
            second_payload = handler.handle_component(
                {"custom_id": SUPERTWINS_SEARCH_WORK_SELECT, "values": ["root-1"]},
                watchlist_path=str(watchlist_path),
                state_path=str(state_path),
            )

            first_custom_id = first_payload["components"][0]["components"][0]["custom_id"]
            second_custom_id = second_payload["components"][0]["components"][0]["custom_id"]
            first_token = first_custom_id[len(SUPERTWINS_SEARCH_RESULT_SELECT_PREFIX) :]
            second_token = second_custom_id[len(SUPERTWINS_SEARCH_RESULT_SELECT_PREFIX) :]
            first_value = first_payload["components"][0]["components"][0]["options"][0]["value"]
            second_value = second_payload["components"][0]["components"][0]["options"][0]["value"]
            first_session = load_supertwins_search_session(first_token, str(state_path))
            second_session = load_supertwins_search_session(second_token, str(state_path))

        self.assertNotEqual(first_custom_id, second_custom_id)
        self.assertNotEqual(first_token, second_token)
        self.assertEqual(first_value, second_value)
        self.assertEqual(
            {
                "root_work_id": "root-1",
                "selected_urls_by_value": {
                    first_value: long_url,
                },
            },
            first_session,
        )
        self.assertEqual(first_session, second_session)

    def test_start_paginates_root_work_options_beyond_25_entries(self):
        watchlist = make_watchlist()
        state = make_state()
        for index in range(3, 31):
            work_id = f"work-{index}"
            watchlist["works"].append(
                {
                    "id": work_id,
                    "source": "kakuyomu",
                    "seed_url": f"https://kakuyomu.jp/works/{index}",
                    "enabled": True,
                    "hidden": False,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                }
            )
            state["works"][work_id] = {
                "latest": {"series_title": f"作品{index}", "episode_title": "第1話"},
                "history": [],
                "unread": {"event_ids": []},
                "health": {},
            }

        handler = SearchSupertwinsCommandHandler(
            search_source=FakeSearchSource({}),
            watchlist_loader=lambda *args, **kwargs: watchlist,
            state_loader=lambda *args, **kwargs: state,
        )

        first_page = handler.start()
        first_select = first_page["components"][0]["components"][0]
        next_button = first_page["components"][1]["components"][1]
        second_page = handler.handle_component({"custom_id": next_button["custom_id"]})
        second_select = second_page["components"][0]["components"][0]

        self.assertEqual(25, len(first_select["options"]))
        self.assertEqual(
            "supertwins_search:page:1",
            next_button["custom_id"],
        )
        self.assertEqual(5, len(second_select["options"]))
        self.assertEqual(
            "supertwins_search:page:0",
            second_page["components"][1]["components"][0]["custom_id"],
        )

    def test_result_selection_adds_hidden_subscription_and_registers_group(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            watchlist_path = tmpdir / "watchlist.json"
            state_path = tmpdir / "state.json"
            write_json(watchlist_path, make_watchlist())
            write_json(state_path, make_state())

            long_url = "https://kakuyomu.jp/works/" + ("1234567890" * 12)
            search_source = FakeSearchSource(
                {
                    "kakuyomu": [
                        SearchResult(
                            source="kakuyomu",
                            title="作品A",
                            seed_url=long_url,
                            subtitle="kakuyomu",
                        )
                    ]
                }
            )
            first_handler = SearchSupertwinsCommandHandler(search_source=search_source)
            selection_payload = first_handler.handle_component(
                {"custom_id": SUPERTWINS_SEARCH_WORK_SELECT, "values": ["root-1"]},
                watchlist_path=str(watchlist_path),
                state_path=str(state_path),
            )
            result_select = selection_payload["components"][0]["components"][0]
            custom_id = result_select["custom_id"]
            selected_value = result_select["options"][0]["value"]

            second_handler = SearchSupertwinsCommandHandler(search_source=search_source)
            with mock.patch(
                "manga_watch.discord_supertwins_search.build_watchlist_preview",
                return_value={
                    "id": "kakuyomu:long",
                    "source": "kakuyomu",
                    "seed_url": long_url,
                    "enabled": True,
                    "hidden": False,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                },
            ):
                payload = second_handler.handle_component(
                    {
                        "custom_id": custom_id,
                        "values": [selected_value],
                    },
                    watchlist_path=str(watchlist_path),
                    state_path=str(state_path),
                )

            saved_watchlist = json.loads(watchlist_path.read_text(encoding="utf-8"))
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertIn("hidden で追加", payload["content"])
        self.assertTrue(
            next(entry for entry in saved_watchlist["works"] if entry["id"] == "kakuyomu:long")["hidden"]
        )
        self.assertEqual(
            ["kakuyomu:long", "root-1", "work-2"],
            saved_state["supertwins"]["groups"]["group-1"]["member_work_ids"],
        )
        self.assertNotIn("root-1", saved_state["supertwins"]["groups"])
        with self.assertRaises(FileNotFoundError):
            load_supertwins_search_session(custom_id[len(SUPERTWINS_SEARCH_RESULT_SELECT_PREFIX) :], str(state_path))

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
            selection_payload = handler.handle_component(
                {"custom_id": SUPERTWINS_SEARCH_WORK_SELECT, "values": ["root-1"]},
                watchlist_path=str(watchlist_path),
                state_path=str(state_path),
            )
            result_select = selection_payload["components"][0]["components"][0]

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
                        "custom_id": result_select["custom_id"],
                        "values": [result_select["options"][0]["value"]],
                    },
                    watchlist_path=str(watchlist_path),
                    state_path=str(state_path),
                )

            saved_watchlist = json.loads(watchlist_path.read_text(encoding="utf-8"))
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(
            next(entry for entry in saved_watchlist["works"] if entry["id"] == "kakuyomu:123")["hidden"]
        )
        self.assertEqual(
            ["kakuyomu:123", "root-1", "work-2"],
            saved_state["supertwins"]["groups"]["group-1"]["member_work_ids"],
        )

    def test_result_selection_trims_resolved_url_loaded_from_session_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            watchlist_path = tmpdir / "watchlist.json"
            state_path = tmpdir / "state.json"
            write_json(watchlist_path, make_watchlist())
            write_json(state_path, make_state())

            handler = SearchSupertwinsCommandHandler(
                search_source=FakeSearchSource({}),
                search_session_loader=lambda *args, **kwargs: {
                    "root_work_id": "root-1",
                    "selected_urls_by_value": {
                        "u:token-1": "  https://kakuyomu.jp/works/123  ",
                    },
                },
                search_session_deleter=lambda *args, **kwargs: None,
            )

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
            ) as build_preview:
                payload = handler.handle_component(
                    {
                        "custom_id": f"{SUPERTWINS_SEARCH_RESULT_SELECT_PREFIX}session-1",
                        "values": ["u:token-1"],
                    },
                    watchlist_path=str(watchlist_path),
                    state_path=str(state_path),
                )

        self.assertIn("hidden で追加", payload["content"])
        build_preview.assert_called_once_with("https://kakuyomu.jp/works/123")


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

    def test_member_selection_paginates_beyond_25_options(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            state_path = tmpdir / "state.json"
            state, _member_work_ids = make_state_with_many_supertwins_members()
            write_json(state_path, state)

            handler = ManageSupertwinsCommandHandler()
            payload = handler.handle_component(
                {"custom_id": SUPERTWINS_MANAGE_GROUP_SELECT, "values": ["group-1"]},
                state_path=str(state_path),
            )
            select = payload["components"][0]["components"][0]
            next_button = payload["components"][1]["components"][1]

            second_page = handler.handle_component(
                {"custom_id": next_button["custom_id"]},
                state_path=str(state_path),
            )
            second_select = second_page["components"][0]["components"][0]

        self.assertEqual(25, len(select["options"]))
        self.assertEqual(["work-01", "work-25"], [select["options"][0]["value"], select["options"][-1]["value"]])
        self.assertEqual(f"{SUPERTWINS_MANAGE_MEMBER_PAGE_PREFIX}group-1:1", next_button["custom_id"])
        self.assertEqual(1, len(second_select["options"]))
        self.assertEqual("work-26", second_select["options"][0]["value"])
        self.assertEqual(f"{SUPERTWINS_MANAGE_MEMBER_PAGE_PREFIX}group-1:0", second_page["components"][1]["components"][0]["custom_id"])

    def test_later_page_member_can_be_selected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            state_path = tmpdir / "state.json"
            state, _member_work_ids = make_state_with_many_supertwins_members()
            write_json(state_path, state)

            handler = ManageSupertwinsCommandHandler()
            handler.handle_component(
                {"custom_id": SUPERTWINS_MANAGE_GROUP_SELECT, "values": ["group-1"]},
                state_path=str(state_path),
            )
            handler.handle_component(
                {"custom_id": f"{SUPERTWINS_MANAGE_MEMBER_PAGE_PREFIX}group-1:1"},
                state_path=str(state_path),
            )
            payload = handler.handle_component(
                {
                    "custom_id": f"{SUPERTWINS_MANAGE_MEMBER_SELECT_PREFIX}group-1",
                    "values": ["work-26"],
                },
                state_path=str(state_path),
            )
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual("member を group から外したあと、どう扱うか選んでください。", payload["content"])
        self.assertEqual(
            ["work-26"],
            next(iter(saved_state["supertwins"]["pending_actions"].values()))["member_work_ids"],
        )

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
