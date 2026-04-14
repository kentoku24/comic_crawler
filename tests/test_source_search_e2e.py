import os
import unittest
from pathlib import Path

from manga_watch.discord_supertwins_search import SUPERTWINS_SEARCH_WORK_SELECT, SearchSupertwinsCommandHandler
from manga_watch.source_search import RequestsHttpClient, search_source
from tests.test_discord_supertwins import write_json


RUN_REAL_SEARCH_E2E = os.environ.get("RUN_REAL_SEARCH_E2E") == "1"

REPRESENTATIVE_SEARCH_CASES = (
    {
        "source": "comic-action",
        "query": "ダンジョンの中のひと",
        "expected_title": "ダンジョンの中のひと",
        "expected_seed_url": "https://comic-action.com/rss/series/13933686331663374228",
    },
    {
        "source": "magapoke",
        "query": "薫る花は凛と咲く",
        "expected_title": "薫る花は凛と咲く",
        "expected_seed_url": "https://pocket.shonenmagazine.com/title/01524",
    },
)


@unittest.skipUnless(RUN_REAL_SEARCH_E2E, "set RUN_REAL_SEARCH_E2E=1 to run real network search e2e tests")
class SourceSearchE2ETests(unittest.TestCase):
    def test_real_search_source_includes_takecomic_representative_series(self):
        client = RequestsHttpClient()

        results = search_source("takecomic", "異世界の常識は難しい", http_client=client)

        self.assertTrue(
            any(
                result.title == "異世界の常識は難しい～希少で最弱な人族に転生したけど物理以外で最強になりそうです～"
                and result.seed_url == "https://takecomic.jp/series/bb237f85f48a3"
                for result in results
            ),
            msg=str(results),
        )

    def test_real_search_source_requests_include_expected_media_for_representative_titles(self):
        client = RequestsHttpClient()

        for case in REPRESENTATIVE_SEARCH_CASES:
            with self.subTest(source=case["source"], query=case["query"]):
                results = search_source(case["source"], case["query"], http_client=client)
                self.assertTrue(
                    any(
                        result.title == case["expected_title"]
                        and result.seed_url == case["expected_seed_url"]
                        for result in results
                    ),
                    msg=str(results),
                )

        nicovideo_results = search_source("nicovideo-manga", "ダンジョンの中のひと", http_client=client)
        gaugau_results = search_source("gaugau", "ダンジョンの中のひと", http_client=client)
        sunday_webry_results = search_source("sunday-webry", "尾守つみきと奇日常。", http_client=client)
        self.assertTrue(
            any(result.seed_url == "https://manga.nicovideo.jp/comic/53764" for result in nicovideo_results),
            msg=str(nicovideo_results),
        )
        self.assertTrue(
            any(
                result.seed_url == "https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000"
                for result in gaugau_results
            )
        )
        self.assertTrue(
            any(
                result.title == "尾守つみきと奇日常。"
                and result.seed_url == "https://www.sunday-webry.com/episode/14079602755299850599"
                for result in sunday_webry_results
            ),
            msg=str(sunday_webry_results),
        )
        self.assertFalse(
            any(result.title in {"1話を読む", "最新話を読む"} for result in sunday_webry_results),
            msg=str(sunday_webry_results),
        )

    def test_real_firecross_search_requests_include_haihara_kun_no_tsurukute_seishun_new_game(self):
        client = RequestsHttpClient()

        firecross_results = search_source("firecross", "灰原くん", http_client=client)

        self.assertTrue(
            any(
                result.title == "灰原くんの強くて青春ニューゲーム"
                and result.seed_url == "https://firecross.jp/ebook/series/441"
                for result in firecross_results
            ),
            msg=str(firecross_results),
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
        option_sources = {option["description"] for option in options}
        self.assertTrue({"comic-action", "magapoke", "nicovideo-manga"}.issubset(option_sources), msg=str(options))


if __name__ == "__main__":
    unittest.main()
