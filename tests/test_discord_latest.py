import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from manga_watch.discord_latest import (
    EMPTY_LINE,
    PARTIAL_FAILURE_WARNING,
    build_latest_query_response,
    handle_latest_query,
)
from manga_watch.discord_text import (
    format_discord_link,
    latest_display_label_for_snapshot,
    truncate_episode_label,
)


class DiscordLatestTests(unittest.TestCase):
    def make_watchlist(self, works):
        return {"version": 2, "works": works}

    def make_state(self, works, *, last_run_at=None):
        return {
            "version": 2,
            "works": works,
            "last_run_at": last_run_at,
            "notification_outbox": [],
        }

    def write_payloads(self, watchlist, state):
        tempdir = tempfile.TemporaryDirectory()
        root = Path(tempdir.name)
        watchlist_path = root / "watchlist.json"
        state_path = root / "state.json"
        watchlist_path.write_text(json.dumps(watchlist, ensure_ascii=False), encoding="utf-8")
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        return tempdir, watchlist_path, state_path

    def test_handle_latest_query_routes_only_trimmed_exact_latest(self):
        watchlist = self.make_watchlist(
            [
                {
                    "id": "work-1",
                    "source": "comic-walker",
                    "seed_url": "https://example.com/work-1",
                    "enabled": True,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                }
            ]
        )
        state = self.make_state(
            {
                "work-1": {
                    "latest": {
                        "series_title": "作品A",
                        "episode_title": "第2話",
                        "url": "https://example.com/2",
                    },
                    "history": [],
                    "health": {"consecutive_failures": 0},
                }
            },
            last_run_at=1_700_000_000,
        )
        tempdir, watchlist_path, state_path = self.write_payloads(watchlist, state)
        self.addCleanup(tempdir.cleanup)

        response = handle_latest_query(
            "  latest  ",
            watchlist_path=str(watchlist_path),
            state_path=str(state_path),
            timezone_name="Asia/Tokyo",
        )

        self.assertIsNotNone(response)
        self.assertIn("保存済みの最新話一覧です", response)
        self.assertIsNone(
            handle_latest_query(
                "latest please",
                watchlist_path=str(watchlist_path),
                state_path=str(state_path),
                timezone_name="Asia/Tokyo",
            )
        )

    def test_build_latest_query_response_matrix(self):
        def run_watchlist_order_ignores_disabled_and_orphans(test):
            watchlist = test.make_watchlist(
                [
                    {
                        "id": "work-b",
                        "source": "comic-walker",
                        "seed_url": "https://example.com/work-b",
                        "enabled": True,
                        "notification_policy": {"mode": "all", "allowed_update_types": None},
                    },
                    {
                        "id": "work-a",
                        "source": "comic-walker",
                        "seed_url": "https://example.com/work-a",
                        "enabled": True,
                        "notification_policy": {"mode": "all", "allowed_update_types": None},
                    },
                    {
                        "id": "work-disabled",
                        "source": "comic-walker",
                        "seed_url": "https://example.com/work-disabled",
                        "enabled": False,
                        "notification_policy": {"mode": "all", "allowed_update_types": None},
                    },
                ]
            )
            state = test.make_state(
                {
                    "work-a": {
                        "latest": {"series_title": "作品A", "episode_title": "第1話", "url": "https://example.com/a"},
                        "history": [],
                        "health": {"consecutive_failures": 0},
                    },
                    "work-b": {
                        "latest": {"series_title": "作品B", "episode_title": "第8話", "url": "https://example.com/b"},
                        "history": [],
                        "health": {"consecutive_failures": 0},
                    },
                    "work-disabled": {
                        "latest": {"series_title": "作品C", "episode_title": "第9話", "url": "https://example.com/c"},
                        "history": [],
                        "health": {"consecutive_failures": 0},
                    },
                    "orphan": {
                        "latest": {"series_title": "孤児", "episode_title": "第99話", "url": "https://example.com/orphan"},
                        "history": [],
                        "health": {"consecutive_failures": 0},
                    },
                },
                last_run_at=1_700_000_000,
            )

            response = build_latest_query_response(watchlist, state, timezone_name="Asia/Tokyo")
            lines = response.splitlines()

            test.assertEqual("現在のリスト:", lines[2])
            test.assertEqual("[第8話](<https://example.com/b>)　作品B", lines[3])
            test.assertEqual("[第1話](<https://example.com/a>)　作品A", lines[4])
            test.assertNotIn("作品C", response)
            test.assertNotIn("孤児", response)

        def run_excludes_hidden_entries(test):
            watchlist = test.make_watchlist(
                [
                    {
                        "id": "work-visible",
                        "source": "comic-walker",
                        "seed_url": "https://example.com/work-visible",
                        "enabled": True,
                        "notification_policy": {"mode": "all", "allowed_update_types": None},
                    },
                    {
                        "id": "work-hidden",
                        "source": "comic-walker",
                        "seed_url": "https://example.com/work-hidden",
                        "enabled": True,
                        "hidden": True,
                        "notification_policy": {"mode": "all", "allowed_update_types": None},
                    },
                ]
            )
            state = test.make_state(
                {
                    "work-visible": {
                        "latest": {"series_title": "表示作品", "episode_title": "第3話", "url": "https://example.com/visible"},
                        "history": [],
                        "health": {"consecutive_failures": 0},
                    },
                    "work-hidden": {
                        "latest": {"series_title": "非表示作品", "episode_title": "第9話", "url": "https://example.com/hidden"},
                        "history": [],
                        "health": {"consecutive_failures": 0},
                    },
                },
                last_run_at=1_700_000_000,
            )

            response = build_latest_query_response(watchlist, state, timezone_name="Asia/Tokyo")

            test.assertIn("表示作品", response)
            test.assertNotIn("非表示作品", response)

        def run_empty_message_when_all_works_are_unfetched(test):
            watchlist = test.make_watchlist(
                [
                    {
                        "id": "work-1",
                        "source": "comic-walker",
                        "seed_url": "https://example.com/work-1",
                        "enabled": True,
                        "notification_policy": {"mode": "all", "allowed_update_types": None},
                    },
                    {
                        "id": "work-2",
                        "source": "comic-walker",
                        "seed_url": "https://example.com/work-2",
                        "enabled": True,
                        "notification_policy": {"mode": "all", "allowed_update_types": None},
                    },
                ]
            )
            state = test.make_state(
                {
                    "work-1": {"latest": {}, "history": [], "health": {"consecutive_failures": 0}},
                    "work-2": {"latest": {}, "history": [], "health": {"consecutive_failures": 0}},
                }
            )

            response = build_latest_query_response(watchlist, state, timezone_name="Asia/Tokyo")

            test.assertIn("最終巡回: まだ実行されていません", response)
            test.assertTrue(response.endswith(EMPTY_LINE))
            test.assertNotIn("（未取得）", response)

        def run_unfetched_rows_when_mixed_with_saved_results(test):
            watchlist = test.make_watchlist(
                [
                    {
                        "id": "work-1",
                        "source": "comic-walker",
                        "seed_url": "https://example.com/work-1",
                        "enabled": True,
                        "notification_policy": {"mode": "all", "allowed_update_types": None},
                    },
                    {
                        "id": "work-2",
                        "source": "comic-walker",
                        "seed_url": "https://example.com/work-2",
                        "enabled": True,
                        "notification_policy": {"mode": "all", "allowed_update_types": None},
                    },
                ]
            )
            state = test.make_state(
                {
                    "work-1": {
                        "latest": {
                            "series_title": "作品A",
                            "episode_title": "第71話 abcdefghijk",
                            "url": "https://example.com/71",
                        },
                        "history": [],
                        "health": {"consecutive_failures": 1},
                    },
                    "work-2": {"latest": {}, "history": [], "health": {"consecutive_failures": 0}},
                }
            )

            response = build_latest_query_response(watchlist, state, timezone_name="Asia/Tokyo")

            test.assertIn("[第71話 abcdefg…](<https://example.com/71>)　作品A", response)
            test.assertIn("（未取得）　work-2", response)
            test.assertTrue(response.endswith(PARTIAL_FAILURE_WARNING))

        def run_saved_next_update_label(test):
            watchlist = test.make_watchlist(
                [
                    {
                        "id": "work-1",
                        "source": "comic-walker",
                        "seed_url": "https://example.com/work-1",
                        "enabled": True,
                        "notification_policy": {"mode": "all", "allowed_update_types": None},
                    }
                ]
            )
            state = test.make_state(
                {
                    "work-1": {
                        "latest": {
                            "series_title": "作品A",
                            "episode_title": "第2話",
                            "next_update_label": "次回更新予定 3/15",
                            "url": "https://example.com/2",
                        },
                        "history": [],
                        "health": {"consecutive_failures": 0},
                    }
                },
                last_run_at=1_700_000_000,
            )

            response = build_latest_query_response(watchlist, state, timezone_name="Asia/Tokyo")

            test.assertIn(
                "[第2話（次回更新予定 3/15）](<https://example.com/2>)　作品A",
                response,
            )

        def run_plain_text_and_fallback_labels_without_url(test):
            watchlist = test.make_watchlist(
                [
                    {
                        "id": "work-1",
                        "source": "comic-walker",
                        "seed_url": "https://example.com/work-1",
                        "enabled": True,
                        "notification_policy": {"mode": "all", "allowed_update_types": None},
                    }
                ]
            )
            state = test.make_state(
                {
                    "work-1": {
                        "latest": {
                            "series": "作品A fallback",
                            "episode_code": "ep-2",
                        },
                        "history": [],
                        "health": {"consecutive_failures": 0},
                    }
                },
                last_run_at=1_700_000_000,
            )

            response = build_latest_query_response(watchlist, state, timezone_name="Asia/Tokyo")

            test.assertIn("ep-2　作品A fallback", response)
            test.assertNotIn("[ep-2]", response)

        def run_stale_saved_data_warning(test):
            watchlist = test.make_watchlist(
                [
                    {
                        "id": "work-1",
                        "source": "comic-walker",
                        "seed_url": "https://example.com/work-1",
                        "enabled": True,
                        "health_policy": {"expected_interval_seconds": 3_600},
                        "notification_policy": {"mode": "all", "allowed_update_types": None},
                    }
                ]
            )
            state = test.make_state(
                {
                    "work-1": {
                        "latest": {
                            "series_title": "作品A",
                            "episode_title": "第2話",
                            "url": "https://example.com/2",
                        },
                        "history": [],
                        "health": {
                            "last_checked_at": 1_700_010_000,
                            "last_success_at": 1_700_000_000,
                            "consecutive_failures": 0,
                        },
                    }
                },
                last_run_at=1_700_010_000,
            )

            response = build_latest_query_response(
                watchlist,
                state,
                timezone_name="Asia/Tokyo",
                now=1_700_008_000,
            )

            test.assertTrue(response.endswith(PARTIAL_FAILURE_WARNING))

        def run_episode_label_truncation_spec_examples(test):
            test.assertEqual("第71話 abcdefg…", truncate_episode_label("第71話 abcdefghijk"))
            test.assertEqual("第71話 あいうえおかき…", truncate_episode_label("第71話 あいうえおかきくけ"))
            test.assertEqual("第71話 abあいうcd…", truncate_episode_label("第71話 abあいうcdef"))
            test.assertEqual("abcdefghijklmnopqrs…", truncate_episode_label("abcdefghijklmnopqrstu"))
            test.assertEqual("第55話後編", truncate_episode_label("第55話後編"))
            test.assertEqual("[第71話 abcdefg…](<https://example.com/71>)", format_discord_link("第71話 abcdefghijk", "https://example.com/71"))
            test.assertEqual(
                "第71話 abcdefg…（次回更新予定 3/15）",
                latest_display_label_for_snapshot(
                    {
                        "episode_title": "第71話 abcdefghijk",
                        "next_update_label": "次回更新予定 3/15",
                    },
                    truncate_episode=True,
                ),
            )

        cases = [
            ("watchlist_order_ignores_disabled_and_orphans", run_watchlist_order_ignores_disabled_and_orphans),
            ("excludes_hidden_entries", run_excludes_hidden_entries),
            ("empty_message_when_all_works_unfetched", run_empty_message_when_all_works_are_unfetched),
            ("unfetched_rows_mixed_with_saved_results", run_unfetched_rows_when_mixed_with_saved_results),
            ("saved_next_update_label", run_saved_next_update_label),
            ("plain_text_and_fallback_labels_without_url", run_plain_text_and_fallback_labels_without_url),
            ("stale_saved_data_warning", run_stale_saved_data_warning),
            ("episode_label_truncation_spec_examples", run_episode_label_truncation_spec_examples),
        ]
        for case, run in cases:
            with self.subTest(case=case):
                run(self)

    def test_handle_latest_query_is_read_only_and_uses_only_injected_loaders(self):
        watchlist = self.make_watchlist(
            [
                {
                    "id": "work-1",
                    "source": "comic-walker",
                    "seed_url": "https://example.com/work-1",
                    "enabled": True,
                    "notification_policy": {"mode": "all", "allowed_update_types": None},
                }
            ]
        )
        state = self.make_state(
            {
                "work-1": {
                    "latest": {
                        "series_title": "作品A",
                        "episode_code": "ep-2",
                        "url": "https://example.com/2",
                    },
                    "history": [],
                    "health": {"consecutive_failures": 0},
                }
            },
            last_run_at=1_700_000_000,
        )
        tempdir, watchlist_path, state_path = self.write_payloads(watchlist, state)
        self.addCleanup(tempdir.cleanup)
        before_watchlist = watchlist_path.read_text(encoding="utf-8")
        before_state = state_path.read_text(encoding="utf-8")
        expected_timestamp = datetime.fromtimestamp(1_700_000_000, tz=ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S %Z")
        calls = {"watchlist": 0, "state": 0}

        def watchlist_loader(path):
            calls["watchlist"] += 1
            self.assertEqual(str(watchlist_path), path)
            return json.loads(before_watchlist)

        def state_loader(path):
            calls["state"] += 1
            self.assertEqual(str(state_path), path)
            return json.loads(before_state)

        response = handle_latest_query(
            "latest",
            watchlist_path=str(watchlist_path),
            state_path=str(state_path),
            timezone_name="Asia/Tokyo",
            watchlist_loader=watchlist_loader,
            state_loader=state_loader,
        )

        self.assertEqual(before_watchlist, watchlist_path.read_text(encoding="utf-8"))
        self.assertEqual(before_state, state_path.read_text(encoding="utf-8"))
        self.assertEqual({"watchlist": 1, "state": 1}, calls)
        self.assertIn(f"最終巡回: {expected_timestamp}", response)
        self.assertIn("[ep-2](<https://example.com/2>)　作品A", response)


if __name__ == "__main__":
    unittest.main()
