import unittest

from manga_watch.source_search import SearchResult, search_source, supported_search_sources


class StaticHttpClient:
    def __init__(self, responses):
        self.responses = dict(responses)

    def get_text(self, url: str) -> str:
        if url not in self.responses:
            raise AssertionError(f"unexpected request: {url!r}")
        return self.responses[url]


class SourceSearchTests(unittest.TestCase):
    def test_supported_search_sources_match_registered_sources(self):
        self.assertEqual(
            ("comic-walker", "comic-action", "champion-cross", "kakuyomu", "nicovideo-manga"),
            supported_search_sources(),
        )

    def test_search_source_parses_comic_walker_results(self):
        html = """
        <html>
          <body>
            <a title="魔術師クノンは見えている" href="/detail/KC_003921_S/episodes/KC_0039210000100011_E">
              魔術師クノンは見えている
            </a>
          </body>
        </html>
        """

        results = search_source(
            "comic-walker",
            "クノン",
            http_client=StaticHttpClient({"https://comic-walker.com/search?keyword=%E3%82%AF%E3%83%8E%E3%83%B3": html}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="comic-walker",
                    title="魔術師クノンは見えている",
                    seed_url="https://comic-walker.com/detail/KC_003921_S",
                    subtitle="comic-walker",
                )
            ],
            results,
        )

    def test_search_source_parses_comic_action_results(self):
        html = """
        <html>
          <body>
            <a href="https://comic-action.com/episode/11341664176570134078">
              <img alt="ダンジョンの中のひと" />
            </a>
          </body>
        </html>
        """

        results = search_source(
            "comic-action",
            "ダンジョンの中のひと",
            http_client=StaticHttpClient(
                {"https://comic-action.com/search?q=%E3%83%80%E3%83%B3%E3%82%B8%E3%83%A7%E3%83%B3%E3%81%AE%E4%B8%AD%E3%81%AE%E3%81%B2%E3%81%A8": html}
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="comic-action",
                    title="ダンジョンの中のひと",
                    seed_url="https://comic-action.com/episode/11341664176570134078",
                    subtitle="comic-action",
                )
            ],
            results,
        )

    def test_search_source_parses_champion_cross_results(self):
        html = """
        <html>
          <body>
            <a href="/series/e349a3791821b/?keyword=%E3%81%BE%E3%82%93%E3%81%8C">酒井美羽の少女まんが戦記</a>
          </body>
        </html>
        """

        results = search_source(
            "champion-cross",
            "まんが",
            http_client=StaticHttpClient({"https://championcross.jp/search?keyword=%E3%81%BE%E3%82%93%E3%81%8C": html}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="champion-cross",
                    title="酒井美羽の少女まんが戦記",
                    seed_url="https://championcross.jp/series/e349a3791821b",
                    subtitle="champion-cross",
                )
            ],
            results,
        )

    def test_search_source_parses_kakuyomu_results(self):
        html = """
        <html>
          <body>
            <a title="雉はどっちだ" href="/works/822139840410356917/episodes/1">雉はどっちだ</a>
          </body>
        </html>
        """

        results = search_source(
            "kakuyomu",
            "まんが",
            http_client=StaticHttpClient({"https://kakuyomu.jp/search?q=%E3%81%BE%E3%82%93%E3%81%8C": html}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="kakuyomu",
                    title="雉はどっちだ",
                    seed_url="https://kakuyomu.jp/works/822139840410356917/episodes/1",
                    subtitle="kakuyomu",
                )
            ],
            results,
        )

    def test_search_source_parses_nicovideo_manga_results(self):
        html = """
        <html>
          <body>
            <div class="search_result">
              <div class="search_result__item">
                <div class="search_result__item__thumbnail">
                  <a href="/comic/53764?track=keyword_search">
                    <img alt="ダンジョンの中のひと" />
                  </a>
                </div>
                <div class="search_result__item__info">
                  <div class="search_result__item__info--title">
                    <a href="/comic/53764?track=keyword_search">ダンジョンの中のひと</a>
                  </div>
                </div>
              </div>
            </div>
          </body>
        </html>
        """

        results = search_source(
            "nicovideo-manga",
            "ダンジョンの中のひと",
            http_client=StaticHttpClient(
                {
                    "https://manga.nicovideo.jp/search?q=%E3%83%80%E3%83%B3%E3%82%B8%E3%83%A7%E3%83%B3%E3%81%AE%E4%B8%AD%E3%81%AE%E3%81%B2%E3%81%A8": html
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="nicovideo-manga",
                    title="ダンジョンの中のひと",
                    seed_url="https://manga.nicovideo.jp/comic/53764",
                    subtitle="nicovideo-manga",
                )
            ],
            results,
        )

    def test_search_source_rejects_unknown_source(self):
        with self.assertRaisesRegex(ValueError, "unsupported search source"):
            search_source("unknown", "まんが", http_client=StaticHttpClient({}))


if __name__ == "__main__":
    unittest.main()
