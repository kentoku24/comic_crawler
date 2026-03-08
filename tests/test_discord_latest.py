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

    def test_build_latest_query_response_uses_watchlist_order_and_ignores_disabled_and_orphans(self):
        watchlist = self.make_watchlist(
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
        state = self.make_state(
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

        self.assertEqual("現在のリスト:", lines[2])
        self.assertEqual("[第8話](<https://example.com/b>)　作品B", lines[3])
        self.assertEqual("[第1話](<https://example.com/a>)　作品A", lines[4])
        self.assertNotIn("作品C", response)
        self.assertNotIn("孤児", response)

    def test_build_latest_query_response_returns_empty_message_when_all_works_are_unfetched(self):
        watchlist = self.make_watchlist(
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
        state = self.make_state(
            {
                "work-1": {"latest": {}, "history": [], "health": {"consecutive_failures": 0}},
                "work-2": {"latest": {}, "history": [], "health": {"consecutive_failures": 0}},
            }
        )

        response = build_latest_query_response(watchlist, state, timezone_name="Asia/Tokyo")

        self.assertIn("最終巡回: まだ実行されていません", response)
        self.assertTrue(response.endswith(EMPTY_LINE))
        self.assertNotIn("（未取得）", response)

    def test_build_latest_query_response_includes_unfetched_rows_when_mixed_with_saved_results(self):
        watchlist = self.make_watchlist(
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
        state = self.make_state(
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

        self.assertIn("[第71話 abcdefg…](<https://example.com/71>)　作品A", response)
        self.assertIn("（未取得）　work-2", response)
        self.assertTrue(response.endswith(PARTIAL_FAILURE_WARNING))

    def test_build_latest_query_response_appends_saved_next_update_label(self):
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

        self.assertIn(
            "[第2話（次回更新予定 3/15）](<https://example.com/2>)　作品A",
            response,
        )

    def test_episode_label_truncation_matches_spec_examples(self):
        self.assertEqual("第71話 abcdefg…", truncate_episode_label("第71話 abcdefghijk"))
        self.assertEqual("第71話 あいうえおかき…", truncate_episode_label("第71話 あいうえおかきくけ"))
        self.assertEqual("第71話 abあいうcd…", truncate_episode_label("第71話 abあいうcdef"))
        self.assertEqual("abcdefghijklmnopqrs…", truncate_episode_label("abcdefghijklmnopqrstu"))
        self.assertEqual("第55話後編", truncate_episode_label("第55話後編"))
        self.assertEqual("[第71話 abcdefg…](<https://example.com/71>)", format_discord_link("第71話 abcdefghijk", "https://example.com/71"))
        self.assertEqual(
            "第71話 abcdefg…（次回更新予定 3/15）",
            latest_display_label_for_snapshot(
                {
                    "episode_title": "第71話 abcdefghijk",
                    "next_update_label": "次回更新予定 3/15",
                },
                truncate_episode=True,
            ),
        )

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
