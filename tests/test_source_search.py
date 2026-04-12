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
            (
                "comic-walker",
                "comic-action",
                "comic-earthstar",
                "comicborder",
                "comic-trail",
                "kuragebunch",
                "shonenjumpplus",
                "sunday-webry",
                "champion-cross",
                "magapoke",
                "firecross",
                "takecomic",
                "nicovideo-manga",
                "kakuyomu",
            ),
            supported_search_sources(),
        )

    def test_search_source_parses_site_results_and_normalizes_seed_url(self):
        html = """
        <html><body>
          <a href="/works/822139840410356917/episodes/1" title="雉はどっちだ">ignored body</a>
          <a href="https://example.com/ignore">ignored</a>
        </body></html>
        """
        request_url = "https://kakuyomu.jp/search?q=%E3%81%BE%E3%82%93%E3%81%8C"

        results = search_source(
            "kakuyomu",
            "まんが",
            http_client=StaticHttpClient({request_url: html}),
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

    def test_search_source_resolves_non_root_relative_result_urls(self):
        html = """
        <html><body>
          <a href="works/822139840410356917/episodes/1" title="雉はどっちだ">ignored body</a>
        </body></html>
        """
        request_url = "https://kakuyomu.jp/search?q=%E3%81%BE%E3%82%93%E3%81%8C"

        results = search_source(
            "kakuyomu",
            "まんが",
            http_client=StaticHttpClient({request_url: html}),
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

    def test_search_source_uses_image_alt_for_image_only_anchors(self):
        html = """
        <html><body>
          <a href="/series/e349a3791821b/"><img alt="酒井美羽の少女まんが戦記【無料】" src="/cover.jpg" /></a>
        </body></html>
        """
        request_url = "https://championcross.jp/search?keyword=%E3%81%BE%E3%82%93%E3%81%8C"

        results = search_source(
            "champion-cross",
            "まんが",
            http_client=StaticHttpClient({request_url: html}),
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

    def test_search_source_rejects_unknown_source(self):
        with self.assertRaisesRegex(ValueError, "unsupported search source"):
            search_source("unknown", "まんが", http_client=StaticHttpClient({}))


if __name__ == "__main__":
    unittest.main()
