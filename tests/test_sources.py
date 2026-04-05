import importlib
import inspect
import json
import pkgutil
import re
import unittest
from pathlib import Path

import manga_watch.sources as source_package
from manga_watch.sources import REGISTERED_ADAPTERS, REGISTERED_SOURCES, SourceAdapter
from manga_watch.sources.base import SourceParseError
from manga_watch.sources.champion_cross import ChampionCrossAdapter
from manga_watch.sources.comic_action import ComicActionAdapter
from manga_watch.sources.comic_walker import ComicWalkerAdapter
from manga_watch.sources.kakuyomu import KakuyomuAdapter
from manga_watch.sources.nicovideo_manga import NicovideoMangaAdapter
from manga_watch.sources.util import html_title
from manga_watch.sources.takecomic import TakecomicAdapter

FIXTURES_ROOT = Path(__file__).parent / "fixtures"
SOURCE_CASES = {
    "comic-walker": (
        "normal",
        "title_variation_or_bonus",
        "same_episode_refresh",
        "broken_missing_next_data",
    ),
    "kakuyomu": (
        "normal",
        "title_variation_or_bonus",
        "same_episode_refresh",
        "broken_missing_next_data",
    ),
    "comic-action": (
        "normal",
        "title_variation",
        "escaped_next_uri",
        "broken_missing_next",
        "broken_loop",
    ),
    "champion-cross": (
        "normal",
        "episode_seed_missing_next_update",
    ),
    "firecross": (
        "normal",
    ),
    "takecomic": (
        "days_of_week_json_only",
        "genre_tag_before_update_label",
        "normal",
    ),
    "nicovideo-manga": (
        "normal",
    ),
}
ADAPTERS = {adapter.source: adapter.__class__ for adapter in REGISTERED_ADAPTERS}
ERROR_TYPES = {
    "SourceParseError": SourceParseError,
    "RuntimeError": RuntimeError,
}
EXPECTED_LATEST_CLASSIFICATIONS = {
    "comic-walker": {
        "normal": "main_story",
        "title_variation_or_bonus": "bonus",
        "same_episode_refresh": "main_story",
    },
    "kakuyomu": {
        "normal": "main_story",
        "title_variation_or_bonus": "bonus",
        "same_episode_refresh": "main_story",
    },
    "comic-action": {
        "normal": "main_story",
        "title_variation": "bonus",
        "escaped_next_uri": "main_story",
        "broken_missing_next": "main_story",
        "broken_loop": "main_story",
    },
    "champion-cross": {
        "normal": "main_story",
        "episode_seed_missing_next_update": "main_story",
    },
    "firecross": {
        "normal": "main_story",
    },
    "takecomic": {
        "days_of_week_json_only": "main_story",
        "genre_tag_before_update_label": "main_story",
        "normal": "main_story",
    },
    "nicovideo-manga": {
        "normal": "main_story",
    },
}


class FixtureHttpClient:
    def __init__(self, case_dir: Path, steps):
        self.case_dir = case_dir
        self.steps = steps
        self.index = 0

    def get_text(self, url: str) -> str:
        if self.index >= len(self.steps):
            raise AssertionError(f"{self.case_dir}: unexpected request after bundle exhausted: {url!r}")

        step = self.steps[self.index]
        self.index += 1
        expected_url = step["url"]
        if url != expected_url:
            raise AssertionError(
                f"{self.case_dir}: request #{self.index} expected {expected_url!r}, got {url!r}"
            )
        return step["body"]

    def assert_consumed(self):
        remaining = [step["url"] for step in self.steps[self.index :]]
        if remaining:
            raise AssertionError(f"{self.case_dir}: bundle not fully consumed: {remaining!r}")


class StaticHttpClient:
    def __init__(self, responses):
        self.responses = dict(responses)
        self.calls = []

    def get_text(self, url: str) -> str:
        self.calls.append(url)
        if url not in self.responses:
            raise AssertionError(f"unexpected request: {url!r}")
        return self.responses[url]


def load_fixture_case(source: str, case_name: str):
    case_dir = FIXTURES_ROOT / source / case_name
    manifest = json.loads((case_dir / "manifest.json").read_text(encoding="utf-8"))
    steps = []
    for step in manifest["steps"]:
        steps.append(
            {
                "url": step["url"],
                "body": (case_dir / step["response"]).read_text(encoding="utf-8"),
            }
        )
    return case_dir, manifest, FixtureHttpClient(case_dir, steps)


def discover_concrete_adapter_sources():
    concrete_sources = {}

    for module_info in pkgutil.iter_modules(source_package.__path__):
        if module_info.ispkg:
            continue

        module = importlib.import_module(f"{source_package.__name__}.{module_info.name}")
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls is SourceAdapter or cls.__module__ != module.__name__:
                continue
            if not issubclass(cls, SourceAdapter) or inspect.isabstract(cls):
                continue

            source = getattr(cls, "source", None)
            if not source:
                raise AssertionError(f"{cls.__module__}.{cls.__name__} must define source")
            if source in concrete_sources:
                raise AssertionError(f"duplicate source adapter discovered for {source}")
            concrete_sources[source] = cls

    return concrete_sources


class SourceAdapterTests(unittest.TestCase):
    maxDiff = None

    def test_html_title_accepts_title_tag_with_attributes(self):
        html = '<html><head><title data-next-head="">作品名｜カドコミ</title></head></html>'

        self.assertEqual("作品名｜カドコミ", html_title(html))

    def test_registry_pins_supported_sources(self):
        self.assertEqual(
            ("comic-walker", "comic-action", "champion-cross", "firecross", "takecomic", "nicovideo-manga", "kakuyomu"),
            REGISTERED_SOURCES,
        )

    def test_registry_covers_every_concrete_adapter_module(self):
        discovered_sources = set(discover_concrete_adapter_sources())

        self.assertEqual(
            discovered_sources,
            set(REGISTERED_SOURCES),
            msg=(
                "Concrete SourceAdapter modules under manga_watch/sources must be added to "
                "manga_watch/sources/registry.py"
            ),
        )

    def test_comic_walker_fixtures(self):
        self._assert_fixture_matrix("comic-walker")

    def test_comic_action_fixtures(self):
        self._assert_fixture_matrix("comic-action")

    def test_kakuyomu_fixtures(self):
        self._assert_fixture_matrix("kakuyomu")

    def test_champion_cross_fixtures(self):
        self._assert_fixture_matrix("champion-cross")

    def test_firecross_fixtures(self):
        self._assert_fixture_matrix("firecross")

    def test_takecomic_fixtures(self):
        self._assert_fixture_matrix("takecomic")

    def test_nicovideo_manga_fixtures(self):
        self._assert_fixture_matrix("nicovideo-manga")

    def test_comic_walker_normalize_accepts_canonical_series_url(self):
        work = ComicWalkerAdapter().normalize("https://comic-walker.com/detail/KC_123456_S/?from=detail")

        self.assertEqual(
            {
                "source": "comic-walker",
                "kind": "comic-walker",
                "workId": "KC_123456_S",
                "seedUrl": "https://comic-walker.com/detail/KC_123456_S",
                "series": "KC_123456_S",
                "seriesCode": "KC_123456_S",
            },
            work.to_dict(),
        )

    def test_kakuyomu_normalize_accepts_work_url(self):
        work = KakuyomuAdapter().normalize("https://kakuyomu.jp/works/123/")

        self.assertEqual(
            {
                "source": "kakuyomu",
                "kind": "kakuyomu",
                "workId": "kakuyomu:123",
                "seedUrl": "https://kakuyomu.jp/works/123/",
                "series": "kakuyomu:123",
                "numericWorkId": "123",
            },
            work.to_dict(),
        )

    def test_champion_cross_normalize_accepts_series_url(self):
        work = ChampionCrossAdapter().normalize("https://championcross.jp/series/abc123/?ref=top")

        self.assertEqual(
            {
                "source": "champion-cross",
                "kind": "champion-cross",
                "workId": "champion-cross:abc123",
                "seedUrl": "https://championcross.jp/series/abc123",
                "series": "champion-cross:abc123",
                "seriesHash": "abc123",
            },
            work.to_dict(),
        )

    def test_takecomic_normalize_accepts_series_url(self):
        work = TakecomicAdapter().normalize("https://takecomic.jp/series/3f846451aff2d/?ref=top")

        self.assertEqual(
            {
                "source": "takecomic",
                "kind": "takecomic",
                "workId": "takecomic:3f846451aff2d",
                "seedUrl": "https://takecomic.jp/series/3f846451aff2d",
                "series": "takecomic:3f846451aff2d",
                "seriesHash": "3f846451aff2d",
            },
            work.to_dict(),
        )

    def test_firecross_normalize_accepts_reader_url(self):
        adapter = ADAPTERS["firecross"]()
        work = adapter.normalize("https://firecross.jp/reader/19386?trial=0&token=temp&vertical=0")

        self.assertEqual(
            {
                "source": "firecross",
                "kind": "firecross",
                "workId": "https://firecross.jp/reader/19386",
                "seedUrl": "https://firecross.jp/reader/19386",
            },
            work.to_dict(),
        )

    def test_nicovideo_manga_normalize_accepts_sp_comic_url(self):
        work = NicovideoMangaAdapter().normalize("https://sp.manga.nicovideo.jp/comic/53764?track=share")

        self.assertEqual(
            {
                "source": "nicovideo-manga",
                "kind": "nicovideo-manga",
                "workId": "nicovideo-manga:53764",
                "seedUrl": "https://manga.nicovideo.jp/comic/53764",
                "series": "nicovideo-manga:53764",
                "comicId": "53764",
            },
            work.to_dict(),
        )

    def test_champion_cross_normalize_accepts_series_rss_url(self):
        work = ChampionCrossAdapter().normalize("https://championcross.jp/series/abc123/rss?ref=top")

        self.assertEqual(
            {
                "source": "champion-cross",
                "kind": "champion-cross",
                "workId": "champion-cross:abc123",
                "seedUrl": "https://championcross.jp/series/abc123/rss",
                "series": "champion-cross:abc123",
                "seriesHash": "abc123",
                "feedKind": "rss",
            },
            work.to_dict(),
        )

    def test_champion_cross_normalize_accepts_episode_url(self):
        work = ChampionCrossAdapter().normalize("https://championcross.jp/episodes/ep12345/?page=1")

        self.assertEqual(
            {
                "source": "champion-cross",
                "kind": "champion-cross",
                "workId": "https://championcross.jp/episodes/ep12345",
                "seedUrl": "https://championcross.jp/episodes/ep12345",
            },
            work.to_dict(),
        )

    def test_comic_action_normalize_accepts_series_feed_url(self):
        work = ComicActionAdapter().normalize("https://comic-action.com/rss/series/13933686331606207128?free_only=1")

        self.assertEqual(
            {
                "source": "comic-action",
                "kind": "comic-action",
                "workId": "comic-action:13933686331606207128",
                "seedUrl": "https://comic-action.com/rss/series/13933686331606207128",
                "series": "comic-action:13933686331606207128",
                "seriesId": "13933686331606207128",
                "feedKind": "rss",
            },
            work.to_dict(),
        )

    def test_comic_action_fetch_latest_accepts_series_feed_url(self):
        adapter = ComicActionAdapter()
        work = adapter.normalize("https://comic-action.com/atom/series/13933686331606207128")
        client = StaticHttpClient(
            {
                "https://comic-action.com/atom/series/13933686331606207128": """
                <feed>
                  <entry>
                    <link href="https://comic-action.com/episode/11341664176570134078" />
                  </entry>
                </feed>
                """,
                "https://comic-action.com/episode/11341664176570134078": """
                <html>
                  <head>
                    <title>第1話 母さんの形見 / つぐもも - 浜田よしかづ | webアクション</title>
                  </head>
                  <body></body>
                </html>
                """,
            }
        )

        latest = adapter.fetch_latest(work, client).to_dict()

        self.assertEqual("comic-action:13933686331606207128", latest["workId"])
        self.assertEqual(
            "https://comic-action.com/episode/11341664176570134078",
            latest["latestKey"],
        )
        self.assertEqual("つぐもも", latest["seriesTitle"])
        self.assertEqual("第1話 母さんの形見", latest["episodeTitle"])
        self.assertEqual(
            [
                "https://comic-action.com/atom/series/13933686331606207128",
                "https://comic-action.com/episode/11341664176570134078",
            ],
            client.calls,
        )

    def test_comic_action_fetch_latest_extracts_next_update_label_from_latest_page(self):
        adapter = ComicActionAdapter()
        work = adapter.normalize("https://comic-action.com/episode/111")
        client = StaticHttpClient(
            {
                "https://comic-action.com/episode/111": """
                <html>
                  <head><title>第1話 / 作品B - webアクション | comic-action</title></head>
                  <body>
                    <script type="text/json" data-value='{"readableProduct":{"nextReadableProductUri":"https://comic-action.com/episode/222"}}'></script>
                  </body>
                </html>
                """,
                "https://comic-action.com/episode/222": """
                <html>
                  <head><title>第2話 / 作品B - webアクション | comic-action</title></head>
                  <body>
                    <div class="viewer-colophon-update-container">
                      <p class="viewer-colophon-next-update">次回更新： 4月3日</p>
                    </div>
                  </body>
                </html>
                """,
            }
        )

        latest = adapter.fetch_latest(work, client).to_dict()

        self.assertEqual("4月3日", latest["nextUpdateLabel"])

    def test_comic_action_fetch_latest_uses_series_rss_for_episode_seed_when_readable_chain_stops(self):
        adapter = ComicActionAdapter()
        work = adapter.normalize("https://comic-action.com/episode/2550689798784879524")
        client = StaticHttpClient(
            {
                "https://comic-action.com/episode/2550689798784879524": """
                <html>
                  <head><title>第39話 / ダンジョンの中のひと - 双見酔 | webアクション</title></head>
                  <body>
                    <script>{"series_id":"13933686331663374228","episode_title":"第39話"}</script>
                    <script id='episode-json' type='text/json' data-value='{
                      "readableProduct":{
                        "series":{"id":"13933686331663374228","title":"ダンジョンの中のひと"},
                        "title":"第39話",
                        "number":50,
                        "nextReadableProductUri":null
                      }
                    }'></script>
                  </body>
                </html>
                """,
                "https://comic-action.com/rss/series/13933686331663374228": """
                <rss>
                  <channel>
                    <item>
                      <title>第51話</title>
                      <link>https://comic-action.com/episode/2551460910007760899</link>
                    </item>
                    <item>
                      <title>第50話</title>
                      <link>https://comic-action.com/episode/2551460909780695609</link>
                    </item>
                  </channel>
                </rss>
                """,
                "https://comic-action.com/episode/2551460910007760899": """
                <html>
                  <head><title>第51話 / ダンジョンの中のひと - 双見酔 | webアクション</title></head>
                  <body>
                    <script id='episode-json' type='text/json' data-value='{"readableProduct":{"title":"第51話","number":51}}'></script>
                    <div class="viewer-colophon-update-container">
                      <p class="viewer-colophon-next-update">次回更新： 4月4日</p>
                    </div>
                  </body>
                </html>
                """,
            }
        )

        latest = adapter.fetch_latest(work, client).to_dict()

        self.assertEqual(
            "https://comic-action.com/episode/2551460910007760899",
            latest["latestKey"],
        )
        self.assertEqual("ダンジョンの中のひと", latest["seriesTitle"])
        self.assertEqual("第51話", latest["episodeTitle"])
        self.assertEqual("4月4日", latest["nextUpdateLabel"])
        self.assertEqual(
            [
                "https://comic-action.com/episode/2550689798784879524",
                "https://comic-action.com/rss/series/13933686331663374228",
                "https://comic-action.com/episode/2551460910007760899",
            ],
            client.calls,
        )

    def test_comic_action_fetch_latest_falls_back_to_entry_episode_when_series_rss_fetch_fails(self):
        adapter = ComicActionAdapter()
        work = adapter.normalize("https://comic-action.com/episode/2550689798784879524")

        class Client:
            def __init__(self):
                self.calls = []

            def get_text(self, url: str) -> str:
                self.calls.append(url)
                if url == "https://comic-action.com/episode/2550689798784879524":
                    return """
                    <html>
                      <head><title>第39話 / ダンジョンの中のひと - 双見酔 | webアクション</title></head>
                      <body>
                        <script>{"series_id":"13933686331663374228","episode_title":"第39話"}</script>
                        <script id='episode-json' type='text/json' data-value='{
                          "readableProduct":{
                            "series":{"id":"13933686331663374228","title":"ダンジョンの中のひと"},
                            "title":"第39話",
                            "number":50,
                            "nextReadableProductUri":null
                          }
                        }'></script>
                      </body>
                    </html>
                    """
                if url == "https://comic-action.com/rss/series/13933686331663374228":
                    raise RuntimeError("temporary feed outage")
                raise AssertionError(f"unexpected request: {url!r}")

        client = Client()

        latest = adapter.fetch_latest(work, client).to_dict()

        self.assertEqual(
            "https://comic-action.com/episode/2550689798784879524",
            latest["latestKey"],
        )
        self.assertEqual("ダンジョンの中のひと", latest["seriesTitle"])
        self.assertEqual("第39話", latest["episodeTitle"])
        self.assertEqual(
            [
                "https://comic-action.com/episode/2550689798784879524",
                "https://comic-action.com/rss/series/13933686331663374228",
            ],
            client.calls,
        )

    def test_comic_action_fetch_latest_keeps_entry_episode_when_series_rss_is_stale(self):
        adapter = ComicActionAdapter()
        work = adapter.normalize("https://comic-action.com/episode/2550689798784879524")
        client = StaticHttpClient(
            {
                "https://comic-action.com/episode/2550689798784879524": """
                <html>
                  <head><title>第39話 / ダンジョンの中のひと - 双見酔 | webアクション</title></head>
                  <body>
                    <script>{"series_id":"13933686331663374228","episode_title":"第39話"}</script>
                    <script id='episode-json' type='text/json' data-value='{
                      "readableProduct":{
                        "series":{"id":"13933686331663374228","title":"ダンジョンの中のひと"},
                        "title":"第39話",
                        "number":51,
                        "nextReadableProductUri":null
                      }
                    }'></script>
                  </body>
                </html>
                """,
                "https://comic-action.com/rss/series/13933686331663374228": """
                <rss>
                  <channel>
                    <item>
                      <title>第50話</title>
                      <link>https://comic-action.com/episode/2551460909780695609</link>
                    </item>
                  </channel>
                </rss>
                """,
                "https://comic-action.com/episode/2551460909780695609": """
                <html>
                  <head><title>第50話 / ダンジョンの中のひと - 双見酔 | webアクション</title></head>
                  <body>
                    <script id='episode-json' type='text/json' data-value='{"readableProduct":{"title":"第50話","number":50}}'></script>
                  </body>
                </html>
                """,
            }
        )

        latest = adapter.fetch_latest(work, client).to_dict()

        self.assertEqual(
            "https://comic-action.com/episode/2550689798784879524",
            latest["latestKey"],
        )
        self.assertEqual("ダンジョンの中のひと", latest["seriesTitle"])
        self.assertEqual("第39話", latest["episodeTitle"])
        self.assertEqual(
            [
                "https://comic-action.com/episode/2550689798784879524",
                "https://comic-action.com/rss/series/13933686331663374228",
                "https://comic-action.com/episode/2551460909780695609",
            ],
            client.calls,
        )

    def test_comic_walker_fetch_latest_extracts_next_update_label(self):
        adapter = ComicWalkerAdapter()
        work = adapter.normalize("https://comic-walker.com/detail/KC_123456_S")
        client = StaticHttpClient(
            {
                "https://comic-walker.com/detail/KC_123456_S": """
                <html>
                  <body>
                    <script id="__NEXT_DATA__" type="application/json">
                      {"episodes":["KC_123456001_E","KC_123456003_E"]}
                    </script>
                  </body>
                </html>
                """,
                "https://comic-walker.com/detail/KC_123456_S/episodes/KC_123456003_E?episodeType=latest": """
                <html>
                  <head><title>【作品A】第3話｜カドコミ (コミックウォーカー)</title></head>
                  <body>
                    <div class="EpisodesTabContents_nextUpdateDate__YDQiC">次回更新予定日：未定</div>
                  </body>
                </html>
                """,
            }
        )

        latest = adapter.fetch_latest(work, client).to_dict()

        self.assertEqual("未定", latest["nextUpdateLabel"])

    def test_kakuyomu_fetch_latest_extracts_next_update_label_from_schedule(self):
        adapter = KakuyomuAdapter()
        work = adapter.normalize("https://kakuyomu.jp/works/123")
        client = StaticHttpClient(
            {
                "https://kakuyomu.jp/works/123": """
                <html>
                  <body>
                    <script id="__NEXT_DATA__" type="application/json">
                      {"props":{"pageProps":{"__APOLLO_STATE__":{"WorkSchedule:123":{"description":"毎日 12:08"}}}},"Episode:456":{"id":"456","title":"第1話","publishedAt":"2025-01-01T00:00:00Z"},"Episode:789":{"id":"789","title":"第2話","publishedAt":"2025-02-01T00:00:00Z"}}
                    </script>
                  </body>
                </html>
                """,
                "https://kakuyomu.jp/works/123/episodes/789": """
                <html>
                  <head><title>第2話 - 作品C - カクヨム</title></head>
                </html>
                """,
            }
        )

        latest = adapter.fetch_latest(work, client).to_dict()

        self.assertEqual("毎日 12:08", latest["nextUpdateLabel"])

    def test_kakuyomu_fetch_latest_allows_null_schedule(self):
        adapter = KakuyomuAdapter()
        work = adapter.normalize("https://kakuyomu.jp/works/123")
        client = StaticHttpClient(
            {
                "https://kakuyomu.jp/works/123": """
                <html>
                  <body>
                    <script id="__NEXT_DATA__" type="application/json">
                      {"props":{"pageProps":{"__APOLLO_STATE__":{"Work:123":{"schedule":null}}}},"Episode:456":{"id":"456","title":"第1話","publishedAt":"2025-01-01T00:00:00Z"},"Episode:789":{"id":"789","title":"第2話","publishedAt":"2025-02-01T00:00:00Z"}}
                    </script>
                  </body>
                </html>
                """,
                "https://kakuyomu.jp/works/123/episodes/789": """
                <html>
                  <head><title>第2話 - 作品C - カクヨム</title></head>
                </html>
                """,
            }
        )

        latest = adapter.fetch_latest(work, client).to_dict()

        self.assertNotIn("nextUpdateLabel", latest)

    def test_comic_action_fetch_latest_accepts_www_episode_links_from_feed(self):
        adapter = ComicActionAdapter()
        work = adapter.normalize("https://comic-action.com/rss/series/13933686331606207128")
        client = StaticHttpClient(
            {
                "https://comic-action.com/rss/series/13933686331606207128": """
                <rss>
                  <channel>
                    <item>
                      <link>https://www.comic-action.com/episode/11341664176570134078</link>
                    </item>
                  </channel>
                </rss>
                """,
                "https://comic-action.com/episode/11341664176570134078": """
                <html>
                  <head>
                    <title>第1話 母さんの形見 / つぐもも - 浜田よしかづ | webアクション</title>
                  </head>
                  <body></body>
                </html>
                """,
            }
        )

        latest = adapter.fetch_latest(work, client).to_dict()

        self.assertEqual("comic-action:13933686331606207128", latest["workId"])
        self.assertEqual(
            "https://comic-action.com/episode/11341664176570134078",
            latest["latestKey"],
        )
        self.assertEqual(
            [
                "https://comic-action.com/rss/series/13933686331606207128",
                "https://comic-action.com/episode/11341664176570134078",
            ],
            client.calls,
        )

    def test_champion_cross_normalize_accepts_series_rss_url(self):
        work = ChampionCrossAdapter().normalize("https://championcross.jp/series/4756324e1c1b1/rss?from=share")

        self.assertEqual(
            {
                "source": "champion-cross",
                "kind": "champion-cross",
                "workId": "champion-cross:4756324e1c1b1",
                "seedUrl": "https://championcross.jp/series/4756324e1c1b1/rss",
                "series": "champion-cross:4756324e1c1b1",
                "seriesHash": "4756324e1c1b1",
                "feedKind": "rss",
            },
            work.to_dict(),
        )

    def test_champion_cross_fetch_latest_accepts_series_url(self):
        adapter = ChampionCrossAdapter()
        work = adapter.normalize("https://championcross.jp/series/4756324e1c1b1/")
        client = StaticHttpClient(
            {
                "https://championcross.jp/series/4756324e1c1b1/rss": """
                <rss>
                  <channel>
                    <title>織津江大志の異世界クリ娘サバイバル日誌</title>
                    <item>
                      <title><![CDATA[第71話 ウェンディゴ2]]></title>
                      <link>https://championcross.jp/episodes/f35108c56e75d/?utm_source=rss&amp;utm_medium=referral</link>
                    </item>
                  </channel>
                </rss>
                """,
                "https://championcross.jp/episodes/f35108c56e75d": """
                <html>
                  <body>
                    <a href="/category/manga?type=連載中&amp;day=火" class="series-h-day-of-week-link">
                      <span class="series-h-tag-label">火曜更新</span>
                    </a>
                  </body>
                </html>
                """,
            }
        )

        latest = adapter.fetch_latest(work, client).to_dict()

        self.assertEqual("champion-cross:4756324e1c1b1", latest["workId"])
        self.assertEqual("champion-cross:4756324e1c1b1", latest["series"])
        self.assertEqual("https://championcross.jp/episodes/f35108c56e75d", latest["latestKey"])
        self.assertEqual("織津江大志の異世界クリ娘サバイバル日誌", latest["seriesTitle"])
        self.assertEqual("第71話 ウェンディゴ2", latest["episodeTitle"])
        self.assertEqual("火曜更新", latest["nextUpdateLabel"])
        self.assertEqual(
            [
                "https://championcross.jp/series/4756324e1c1b1/rss",
                "https://championcross.jp/episodes/f35108c56e75d",
            ],
            client.calls,
        )

    def test_takecomic_fetch_latest_accepts_series_url(self):
        adapter = TakecomicAdapter()
        work = adapter.normalize("https://takecomic.jp/series/3f846451aff2d/")
        client = StaticHttpClient(
            {
                "https://takecomic.jp/series/3f846451aff2d/rss": """
                <rss>
                  <channel>
                    <title>作品D</title>
                    <item>
                      <title><![CDATA[第10話]]></title>
                      <link>https://takecomic.jp/episodes/abc12345?from=rss</link>
                    </item>
                  </channel>
                </rss>
                """,
                "https://takecomic.jp/episodes/abc12345": """
                <html>
                  <body>
                    <a href="/category/manga?type=連載中&amp;day=火" class="series-h-day-of-week-link">
                      <span class="series-h-tag-label">火曜更新</span>
                    </a>
                  </body>
                </html>
                """,
            }
        )

        latest = adapter.fetch_latest(work, client).to_dict()

        self.assertEqual("takecomic:3f846451aff2d", latest["workId"])
        self.assertEqual("https://takecomic.jp/episodes/abc12345", latest["latestKey"])
        self.assertEqual("作品D", latest["seriesTitle"])
        self.assertEqual("第10話", latest["episodeTitle"])
        self.assertEqual("火曜更新", latest["nextUpdateLabel"])
        self.assertEqual(
            [
                "https://takecomic.jp/series/3f846451aff2d/rss",
                "https://takecomic.jp/episodes/abc12345",
            ],
            client.calls,
        )

    def test_firecross_fetch_latest_accepts_reader_url(self):
        adapter = ADAPTERS["firecross"]()
        work = adapter.normalize("https://firecross.jp/reader/19386?trial=0&token=temp")
        client = StaticHttpClient(
            {
                "https://firecross.jp/reader/19386": """
                <html>
                  <head><title>第12話 / 作品E | ファイアCROSS</title></head>
                  <body>
                    <a href="https://firecross.jp/series/series-abc">作品詳細</a>
                  </body>
                </html>
                """,
                "https://firecross.jp/series/series-abc": """
                <html>
                  <head><title>作品E | ファイアCROSS</title></head>
                  <body>
                    <a class="latest-episode" href="https://firecross.jp/reader/19420?from=series">最新話</a>
                  </body>
                </html>
                """,
                "https://firecross.jp/reader/19420": """
                <html>
                  <head><title>第13話 / 作品E | ファイアCROSS</title></head>
                  <body></body>
                </html>
                """,
            }
        )

        latest = adapter.fetch_latest(work, client).to_dict()

        self.assertEqual("https://firecross.jp/reader/19420", latest["latestKey"])
        self.assertEqual("https://firecross.jp/reader/19420", latest["url"])
        self.assertEqual("firecross:series-abc", latest["series"])
        self.assertEqual("作品E", latest["seriesTitle"])
        self.assertEqual("第13話", latest["episodeTitle"])
        self.assertEqual(
            [
                "https://firecross.jp/reader/19386",
                "https://firecross.jp/series/series-abc",
                "https://firecross.jp/reader/19420",
            ],
            client.calls,
        )

    def test_nicovideo_manga_fetch_latest_accepts_comic_url(self):
        adapter = NicovideoMangaAdapter()
        work = adapter.normalize("https://sp.manga.nicovideo.jp/comic/53764")
        client = StaticHttpClient(
            {
                "https://manga.nicovideo.jp/comic/53764/new": """
                <html>
                  <head>
                    <meta property="og:url" content="https://manga.nicovideo.jp/watch/mg1007626" />
                    <title>ダンジョンの中のひと 第51話 / 双見酔 - ニコニコ漫画</title>
                  </head>
                  <body></body>
                </html>
                """,
            }
        )

        latest = adapter.fetch_latest(work, client).to_dict()

        self.assertEqual("nicovideo-manga:53764", latest["workId"])
        self.assertEqual("https://manga.nicovideo.jp/watch/mg1007626", latest["latestKey"])
        self.assertEqual("https://manga.nicovideo.jp/watch/mg1007626", latest["url"])
        self.assertEqual("nicovideo-manga:53764", latest["series"])
        self.assertEqual("ダンジョンの中のひと", latest["seriesTitle"])
        self.assertEqual("第51話", latest["episodeTitle"])
        self.assertEqual(
            ["https://manga.nicovideo.jp/comic/53764/new"],
            client.calls,
        )

    def _assert_fixture_matrix(self, source: str):
        source_dir = FIXTURES_ROOT / source
        actual_cases = sorted(path.name for path in source_dir.iterdir() if path.is_dir())
        self.assertEqual(sorted(SOURCE_CASES[source]), actual_cases)

        adapter_class = ADAPTERS[source]
        for case_name in SOURCE_CASES[source]:
            with self.subTest(source=source, case=case_name):
                _, manifest, client = load_fixture_case(source, case_name)
                adapter = adapter_class()
                work = adapter.normalize(manifest["seedUrl"])
                self.assertEqual(manifest["expectedWork"], work.to_dict())

                expected_error = manifest.get("expectedError")
                if expected_error:
                    error_type = ERROR_TYPES[expected_error["type"]]
                    with self.assertRaisesRegex(error_type, re.escape(expected_error["message"])):
                        adapter.fetch_latest(work, client)
                else:
                    latest = adapter.fetch_latest(work, client)
                    latest_dict = latest.to_dict()
                    expected_latest = manifest["expectedLatest"]
                    self.assertEqual(
                        expected_latest,
                        {key: latest_dict[key] for key in expected_latest},
                    )
                    for key in manifest.get("missingLatestKeys", []):
                        self.assertNotIn(key, latest_dict)
                    self.assertEqual(
                        EXPECTED_LATEST_CLASSIFICATIONS[source][case_name],
                        latest_dict["update_type"],
                    )
                    self.assertTrue(latest_dict["classification_reason"])
                    self.assertEqual(
                        latest_dict["update_type"] in {"main_story", "unknown"},
                        latest_dict["default_notify"],
                    )

                client.assert_consumed()


if __name__ == "__main__":
    unittest.main()
