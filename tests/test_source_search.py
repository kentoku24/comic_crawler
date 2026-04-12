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
    def test_supported_search_sources_are_limited_to_the_initial_supported_set(self):
        self.assertEqual(
            (
                "champion-cross",
                "kakuyomu",
                "comic-walker",
                "comic-action",
                "comic-earthstar",
                "comicborder",
                "comic-trail",
                "kuragebunch",
                "shonenjumpplus",
                "sunday-webry",
                "magapoke",
                "firecross",
                "takecomic",
                "nicovideo-manga",
            ),
            supported_search_sources(),
        )

    def test_search_source_parses_champion_cross_results(self):
        html = """
        <html>
          <body>
            <a href="/series/e349a3791821b/?keyword=%E3%81%BE%E3%82%93%E3%81%8C">酒井美羽の少女まんが戦記</a>
            <a href="/series/aaaaaaaaaaaaa/?keyword=%E3%81%BE%E3%82%93%E3%81%8C">別の作品</a>
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
                ),
                SearchResult(
                    source="champion-cross",
                    title="別の作品",
                    seed_url="https://championcross.jp/series/aaaaaaaaaaaaa",
                    subtitle="champion-cross",
                ),
            ],
            results,
        )

    def test_search_source_parses_kakuyomu_results(self):
        html = """
        <html>
          <body>
            <a title="雉はどっちだ" href="/works/822139840410356917">雉はどっちだ</a>
            <a title="別作品" href="/works/900000000000000000">別作品</a>
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
                    seed_url="https://kakuyomu.jp/works/822139840410356917",
                    subtitle="kakuyomu",
                ),
                SearchResult(
                    source="kakuyomu",
                    title="別作品",
                    seed_url="https://kakuyomu.jp/works/900000000000000000",
                    subtitle="kakuyomu",
                ),
            ],
            results,
        )


    def test_search_source_parses_comic_walker_results(self):
        html = """
        <html>
          <body>
            <a title="忍者と極道" href="/detail/KC_005419_S?episodeType=latest">忍者と極道</a>
            <a title="別作品" href="/detail/KC_999999_S">別作品</a>
          </body>
        </html>
        """

        results = search_source(
            "comic-walker",
            "忍者",
            http_client=StaticHttpClient({"https://comic-walker.com/search?q=%E5%BF%8D%E8%80%85": html}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="comic-walker",
                    title="忍者と極道",
                    seed_url="https://comic-walker.com/detail/KC_005419_S",
                    subtitle="comic-walker",
                ),
                SearchResult(
                    source="comic-walker",
                    title="別作品",
                    seed_url="https://comic-walker.com/detail/KC_999999_S",
                    subtitle="comic-walker",
                ),
            ],
            results,
        )

    def test_search_source_rejects_unknown_source(self):
        with self.assertRaisesRegex(ValueError, "unsupported search source"):
            search_source("unknown", "まんが", http_client=StaticHttpClient({}))

    def test_search_source_parses_site_index_results_for_unimplemented_source(self):
        html = """
        <html>
          <body>
            <a href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fcomic-action.com%2Fepisode%2F2550912965438754901">私のタイトル</a>
            <a href="https://comic-action.com/episode/2550912965438754902">別タイトル</a>
          </body>
        </html>
        """
        results = search_source(
            "comic-action",
            "タイトル",
            http_client=StaticHttpClient({"https://duckduckgo.com/html/?q=site%3Acomic-action.com%20%E3%82%BF%E3%82%A4%E3%83%88%E3%83%AB": html}),
        )
        self.assertEqual(
            [
                SearchResult(
                    source="comic-action",
                    title="私のタイトル",
                    seed_url="https://comic-action.com/episode/2550912965438754901",
                    subtitle="comic-action",
                ),
                SearchResult(
                    source="comic-action",
                    title="別タイトル",
                    seed_url="https://comic-action.com/episode/2550912965438754902",
                    subtitle="comic-action",
                ),
            ],
            results,
        )


if __name__ == "__main__":
    unittest.main()
