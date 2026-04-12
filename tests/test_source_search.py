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

    def test_search_source_parses_gaugau_results(self):
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

    def test_search_source_parses_comic_walker_homepage_results(self):
        html = """
        <html>
          <body>
            <li class="RichWorkItemList_item__GOpOw">
              <div>
                <a class="RichItemBaseActionArea_root__aFnbG" href="/detail/KC_008280_S/episodes/KC_0082800000700011_E?episodeType=latest">
                  <div class="RichItemBaseRow_root__qzgLT" style="--margin-top:4px">
                    <div class="RichWorkItem_titleText__Jz1k7">異世界迷宮の迷子ちゃん</div>
                  </div>
                  <div class="RichItemBaseRow_root__qzgLT" style="--margin-top:8px">
                    <div class="RichWorkItem_episodeTitleText__0upMA">第6話①を読む</div>
                  </div>
                </a>
              </div>
            </li>
          </body>
        </html>
        """

        results = search_source(
            "comic-walker",
            "異世界迷宮の迷子ちゃん",
            http_client=StaticHttpClient(
                {
                    "https://comic-walker.com/search?q=%E7%95%B0%E4%B8%96%E7%95%8C%E8%BF%B7%E5%AE%AE%E3%81%AE%E8%BF%B7%E5%AD%90%E3%81%A1%E3%82%83%E3%82%93": "<html></html>",
                    "https://comic-walker.com/": html,
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="comic-walker",
                    title="異世界迷宮の迷子ちゃん",
                    seed_url="https://comic-walker.com/detail/KC_008280_S",
                    subtitle="comic-walker",
                )
            ],
            results,
        )

    def test_search_source_parses_comic_earthstar_homepage_results(self):
        html = """
        <html>
          <body>
            <li class="UpdatedSeriesListItem_list_item__v8G5P">
              <a href="https://comic-earthstar.com/episode/12207421983458916468">
                <div class="UpdatedSeriesListItem_thumb__HGW7s">
                  <img alt="戦国小町苦労譚" />
                </div>
                <div class="UpdatedSeriesListItem_description__8_rGj">戦国小町苦労譚</div>
                <div class="UpdatedSeriesListItem_episode_title__yfDUB"><span>第百幕 凜然 後編</span></div>
              </a>
            </li>
          </body>
        </html>
        """

        results = search_source(
            "comic-earthstar",
            "戦国小町苦労譚",
            http_client=StaticHttpClient(
                {
                    "https://comic-earthstar.com/search?keyword=%E6%88%A6%E5%9B%BD%E5%B0%8F%E7%94%BA%E8%8B%A6%E5%8A%B4%E8%AD%9A": "<html></html>",
                    "https://comic-earthstar.com/": html,
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="comic-earthstar",
                    title="戦国小町苦労譚",
                    seed_url="https://comic-earthstar.com/episode/12207421983458916468",
                    subtitle="comic-earthstar",
                )
            ],
            results,
        )

    def test_search_source_parses_comicborder_homepage_results(self):
        html = """
        <html>
          <body>
            <ul class="index-list-all">
              <li><a href="https://comicborder.com/episode/3269754496750702763">勇者のクズ</a></li>
            </ul>
          </body>
        </html>
        """

        results = search_source(
            "comicborder",
            "勇者のクズ",
            http_client=StaticHttpClient(
                {
                    "https://comicborder.com/search?keyword=%E5%8B%87%E8%80%85%E3%81%AE%E3%82%AF%E3%82%BA": '{"error":{"message":"wrong feature"}}',
                    "https://comicborder.com/": html,
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="comicborder",
                    title="勇者のクズ",
                    seed_url="https://comicborder.com/episode/3269754496750702763",
                    subtitle="comicborder",
                )
            ],
            results,
        )

    def test_search_source_parses_comic_trail_homepage_results_from_image_alt(self):
        html = """
        <html>
          <body>
            <li class="normal-series s13933686331766872960">
              <a href="https://comic-trail.com/episode/12207421983425238737">
                <div class="thumb">
                  <img alt="アタリ｜琥狗ハヤテ" />
                </div>
                <h2 class="episode-title">其の四十一</h2>
                <div class="text-tag">
                  <span>＃ねこまた。</span>
                </div>
              </a>
            </li>
          </body>
        </html>
        """

        results = search_source(
            "comic-trail",
            "アタリ",
            http_client=StaticHttpClient(
                {
                    "https://comic-trail.com/search?keyword=%E3%82%A2%E3%82%BF%E3%83%AA": "<html></html>",
                    "https://comic-trail.com/": html,
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="comic-trail",
                    title="アタリ",
                    seed_url="https://comic-trail.com/episode/12207421983425238737",
                    subtitle="comic-trail",
                )
            ],
            results,
        )

    def test_search_source_parses_kuragebunch_homepage_results(self):
        html = """
        <html>
          <body>
            <li class="series-items-box">
              <a href="https://kuragebunch.com/episode/12207421983484661205" class="episode-link force-first-episode">
                <div class="episode-link-thumb">
                  <img alt="極主夫道" />
                </div>
                <div class="episode-link-title">
                  <h4>極主夫道</h4>
                </div>
              </a>
            </li>
          </body>
        </html>
        """

        results = search_source(
            "kuragebunch",
            "極主夫道",
            http_client=StaticHttpClient(
                {
                    "https://kuragebunch.com/search?keyword=%E6%A5%B5%E4%B8%BB%E5%A4%AB%E9%81%93": "<html></html>",
                    "https://kuragebunch.com/": html,
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="kuragebunch",
                    title="極主夫道",
                    seed_url="https://kuragebunch.com/episode/12207421983484661205",
                    subtitle="kuragebunch",
                )
            ],
            results,
        )

    def test_search_source_parses_shonenjumpplus_homepage_results(self):
        html = """
        <html>
          <body>
            <li class="daily-series-item">
              <a href="https://shonenjumpplus.com/episode/17107419589191808162">
                <div class="daily-series-info">
                  <h2 class="daily-series-title">ふつうの軽音部</h2>
                </div>
              </a>
            </li>
          </body>
        </html>
        """

        results = search_source(
            "shonenjumpplus",
            "ふつうの軽音部",
            http_client=StaticHttpClient(
                {
                    "https://shonenjumpplus.com/search?query=%E3%81%B5%E3%81%A4%E3%81%86%E3%81%AE%E8%BB%BD%E9%9F%B3%E9%83%A8": "<html></html>",
                    "https://shonenjumpplus.com/": html,
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="shonenjumpplus",
                    title="ふつうの軽音部",
                    seed_url="https://shonenjumpplus.com/episode/17107419589191808162",
                    subtitle="shonenjumpplus",
                )
            ],
            results,
        )

    def test_search_source_parses_sunday_webry_homepage_results(self):
        html = """
        <html>
          <body>
            <li class="daily-series-item">
              <a href="https://www.sunday-webry.com/episode/12207421983588825279">
                <div class="thumb-wrapper">
                  <img alt="レッドブルー" />
                </div>
                <h4>レッドブルー</h4>
                <p class="episode-title">第189話 目指せ万バズ</p>
              </a>
            </li>
          </body>
        </html>
        """

        results = search_source(
            "sunday-webry",
            "レッドブルー",
            http_client=StaticHttpClient(
                {
                    "https://www.sunday-webry.com/search?query=%E3%83%AC%E3%83%83%E3%83%89%E3%83%96%E3%83%AB%E3%83%BC": "<html></html>",
                    "https://www.sunday-webry.com/": html,
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="sunday-webry",
                    title="レッドブルー",
                    seed_url="https://www.sunday-webry.com/episode/12207421983588825279",
                    subtitle="sunday-webry",
                )
            ],
            results,
        )

    def test_search_source_parses_root_relative_homepage_fallback_results(self):
        html = """
        <html>
          <body>
            <li class="daily-series-item">
              <a href="/episode/12207421983588825279">
                <div class="thumb-wrapper">
                  <img alt="レッドブルー" />
                </div>
                <h4>レッドブルー</h4>
              </a>
            </li>
          </body>
        </html>
        """

        results = search_source(
            "sunday-webry",
            "レッドブルー",
            http_client=StaticHttpClient(
                {
                    "https://www.sunday-webry.com/search?query=%E3%83%AC%E3%83%83%E3%83%89%E3%83%96%E3%83%AB%E3%83%BC": "<html></html>",
                    "https://www.sunday-webry.com/": html,
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="sunday-webry",
                    title="レッドブルー",
                    seed_url="https://www.sunday-webry.com/episode/12207421983588825279",
                    subtitle="sunday-webry",
                )
            ],
            results,
        )

    def test_search_source_strips_champion_cross_campaign_suffixes(self):
        html = """
        <html>
          <body>
            <a href="/series/899dda204c3f2/">
              僕の心のヤバイやつ【最新話無料】 桜井のりお
            </a>
          </body>
        </html>
        """
        request_url = "https://championcross.jp/search?keyword=%E5%83%95%E3%81%AE%E5%BF%83%E3%81%AE%E3%83%A4%E3%83%90%E3%82%A4%E3%82%84%E3%81%A4"

        results = search_source(
            "champion-cross",
            "僕の心のヤバイやつ",
            http_client=StaticHttpClient({request_url: html}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="champion-cross",
                    title="僕の心のヤバイやつ",
                    seed_url="https://championcross.jp/series/899dda204c3f2",
                    subtitle="champion-cross",
                )
            ],
            results,
        )

    def test_search_source_keeps_multiword_champion_cross_titles(self):
        html = """
        <html>
          <body>
            <a href="/series/e349a3791821b/">
              ONE PIECE
            </a>
          </body>
        </html>
        """
        request_url = "https://championcross.jp/search?keyword=ONE+PIECE"

        results = search_source(
            "champion-cross",
            "ONE PIECE",
            http_client=StaticHttpClient({request_url: html}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="champion-cross",
                    title="ONE PIECE",
                    seed_url="https://championcross.jp/series/e349a3791821b",
                    subtitle="champion-cross",
                )
            ],
            results,
        )

    def test_search_source_matches_titles_case_insensitively(self):
        html = """
        <html>
          <body>
            <a href="/series/e349a3791821b/">
              ONE PIECE
            </a>
          </body>
        </html>
        """
        request_url = "https://championcross.jp/search?keyword=one+piece"

        results = search_source(
            "champion-cross",
            "one piece",
            http_client=StaticHttpClient({request_url: html}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="champion-cross",
                    title="ONE PIECE",
                    seed_url="https://championcross.jp/series/e349a3791821b",
                    subtitle="champion-cross",
                )
            ],
            results,
        )

    def test_search_source_does_not_truncate_champion_cross_titles_for_space_separated_prefix_queries(self):
        html = """
        <html>
          <body>
            <a href="/series/e349a3791821b/">
              ONE PIECE
            </a>
          </body>
        </html>
        """
        request_url = "https://championcross.jp/search?keyword=ONE"

        results = search_source(
            "champion-cross",
            "ONE",
            http_client=StaticHttpClient({request_url: html}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="champion-cross",
                    title="ONE PIECE",
                    seed_url="https://championcross.jp/series/e349a3791821b",
                    subtitle="champion-cross",
                )
            ],
            results,
        )

    def test_search_source_does_not_truncate_champion_cross_titles_for_prefix_queries(self):
        html = """
        <html>
          <body>
            <a href="/series/899dda204c3f2/">
              僕の心のヤバイやつ【最新話無料】 桜井のりお
            </a>
          </body>
        </html>
        """
        request_url = "https://championcross.jp/search?keyword=%E5%83%95%E3%81%AE%E5%BF%83"

        results = search_source(
            "champion-cross",
            "僕の心",
            http_client=StaticHttpClient({request_url: html}),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="champion-cross",
                    title="僕の心のヤバイやつ 桜井のりお",
                    seed_url="https://championcross.jp/series/899dda204c3f2",
                    subtitle="champion-cross",
                )
            ],
            results,
        )

    def test_search_source_parses_magapoke_homepage_results(self):
        html = """
        <html>
          <body>
            <li class="c-ranking-items__item">
              <a href="/title/01524/episode/329599" class="c-ranking-item">
                <div class="c-ranking-item__thumb">
                  <div class="c-ranking-item__img"><img alt="薫る花は凛と咲く" /></div>
                </div>
                <div class="c-ranking-item__detail">
                  <h3 class="c-ranking-item__ttl">薫る花は凛と咲く</h3>
                </div>
              </a>
            </li>
          </body>
        </html>
        """

        results = search_source(
            "magapoke",
            "薫る花は凛と咲く",
            http_client=StaticHttpClient(
                {
                    "https://pocket.shonenmagazine.com/search?query=%E8%96%AB%E3%82%8B%E8%8A%B1%E3%81%AF%E5%87%9B%E3%81%A8%E5%92%B2%E3%81%8F": "<html></html>",
                    "https://pocket.shonenmagazine.com/": html,
                }
            ),
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

    def test_search_source_parses_takecomic_search_results_without_update_prefix(self):
        html = """
        <html>
          <body>
            <div class="series-list-item">
              <a class="series-list-item-link" href="/series/506d4c55753aa">
                <div class="series-list-item-desc">
                  <div class="series-list-item-h"><span data-e2e="sliTitle">ねこもんすたー</span></div>
                </div>
              </a>
            </div>
            <div class="series-list-item">
              <a class="series-list-item-link" href="/series/422e135f10aeb">
                <div class="g-updated-mark-wrap"><div class="g-updated-mark">更新</div></div>
                <div class="series-list-item-desc">
                  <div class="series-list-item-h"><span data-e2e="sliTitle">のみじょし</span></div>
                </div>
              </a>
            </div>
          </body>
        </html>
        """

        results = search_source(
            "takecomic",
            "のみじょし",
            http_client=StaticHttpClient(
                {
                    "https://takecomic.jp/search?keyword=%E3%81%AE%E3%81%BF%E3%81%98%E3%82%87%E3%81%97": html,
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="takecomic",
                    title="のみじょし",
                    seed_url="https://takecomic.jp/series/422e135f10aeb",
                    subtitle="takecomic",
                )
            ],
            results,
        )

    def test_search_source_parses_takecomic_results_when_href_precedes_class(self):
        html = """
        <html>
          <body>
            <div class="series-list-item">
              <a href="/series/422e135f10aeb" class="series-list-item-link">
                <div class="series-list-item-desc">
                  <div class="series-list-item-h"><span data-e2e="sliTitle">のみじょし</span></div>
                </div>
              </a>
            </div>
          </body>
        </html>
        """

        results = search_source(
            "takecomic",
            "のみじょし",
            http_client=StaticHttpClient(
                {
                    "https://takecomic.jp/search?keyword=%E3%81%AE%E3%81%BF%E3%81%98%E3%82%87%E3%81%97": html,
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="takecomic",
                    title="のみじょし",
                    seed_url="https://takecomic.jp/series/422e135f10aeb",
                    subtitle="takecomic",
                )
            ],
            results,
        )

    def test_search_source_filters_takecomic_results_before_applying_limit(self):
        html = """
        <html>
          <body>
            <div class="series-list-item">
              <a class="series-list-item-link" href="/series/506d4c55753aa">
                <span data-e2e="sliTitle">ねこもんすたー</span>
              </a>
            </div>
            <div class="series-list-item">
              <a class="series-list-item-link" href="/series/78ed85a57a8f2">
                <span data-e2e="sliTitle">未経験の私がアシですか!?</span>
              </a>
            </div>
            <div class="series-list-item">
              <a class="series-list-item-link" href="/series/422e135f10aeb">
                <span data-e2e="sliTitle">のみじょし</span>
              </a>
            </div>
          </body>
        </html>
        """

        results = search_source(
            "takecomic",
            "のみじょし",
            http_client=StaticHttpClient(
                {
                    "https://takecomic.jp/search?keyword=%E3%81%AE%E3%81%BF%E3%81%98%E3%82%87%E3%81%97": html,
                }
            ),
            limit=2,
        )

        self.assertEqual(
            [
                SearchResult(
                    source="takecomic",
                    title="のみじょし",
                    seed_url="https://takecomic.jp/series/422e135f10aeb",
                    subtitle="takecomic",
                )
            ],
            results,
        )

    def test_search_source_prefers_kakuyomu_work_links_over_episode_links(self):
        html = """
        <html>
          <body>
            <a href="/works/16817139555923024504" title="異世界刀匠魔剣製作記">作品ページ</a>
            <a href="/works/16817139555923024504/episodes/16817139555923278878">1話目から読む</a>
          </body>
        </html>
        """

        results = search_source(
            "kakuyomu",
            "異世界刀匠魔剣製作記",
            http_client=StaticHttpClient(
                {
                    "https://kakuyomu.jp/search?q=%E7%95%B0%E4%B8%96%E7%95%8C%E5%88%80%E5%8C%A0%E9%AD%94%E5%89%A3%E8%A3%BD%E4%BD%9C%E8%A8%98": html
                }
            ),
        )

        self.assertEqual(
            [
                SearchResult(
                    source="kakuyomu",
                    title="異世界刀匠魔剣製作記",
                    seed_url="https://kakuyomu.jp/works/16817139555923024504",
                    subtitle="kakuyomu",
                )
            ],
            results,
        )

    def test_search_source_filters_kakuyomu_work_results_before_applying_limit(self):
        html = """
        <html>
          <body>
            <a href="/works/1" title="作品A">作品A</a>
            <a href="/works/2" title="作品B">作品B</a>
            <a href="/works/16817139555923024504" title="異世界刀匠魔剣製作記">異世界刀匠魔剣製作記</a>
          </body>
        </html>
        """

        results = search_source(
            "kakuyomu",
            "異世界刀匠魔剣製作記",
            http_client=StaticHttpClient(
                {
                    "https://kakuyomu.jp/search?q=%E7%95%B0%E4%B8%96%E7%95%8C%E5%88%80%E5%8C%A0%E9%AD%94%E5%89%A3%E8%A3%BD%E4%BD%9C%E8%A8%98": html
                }
            ),
            limit=2,
        )

        self.assertEqual(
            [
                SearchResult(
                    source="kakuyomu",
                    title="異世界刀匠魔剣製作記",
                    seed_url="https://kakuyomu.jp/works/16817139555923024504",
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
