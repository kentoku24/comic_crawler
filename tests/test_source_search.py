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
    def test_supported_search_sources_excludes_only_comic_walker(self):
        self.assertEqual(
            (
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

    def test_search_source_rejects_unknown_source(self):
        with self.assertRaisesRegex(ValueError, "unsupported search source"):
            search_source("unknown", "まんが", http_client=StaticHttpClient({}))


if __name__ == "__main__":
    unittest.main()
