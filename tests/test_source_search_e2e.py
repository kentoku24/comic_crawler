import os
import unittest
from pathlib import Path

from manga_watch.discord_supertwins_search import SUPERTWINS_SEARCH_WORK_SELECT, SearchSupertwinsCommandHandler
from manga_watch.source_search import RequestsHttpClient, search_source
from tests.test_discord_supertwins import write_json


RUN_REAL_SEARCH_E2E = os.environ.get("RUN_REAL_SEARCH_E2E") == "1"


@unittest.skipUnless(RUN_REAL_SEARCH_E2E, "set RUN_REAL_SEARCH_E2E=1 to run real network search e2e tests")
class SourceSearchE2ETests(unittest.TestCase):
    def test_real_search_source_requests_reach_expected_work_for_shonenjumpplus_spy_family(self):
        client = RequestsHttpClient()
        results = search_source("shonenjumpplus", "SPY×FAMILY", http_client=client)

        self.assertTrue(results, msg="shonenjumpplus returned no results for SPY×FAMILY")
        self.assertTrue(
            any(
                result.title == "SPY×FAMILY"
                and result.seed_url == "https://shonenjumpplus.com/episode/17107419589372003740"
                for result in results
            ),
            msg=str(results),
        )

    def test_real_search_source_requests_reach_expected_works_for_recognized_media_title_pairs(self):
        client = RequestsHttpClient()
        cases = [
            (
                "shonenjumpplus",
                "SPY×FAMILY",
                "SPY×FAMILY",
                "https://shonenjumpplus.com/episode/17107419589372003740",
            ),
            (
                "champion-cross",
                "僕の心のヤバイやつ",
                "僕の心のヤバイやつ",
                "https://championcross.jp/series/899dda204c3f2",
            ),
        ]

        for source, query, expected_title, expected_seed_url in cases:
            with self.subTest(source=source):
                results = search_source(source, query, http_client=client)
                self.assertTrue(results, msg=f"{source} returned no results for {query}")
                self.assertTrue(
                    any(
                        result.title == expected_title and result.seed_url == expected_seed_url
                        for result in results
                    ),
                    msg=str(results),
                )

    def test_real_search_source_requests_include_expected_media_for_dungeon_no_naka_no_hito(self):
        client = RequestsHttpClient()

        comic_action_results = search_source("comic-action", "ダンジョンの中のひと", http_client=client)
        nicovideo_results = search_source("nicovideo-manga", "ダンジョンの中のひと", http_client=client)
        gaugau_results = search_source("gaugau", "ダンジョンの中のひと", http_client=client)

        self.assertTrue(
            any(
                result.seed_url == "https://comic-action.com/rss/series/13933686331663374228"
                for result in comic_action_results
            )
        )
        self.assertTrue(
            any(result.seed_url == "https://manga.nicovideo.jp/comic/53764" for result in nicovideo_results),
            msg=str(nicovideo_results),
        )
        self.assertTrue(
            any(
                result.title == "ダンジョンの中のひと"
                and result.seed_url == "https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000"
                for result in gaugau_results
            )
        )

    def test_real_supertwins_search_handler_includes_three_target_media(self):
        root = Path(os.environ.get("TMPDIR", "/tmp"))
        watchlist_path = root / "issue-268-search-watchlist.json"
        state_path = root / "issue-268-search-state.json"
        write_json(
            watchlist_path,
            {
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
            },
        )
        write_json(
            state_path,
            {
                "version": 2,
                "works": {
                    "root-1": {
                        "latest": {"series_title": "ダンジョンの中のひと", "episode_title": "第1話"},
                        "history": [],
                        "unread": {"event_ids": []},
                        "health": {},
                    }
                },
                "last_run_at": None,
                "notification_outbox": [],
                "discord_delivery": {"daily_notification": {"delivered_latest_keys": {}, "pending_messages": []}},
                "supertwins": {"groups": {}},
            },
        )

        try:
            payload = SearchSupertwinsCommandHandler().handle_component(
                {"custom_id": SUPERTWINS_SEARCH_WORK_SELECT, "values": ["root-1"]},
                watchlist_path=str(watchlist_path),
                state_path=str(state_path),
            )
        finally:
            watchlist_path.unlink(missing_ok=True)
            state_path.unlink(missing_ok=True)

        options = payload["components"][0]["components"][0]["options"]
        labels_by_source = {}
        for option in options:
            source = option.get("description")
            label = option.get("label")
            if source not in labels_by_source:
                labels_by_source[source] = []
            labels_by_source[source].append(label)

        for source in ("comic-action", "nicovideo-manga", "gaugau"):
            self.assertIn(source, labels_by_source, msg=str(options))
            self.assertIn("ダンジョンの中のひと", labels_by_source[source], msg=str(options))


if __name__ == "__main__":
    unittest.main()
