import unittest
from pathlib import Path

from manga_watch.source_search import SearchResult, search_source, supported_search_sources

FIXTURES_ROOT = Path(__file__).parent / "fixtures"


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
                "gaugau",
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

    def test_search_source_parses_comic_action_results_via_q_parameter(self):
        html = """
        <html>
          <body>
            <section>
              <h4>「ダンジョンの中のひと」の検索結果</h4>
              <ul>
                <li class="SearchResultItem_li__u1Vp8">
                  <div>
                    <a href="https://comic-action.com/episode/13933686331665056851">
                      <img
                        alt="ダンジョンの中のひと"
                        src="https://cdn-img.comic-action.com/public/series-thumbnail/13933686331663374228-4e8c11f394783f9b8a20a98d4354d771"
                      />
                    </a>
                  </div>
                  <div class="SearchResultItem_title_box__kqLq3">
                    <p class="SearchResultItem_series_title__hDsk1">ダンジョンの中のひと</p>
                    <p class="SearchResultItem_author__WEU8G">双見酔</p>
                    <a href="https://comic-action.com/episode/13933686331665056851" class="SearchResultItem_main_link__NWMR7">1話を読む</a>
                    <a href="https://comic-action.com/episode/13933686331677886179" class="SearchResultItem_sub_link__ZIGr8">最新話を読む</a>
                  </div>
                </li>
              </ul>
            </section>
          </body>
        </html>
        """

        results = search_source(
            "comic-action",
            "ダンジョンの中のひと",
            http_client=StaticHttpClient(
                {
                    "https://comic-action.com/search?q=%E3%83%80%E3%83%B3%E3%82%B8%E3%83%A7%E3%83%B3%E3%81%AE%E4%B8%AD%E3%81%AE%E3%81%B2%E3%81%A8": html
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="comic-action",
                    title="ダンジョンの中のひと",
                    seed_url="https://comic-action.com/rss/series/13933686331663374228",
                    subtitle="comic-action",
                )
            ],
            results,
        )

    def test_search_source_parses_comic_action_latest_link_when_attributes_are_reordered(self):
        html = """
        <html>
          <body>
            <section>
              <ul>
                <li class="SearchResultItem_li__u1Vp8">
                  <div>
                    <a href="https://comic-action.com/episode/13933686331665056851">
                      <img alt="ダンジョンの中のひと" />
                    </a>
                  </div>
                  <div class="SearchResultItem_title_box__kqLq3">
                    <p class="SearchResultItem_series_title__hDsk1">ダンジョンの中のひと</p>
                    <a class="SearchResultItem_sub_link__ZIGr8" href="https://comic-action.com/episode/13933686331677886179">
                      最新話を読む
                    </a>
                  </div>
                </li>
              </ul>
            </section>
          </body>
        </html>
        """

        results = search_source(
            "comic-action",
            "ダンジョンの中のひと",
            http_client=StaticHttpClient(
                {
                    "https://comic-action.com/search?q=%E3%83%80%E3%83%B3%E3%82%B8%E3%83%A7%E3%83%B3%E3%81%AE%E4%B8%AD%E3%81%AE%E3%81%B2%E3%81%A8": html
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="comic-action",
                    title="ダンジョンの中のひと",
                    seed_url="https://comic-action.com/episode/13933686331677886179",
                    subtitle="comic-action",
                )
            ],
            results,
        )

    def test_search_source_parses_nicovideo_manga_results_via_q_parameter(self):
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

    def test_search_source_parses_magapoke_results_via_query_parameter(self):
        html = (FIXTURES_ROOT / "magapoke" / "search" / "01-search.html").read_text(encoding="utf-8")
        request_url = "https://pocket.shonenmagazine.com/search/%E8%96%AB%E3%82%8B%E8%8A%B1%E3%81%AF%E5%87%9B%E3%81%A8%E5%92%B2%E3%81%8F"

        results = search_source(
            "magapoke",
            "薫る花は凛と咲く",
            http_client=StaticHttpClient({request_url: html}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="magapoke",
                    title="薫る花は凛と咲く",
                    seed_url="https://pocket.shonenmagazine.com/title/01524",
                    subtitle="magapoke",
                )
            ],
            results,
        )

    def test_search_source_parses_gaugau_results(self):
        html = """
        <html>
          <body>
            <div class="works__list">
              <div class="works__grid">
                <div class="list__box -free">
                  <a class="thumbnail -youth" href="https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000">
                    <div class="img"><img alt="" /></div>
                  </a>
                  <div class="list__text">
                    <h4>
                      <a href="https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000">ダンジョンの中のひと</a>
                    </h4>
                  </div>
                </div>
              </div>
            </div>
          </body>
        </html>
        """

        results = search_source(
            "gaugau",
            "ダンジョンの中のひと",
            http_client=StaticHttpClient(
                {
                    "https://gaugau.futabanet.jp/list/search-result?word=%E3%83%80%E3%83%B3%E3%82%B8%E3%83%A7%E3%83%B3%E3%81%AE%E4%B8%AD%E3%81%AE%E3%81%B2%E3%81%A8": html
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="gaugau",
                    title="ダンジョンの中のひと",
                    seed_url="https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000",
                    subtitle="gaugau",
                )
            ],
            results,
        )

    def test_search_source_parses_comic_walker_results_via_keyword_parameter(self):
        html = """
        <html>
          <body>
            <a class="WorkThumbnail_link__LWlLk" href="/detail/KC_003921_S/episodes/KC_0039210000100011_E">
              <span class="WorkThumbnail_title__EmZ6E" lang="ja">魔術師クノンは見えている</span>
            </a>
            <a class="WorkThumbnail_link__LWlLk" href="/detail/KC_999999_S/episodes/KC_9999990000100011_E">
              <span class="WorkThumbnail_title__EmZ6E" lang="ja">別作品</span>
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


if __name__ == "__main__":
    unittest.main()
