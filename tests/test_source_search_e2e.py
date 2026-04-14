import os
import unittest
from pathlib import Path

from manga_watch.discord_supertwins_search import SUPERTWINS_SEARCH_WORK_SELECT, SearchSupertwinsCommandHandler
from manga_watch.source_search import RequestsHttpClient, search_source
from tests.test_discord_supertwins import write_json


RUN_REAL_SEARCH_E2E = os.environ.get("RUN_REAL_SEARCH_E2E") == "1"


@unittest.skipUnless(RUN_REAL_SEARCH_E2E, "set RUN_REAL_SEARCH_E2E=1 to run real network search e2e tests")
class SourceSearchE2ETests(unittest.TestCase):
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
                result.seed_url == "https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000"
                for result in gaugau_results
            )
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
        self.assertTrue({"comic-action", "nicovideo-manga", "gaugau"}.issubset(option_sources), msg=str(options))


if __name__ == "__main__":
    unittest.main()
