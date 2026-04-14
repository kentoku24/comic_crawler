import os
import unittest

from manga_watch.source_search import RequestsHttpClient, search_source


RUN_REAL_SEARCH_E2E = os.environ.get("RUN_REAL_SEARCH_E2E") == "1"


@unittest.skipUnless(RUN_REAL_SEARCH_E2E, "set RUN_REAL_SEARCH_E2E=1 to run real network search e2e tests")
class SourceSearchE2ETests(unittest.TestCase):
    def test_real_nicovideo_search_hits_dungeon_no_naka_no_hito(self):
        client = RequestsHttpClient()
        results = search_source("nicovideo-manga", "ダンジョンの中のひと", http_client=client)

        self.assertTrue(
            any(
                result.title == "ダンジョンの中のひと"
                and result.seed_url == "https://manga.nicovideo.jp/comic/53764"
                for result in results
            ),
            msg=str(results),
        )


if __name__ == "__main__":
    unittest.main()
