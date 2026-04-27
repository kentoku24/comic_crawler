import unittest
from pathlib import Path
from urllib.parse import quote_plus

from manga_watch.source_search import SearchResult, search_source, supported_search_sources

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "source-search"


class StaticHttpClient:
    def __init__(self, responses):
        self.responses = dict(responses)

    def get_text(self, url: str) -> str:
        if url not in self.responses:
            raise AssertionError(f"unexpected request: {url!r}")
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


class SourceSearchTests(unittest.TestCase):
    def test_search_source_parses_takecomic_results_and_strips_update_label(self):
        query = "異世界の常識は難しい"
        request_url = f"https://takecomic.jp/search?keyword={quote_plus(query)}"
        html = (
            Path(__file__).parent
            / "fixtures"
            / "source_search"
            / "takecomic_search_update_label.html"
        ).read_text(encoding="utf-8")

        results = search_source(
            "takecomic",
            query,
            http_client=StaticHttpClient({request_url: html}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="takecomic",
                    title="異世界の常識は難しい～希少で最弱な人族に転生したけど物理以外で最強になりそうです～",
                    seed_url="https://takecomic.jp/series/bb237f85f48a3",
                    subtitle="takecomic",
                )
            ],
            results,
        )

    def test_search_source_falls_back_to_canonical_url_when_takecomic_title_is_only_badge(self):
        query = "takecomic badge only"
        request_url = f"https://takecomic.jp/search?keyword={quote_plus(query)}"
        html = """
        <html><body>
          <a class="series-list-item-link" href="/series/bb237f85f48a3">
            <div class="g-updated-mark-wrap">
              <div class="g-updated-mark">更新</div>
            </div>
          </a>
        </body></html>
        """

        results = search_source(
            "takecomic",
            query,
            http_client=StaticHttpClient({request_url: html}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="takecomic",
                    title="https://takecomic.jp/series/bb237f85f48a3",
                    seed_url="https://takecomic.jp/series/bb237f85f48a3",
                    subtitle="takecomic",
                )
            ],
            results,
        )

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
                "piccoma",
                "bookwalker",
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

    def test_search_source_prefers_champion_cross_series_card_over_noise_links(self):
        html = """
        <html>
          <body>
            <div class="incremental-suggestion-panel">
              <a class="incremental-result-item x-incremental-result-anchor" href="/championcross/series/4756324e1c1b1/?keyword=%E7%B9%94%E6%B4%A5%E6%B1%9F%E5%A4%A7%E5%BF%97">
                火曜更新
              </a>
            </div>
            <div class="series-list">
              <div class="manga-store-item">
                <a class="c-ms-clk-article c-ms-mode-series click-link" href="https://championcross.jp/series/4756324e1c1b1">
                  <div class="manga-title-box">
                    <h2 class="manga-title">織津江大志の異世界クリ娘サバイバル日誌</h2>
                  </div>
                </a>
              </div>
            </div>
          </body>
        </html>
        """

        results = search_source(
            "champion-cross",
            "織津江大志",
            http_client=StaticHttpClient(
                {"https://championcross.jp/search?keyword=%E7%B9%94%E6%B4%A5%E6%B1%9F%E5%A4%A7%E5%BF%97": html}
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="champion-cross",
                    title="織津江大志の異世界クリ娘サバイバル日誌",
                    seed_url="https://championcross.jp/series/4756324e1c1b1",
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

    def test_search_source_parses_comic_earthstar_results_via_q_parameter(self):
        html = """
        <html>
          <body>
            <section>
              <h4 class="SearchResult_bold_title__xPHvc">「俺は全てを【パリイ】する」の検索結果</h4>
              <ul class="SearchResult_search_result_list__XKa5L">
                <li class="SearchResultItem_li__u1Vp8">
                  <div>
                    <a href="https://comic-earthstar.com/episode/14079602755509014909">
                      <img
                        alt="俺は全てを【パリイ】する　～逆勘違いの世界最強は冒険者の夢をみる～"
                        src="https://cdn-img.comic-earthstar.com/public/series-thumbnail/14079602755508978459-f5ccb81402690f486c14edf241e4b0db?1774260578"
                      />
                    </a>
                  </div>
                  <div class="SearchResultItem_title_box__kqLq3">
                    <p class="SearchResultItem_series_title__hDsk1">俺は全てを【パリイ】する　～逆勘違いの世界最強は冒険者の夢をみる～</p>
                    <p class="SearchResultItem_author__WEU8G">漫画：KRSG/原作：鍋敷・カワグチ</p>
                    <a href="https://comic-earthstar.com/episode/14079602755509014909" class="SearchResultItem_main_link__NWMR7">1話を読む</a>
                    <a href="https://comic-earthstar.com/episode/2551460909735889958" class="SearchResultItem_sub_link__ZIGr8">最新話を読む</a>
                  </div>
                </li>
              </ul>
            </section>
          </body>
        </html>
        """

        results = search_source(
            "comic-earthstar",
            "俺は全てを【パリイ】する",
            http_client=StaticHttpClient(
                {
                    "https://comic-earthstar.com/search?q=%E4%BF%BA%E3%81%AF%E5%85%A8%E3%81%A6%E3%82%92%E3%80%90%E3%83%91%E3%83%AA%E3%82%A4%E3%80%91%E3%81%99%E3%82%8B": html,
                    "https://comic-earthstar.com/episode/14079602755509014909": """
                    <html>
                      <head>
                        <link rel="alternate" type="application/rss+xml" href="https://comic-earthstar.com/rss/series/14079602755508978459">
                      </head>
                      <body>
                        <div data-gtm-data-layer="{&quot;episode&quot;:{&quot;series_id&quot;:&quot;14079602755508978459&quot;}}"></div>
                      </body>
                    </html>
                    """,
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="comic-earthstar",
                    title="俺は全てを【パリイ】する ～逆勘違いの世界最強は冒険者の夢をみる～",
                    seed_url="https://comic-earthstar.com/rss/series/14079602755508978459",
                    subtitle="comic-earthstar",
                )
            ],
            results,
        )

    def test_search_source_parses_kuragebunch_results_via_q_parameter(self):
        html = (FIXTURES_ROOT / "kuragebunch" / "01-search.html").read_text(encoding="utf-8")
        request_url = f"https://kuragebunch.com/search?q={quote_plus('今日から始める幼なじみ')}"

        results = search_source(
            "kuragebunch",
            "今日から始める幼なじみ",
            http_client=StaticHttpClient({request_url: html}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="kuragebunch",
                    title="今日から始める幼なじみ",
                    seed_url="https://kuragebunch.com/episode/3269632237305143755",
                    subtitle="kuragebunch",
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
        html = (FIXTURES_ROOT / "magapoke" / "01-search.html").read_text(encoding="utf-8")
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

    def test_search_source_percent_encodes_magapoke_queries_with_spaces(self):
        html = (FIXTURES_ROOT / "magapoke" / "01-search.html").read_text(encoding="utf-8")
        request_url = "https://pocket.shonenmagazine.com/search/Foo%20Bar"

        results = search_source(
            "magapoke",
            "Foo Bar",
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

    def test_search_source_parses_bookwalker_series_results(self):
        html = """
        <html>
          <body>
            <ul class="m-tile-list">
              <li class="m-tile">
                <div class="m-book-item">
                  <a href="https://bookwalker.jp/series/519222/list/"
                     class="m-thumb__image"
                     data-series-id="519222">
                    <img alt="くまぐらし（MANGAバル コミックス）" />
                  </a>
                  <p class="m-book-item__title">
                    <a href="https://bookwalker.jp/series/519222/list/"
                       class="m-book-item__title"
                       title="くまぐらし（MANGAバル コミックス）">くまぐらし（MANGAバル コミックス）</a>
                  </p>
                  <a href="https://bookwalker.jp/de893cb2ba-dc87-4c1b-90cb-a1cd13d33a0f/"
                     data-action-label="最新巻を見る">最新刊を見る</a>
                </div>
              </li>
            </ul>
          </body>
        </html>
        """

        results = search_source(
            "bookwalker",
            "くまぐらし",
            http_client=StaticHttpClient(
                {"https://bookwalker.jp/search/?word=%E3%81%8F%E3%81%BE%E3%81%90%E3%82%89%E3%81%97&order=score": html}
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="bookwalker",
                    title="くまぐらし（MANGAバル コミックス）",
                    seed_url="https://bookwalker.jp/series/519222/list/",
                    subtitle="bookwalker",
                )
            ],
            results,
        )

    def test_search_source_uses_bookwalker_image_alt_when_title_anchor_is_absent(self):
        html = """
        <html>
          <body>
            <ul class="m-tile-list">
              <li class="m-tile">
                <div class="m-book-item">
                  <img alt="くまぐらし（MANGAバル コミックス）" />
                  <a href="https://bookwalker.jp/series/519222/list/"
                     class="m-book-item__title"></a>
                </div>
              </li>
            </ul>
          </body>
        </html>
        """

        results = search_source(
            "bookwalker",
            "くまぐらし",
            http_client=StaticHttpClient(
                {"https://bookwalker.jp/search/?word=%E3%81%8F%E3%81%BE%E3%81%90%E3%82%89%E3%81%97&order=score": html}
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="bookwalker",
                    title="くまぐらし（MANGAバル コミックス）",
                    seed_url="https://bookwalker.jp/series/519222/list/",
                    subtitle="bookwalker",
                )
            ],
            results,
        )

    def test_search_source_prefers_gaugau_series_heading_over_badge_inside_thumbnail_anchor(self):
        html = """
        <html>
          <body>
            <div class="works__list">
              <div class="works__grid">
                <div class="list__box -free">
                  <a class="thumbnail -youth" href="https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000">
                    <div class="img"><img alt="" /></div>
                    <p class="thumbnail__badge">無料コミック 3/27 更新</p>
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

    def test_search_source_parses_piccoma_json_results(self):
        query = "九条の大罪"
        request_url = (
            "https://piccoma.com/web/search/result_ajax/list"
            f"?tab_type=T&word={quote_plus(query)}&page=1"
        )
        json_text = (FIXTURES_ROOT / "piccoma" / "01-search.json").read_text(encoding="utf-8")

        results = search_source(
            "piccoma",
            query,
            http_client=StaticHttpClient({request_url: json_text}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="piccoma",
                    title="九条の大罪",
                    seed_url="https://piccoma.com/web/product/58170?etype=episode",
                    subtitle="piccoma",
                ),
                SearchResult(
                    source="piccoma",
                    title="闇金ウシジマくん",
                    seed_url="https://piccoma.com/web/product/12345?etype=episode",
                    subtitle="piccoma",
                ),
            ],
            results,
        )

    def test_search_source_piccoma_ignores_malformed_rows(self):
        query = "九条の大罪"
        request_url = (
            "https://piccoma.com/web/search/result_ajax/list"
            f"?tab_type=T&word={quote_plus(query)}&page=1"
        )
        json_text = """
        {
          "status": 0,
          "products": [
            {"id": 58170},
            {"id": "abc", "title": "bad id"},
            {"title": "missing id"},
            null,
            "bad row",
            {"id": 58170, "title": "九条の大罪"},
            {"id": 58170, "title": "duplicate"}
          ]
        }
        """

        results = search_source(
            "piccoma",
            query,
            http_client=StaticHttpClient({request_url: json_text}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="piccoma",
                    title="九条の大罪",
                    seed_url="https://piccoma.com/web/product/58170?etype=episode",
                    subtitle="piccoma",
                )
            ],
            results,
        )

    def test_search_source_piccoma_returns_empty_for_empty_or_malformed_products(self):
        query = "九条の大罪"
        request_url = (
            "https://piccoma.com/web/search/result_ajax/list"
            f"?tab_type=T&word={quote_plus(query)}&page=1"
        )

        for json_text in (
            '{"status": 0, "products": []}',
            '{"status": 0, "products": {}}',
            '{"status": 1, "products": [{"id": 58170, "title": "九条の大罪"}]}',
            '{"status": 0}',
            'not json',
        ):
            with self.subTest(json_text=json_text):
                results = search_source(
                    "piccoma",
                    query,
                    http_client=StaticHttpClient({request_url: json_text}),
                )

                self.assertEqual([], results)

    def test_search_source_falls_back_to_comicborder_homepage_results_when_search_errors(self):
        homepage_html = """
        <html><body>
          <a href="/episode/12207421983382919118">NEW! 殺っちゃえ!! 宇喜多さん</a>
        </body></html>
        """

        results = search_source(
            "comicborder",
            "殺っちゃえ!! 宇喜多さん",
            http_client=StaticHttpClient(
                {
                    "https://comicborder.com/search?keyword=%E6%AE%BA%E3%81%A3%E3%81%A1%E3%82%83%E3%81%88%21%21+%E5%AE%87%E5%96%9C%E5%A4%9A%E3%81%95%E3%82%93": RuntimeError(
                        "400"
                    ),
                    "https://comicborder.com/": homepage_html,
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="comicborder",
                    title="殺っちゃえ!! 宇喜多さん",
                    seed_url="https://comicborder.com/episode/12207421983382919118",
                    subtitle="comicborder",
                )
            ],
            results,
        )

    def test_search_source_falls_back_to_comic_trail_homepage_results_when_search_is_empty(self):
        homepage_html = """
        <html>
          <body>
            <a href="/episode/2551460910065898017">
              <img alt="破滅の聖女は運命の夫の溺愛から逃れたい｜コミックトレイル" />
            </a>
          </body>
        </html>
        """

        results = search_source(
            "comic-trail",
            "破滅の聖女は運命の夫の溺愛から逃れたい",
            http_client=StaticHttpClient(
                {
                    "https://comic-trail.com/search?keyword=%E7%A0%B4%E6%BB%85%E3%81%AE%E8%81%96%E5%A5%B3%E3%81%AF%E9%81%8B%E5%91%BD%E3%81%AE%E5%A4%AB%E3%81%AE%E6%BA%BA%E6%84%9B%E3%81%8B%E3%82%89%E9%80%83%E3%82%8C%E3%81%9F%E3%81%84": "<html></html>",
                    "https://comic-trail.com/": homepage_html,
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="comic-trail",
                    title="破滅の聖女は運命の夫の溺愛から逃れたい",
                    seed_url="https://comic-trail.com/episode/2551460910065898017",
                    subtitle="comic-trail",
                )
            ],
            results,
        )

    def test_search_source_falls_back_to_shonenjumpplus_homepage_results_when_search_is_empty(self):
        homepage_html = """
        <html>
          <body>
            <li class="daily-series-item">
              <a href="/episode/17107419589372003740">
                <div class="daily-series-info">
                  <h2 class="daily-series-title">SPY×FAMILY</h2>
                </div>
              </a>
            </li>
          </body>
        </html>
        """

        results = search_source(
            "shonenjumpplus",
            "SPY×FAMILY",
            http_client=StaticHttpClient(
                {
                    "https://shonenjumpplus.com/search?query=SPY%C3%97FAMILY": "<html></html>",
                    "https://shonenjumpplus.com/": homepage_html,
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="shonenjumpplus",
                    title="SPY×FAMILY",
                    seed_url="https://shonenjumpplus.com/episode/17107419589372003740",
                    subtitle="shonenjumpplus",
                )
            ],
            results,
        )

    def test_search_source_parses_firecross_results_via_search_page_web_reading_link(self):
        html = """
        <html>
          <body>
            <ul class="seriesList" id="search-result">
              <li class="seriesList_item">
                <div class="series-list-figure">
                  <a href="https://firecross.jp/hjbunko/series/441">
                    <picture>
                      <img alt="灰原くんの強くて青春ニューゲーム" />
                    </picture>
                  </a>
                </div>
                <div class="seriesList_itemMeta">
                  <span class="series-list-label series-list-label--hb">HJ文庫</span>
                </div>
                <a class="seriesList_itemTitle border" href="https://firecross.jp/hjbunko/series/441">灰原くんの強くて青春ニューゲーム</a>
                <div class="seriesList_itemBtnSet">
                  <a class="btn-search-result" href="https://firecross.jp/hjbunko/series/441">シリーズ紹介</a>
                  <a class="btn-search-result" href="https://firecross.jp/ebook/series/441">WEB読み</a>
                </div>
              </li>
            </ul>
          </body>
        </html>
        """

        request_url = "https://firecross.jp/search?q=" + quote_plus("灰原くん") + "&t=1"

        results = search_source(
            "firecross",
            "灰原くん",
            http_client=StaticHttpClient({request_url: html}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="firecross",
                    title="灰原くんの強くて青春ニューゲーム",
                    seed_url="https://firecross.jp/ebook/series/441",
                    subtitle="firecross",
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

    def test_search_source_parses_sunday_webry_results_via_query_parameter(self):
        html = (FIXTURES_ROOT / "sunday-webry" / "search_title.html").read_text(encoding="utf-8")
        request_url = "https://www.sunday-webry.com/search?q=" + quote_plus("尾守つみきと奇日常。")

        results = search_source(
            "sunday-webry",
            "尾守つみきと奇日常。",
            http_client=StaticHttpClient({request_url: html}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="sunday-webry",
                    title="尾守つみきと奇日常。",
                    seed_url="https://www.sunday-webry.com/episode/14079602755299850599",
                    subtitle="sunday-webry",
                )
            ],
            results,
        )

    def test_search_source_rejects_unknown_source(self):
        with self.assertRaisesRegex(ValueError, "unsupported search source"):
            search_source("unknown", "まんが", http_client=StaticHttpClient({}))


if __name__ == "__main__":
    unittest.main()
