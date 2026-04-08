import importlib
import inspect
import json
import pkgutil
import re
import unittest
from pathlib import Path

import manga_watch.sources as source_package
from manga_watch.sources import (
    REGISTERED_ADAPTERS,
    REGISTERED_SOURCES,
    SourceAdapter,
    fetch_latest_for_work,
    normalize_seed_url,
)
from manga_watch.sources.base import SourceParseError, WorkDescriptor
from manga_watch.sources.champion_cross import ChampionCrossAdapter
from manga_watch.sources.comic_action import ComicActionAdapter
from manga_watch.sources.comic_walker import ComicWalkerAdapter
from manga_watch.sources.kakuyomu import KakuyomuAdapter
from manga_watch.sources.magapoke import MagapokeAdapter
from manga_watch.sources.nicovideo_manga import NicovideoMangaAdapter
from manga_watch.sources.shonenjumpplus import ShonenJumpPlusAdapter
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
    "comicborder": (
        "normal",
        "broken_missing_series_id",
    ),
    "comic-trail": (
        "normal",
        "broken_missing_series_id",
    ),
    "shonenjumpplus": (
        "broken_missing_series_id",
        "normal",
    ),
    "champion-cross": (
        "normal",
        "episode_seed_missing_next_update",
    ),
    "magapoke": (
        "normal",
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
    "comicborder": {
        "normal": "main_story",
    },
    "comic-trail": {
        "normal": "main_story",
    },
    "shonenjumpplus": {
        "normal": "main_story",
    },
    "champion-cross": {
        "normal": "main_story",
        "episode_seed_missing_next_update": "main_story",
    },
    "magapoke": {
        "normal": "main_story",
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
            (
                "comic-walker",
                "comic-action",
                "comicborder",
                "comic-trail",
                "shonenjumpplus",
                "champion-cross",
                "magapoke",
                "firecross",
                "takecomic",
                "nicovideo-manga",
                "kakuyomu",
            ),
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

    def test_shonenjumpplus_fixtures(self):
        self._assert_fixture_matrix("shonenjumpplus")

    def test_comicborder_fixtures(self):
        self._assert_fixture_matrix("comicborder")

    def test_comic_trail_fixtures(self):
        self._assert_fixture_matrix("comic-trail")

    def test_kakuyomu_fixtures(self):
        self._assert_fixture_matrix("kakuyomu")

    def test_champion_cross_fixtures(self):
        self._assert_fixture_matrix("champion-cross")

    def test_firecross_fixtures(self):
        self._assert_fixture_matrix("firecross")

    def test_magapoke_fixtures(self):
        self._assert_fixture_matrix("magapoke")

    def test_takecomic_fixtures(self):
        self._assert_fixture_matrix("takecomic")

    def test_nicovideo_manga_fixtures(self):
        self._assert_fixture_matrix("nicovideo-manga")

    def test_magapoke_normalize_accepts_episode_url(self):
        work = MagapokeAdapter().normalize(
            "https://pocket.shonenmagazine.com/title/03021/episode/427856?utm_source=share"
        )

        self.assertEqual(
            {
                "source": "magapoke",
                "kind": "magapoke",
                "workId": "magapoke:3021",
                "seedUrl": "https://pocket.shonenmagazine.com/title/03021",
                "series": "magapoke:3021",
                "titleId": "3021",
                "titleSlug": "03021",
            },
            work.to_dict(),
        )

    def test_magapoke_fetch_latest_reads_series_rss_from_title_page(self):
        adapter = MagapokeAdapter()
        work = adapter.normalize("https://pocket.shonenmagazine.com/title/03021/episode/427856")
        client = StaticHttpClient(
            {
                "https://pocket.shonenmagazine.com/title/03021": """
                <html>
                  <head>
                    <title>普通の本はありません！ / マガポケ</title>
                    <link rel="alternate" type="application/rss+xml" href="https://mgpk-cdn.magazinepocket.com/static/rss/3021/feed.xml">
                  </head>
                  <body>
                    <p class="p-episode__update-txt">次回更新は4/20(月曜)予定です。</p>
                  </body>
                </html>
                """,
                "https://mgpk-cdn.magazinepocket.com/static/rss/3021/feed.xml": """
                <rss>
                  <channel>
                    <title>マガポケ（普通の本はありません！）</title>
                    <item>
                      <title>【＃17】ハルとギンギン丸</title>
                      <link>https://pocket.shonenmagazine.com/title/03021/episode/434393</link>
                      <description>普通の本はありません！</description>
                    </item>
                  </channel>
                </rss>
                """,
            }
        )

        latest = adapter.fetch_latest(work, client).to_dict()

        self.assertEqual("magapoke:3021", latest["workId"])
        self.assertEqual(
            "https://pocket.shonenmagazine.com/title/03021/episode/434393",
            latest["latestKey"],
        )
        self.assertEqual("普通の本はありません！", latest["seriesTitle"])
        self.assertEqual("【＃17】ハルとギンギン丸", latest["episodeTitle"])
        self.assertEqual("次回更新は4/20(月曜)予定です。", latest["nextUpdateLabel"])
        self.assertEqual(
            [
                "https://pocket.shonenmagazine.com/title/03021",
                "https://mgpk-cdn.magazinepocket.com/static/rss/3021/feed.xml",
            ],
            client.calls,
        )

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

    def test_comic_trail_normalize_accepts_episode_and_feed_urls(self):
        episode_work = normalize_seed_url("https://comic-trail.com/episode/2550689798402927313?from=share").to_dict()
        rss_work = normalize_seed_url("https://comic-trail.com/rss/series/14079602755560047206?from=share").to_dict()
        atom_work = normalize_seed_url("https://comic-trail.com/atom/series/14079602755560047206?from=share").to_dict()

        self.assertEqual(
            {
                "source": "comic-trail",
                "kind": "comic-trail",
                "workId": "https://comic-trail.com/episode/2550689798402927313",
                "seedUrl": "https://comic-trail.com/episode/2550689798402927313",
            },
            episode_work,
        )
        expected_feed = {
            "source": "comic-trail",
            "kind": "comic-trail",
            "workId": "comic-trail:14079602755560047206",
            "seedUrl": "https://comic-trail.com/rss/series/14079602755560047206",
            "series": "comic-trail:14079602755560047206",
            "seriesId": "14079602755560047206",
            "feedKind": "rss",
        }
        self.assertEqual(expected_feed, rss_work)
        self.assertEqual(expected_feed, atom_work)

    def test_comic_trail_fetch_latest_accepts_canonical_feed_seed(self):
        work = WorkDescriptor(
            source="comic-trail",
            work_id="comic-trail:14079602755560047206",
            seed_url="https://comic-trail.com/rss/series/14079602755560047206",
            metadata={
                "series": "comic-trail:14079602755560047206",
                "seriesId": "14079602755560047206",
                "feedKind": "rss",
            },
        )
        client = StaticHttpClient(
            {
                "https://comic-trail.com/rss/series/14079602755560047206": """
                <rss version="2.0">
                  <channel>
                    <title>コミックトレイル（作品E）</title>
                    <item>
                      <title>第3話 新章</title>
                      <link>https://comic-trail.com/episode/2550912965721039352?from=rss</link>
                      <description>作品E</description>
                    </item>
                  </channel>
                </rss>
                """,
                "https://comic-trail.com/episode/2550912965721039352": """
                <html>
                  <head>
                    <title>第3話 新章 / 作品E | コミックトレイル</title>
                  </head>
                  <body>
                    <span class="schedule-label">次回更新：毎月第2金曜</span>
                  </body>
                </html>
                """,
            }
        )

        latest = fetch_latest_for_work(work, http_client=client).to_dict()

        self.assertEqual("comic-trail:14079602755560047206", latest["workId"])
        self.assertEqual("comic-trail:14079602755560047206", latest["series"])
        self.assertEqual("https://comic-trail.com/episode/2550912965721039352", latest["latestKey"])
        self.assertEqual("作品E", latest["seriesTitle"])
        self.assertEqual("第3話 新章", latest["episodeTitle"])
        self.assertEqual("次回更新：毎月第2金曜", latest["nextUpdateLabel"])
        self.assertEqual(
            [
                "https://comic-trail.com/rss/series/14079602755560047206",
                "https://comic-trail.com/episode/2550912965721039352",
            ],
            client.calls,
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

    def test_firecross_normalize_accepts_ebook_series_url(self):
        adapter = ADAPTERS["firecross"]()
        work = adapter.normalize("https://firecross.jp/ebook/series/358?sort=latest")

        self.assertEqual(
            {
                "source": "firecross",
                "kind": "firecross",
                "workId": "firecross:358",
                "seedUrl": "https://firecross.jp/ebook/series/358",
                "series": "firecross:358",
                "seriesId": "358",
                "seriesUrl": "https://firecross.jp/ebook/series/358",
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

    def test_shonenjumpplus_normalize_accepts_series_feed_urls(self):
        adapter = ShonenJumpPlusAdapter()

        rss_work = adapter.normalize("https://shonenjumpplus.com/rss/series/3269754496881854342?from=share")
        atom_work = adapter.normalize("https://shonenjumpplus.com/atom/series/3269754496881854342")

        expected = {
            "source": "shonenjumpplus",
            "kind": "shonenjumpplus",
            "workId": "shonenjumpplus:3269754496881854342",
            "seedUrl": "https://shonenjumpplus.com/rss/series/3269754496881854342",
            "series": "shonenjumpplus:3269754496881854342",
            "seriesId": "3269754496881854342",
            "feedKind": "rss",
        }
        self.assertEqual(expected, rss_work.to_dict())
        self.assertEqual(expected, atom_work.to_dict())

    def test_shonenjumpplus_fetch_latest_accepts_episode_seed(self):
        adapter = ShonenJumpPlusAdapter()
        work = adapter.normalize("https://shonenjumpplus.com/episode/17107419589191805801?from=episode")
        client = StaticHttpClient(
            {
                "https://shonenjumpplus.com/episode/17107419589191805801": """
                <html>
                  <head>
                    <title>[159話]マリッジトキシン - 静脈/依田瑞稀 | 少年ジャンプ＋</title>
                    <link rel="alternate" type="application/rss+xml" title="RSS2.0" href="https://shonenjumpplus.com/rss/series/3269754496881854342">
                  </head>
                  <body>
                    <script id='episode-json' type='text/json' data-value='{"readableProduct":{"nextReadableProductUri":null}}'></script>
                  </body>
                </html>
                """,
                "https://shonenjumpplus.com/rss/series/3269754496881854342": """
                <rss>
                  <channel>
                    <title>少年ジャンプ＋（マリッジトキシン）</title>
                    <item>
                      <title>[159話]マリッジトキシン</title>
                      <link>https://shonenjumpplus.com/episode/17107419589191805801</link>
                      <description>マリッジトキシン</description>
                    </item>
                  </channel>
                </rss>
                """,
            }
        )

        latest = adapter.fetch_latest(work, client).to_dict()

        self.assertEqual("https://shonenjumpplus.com/episode/17107419589191805801", latest["latestKey"])
        self.assertEqual("マリッジトキシン", latest["seriesTitle"])
        self.assertEqual("[159話]マリッジトキシン", latest["episodeTitle"])
        self.assertEqual(
            [
                "https://shonenjumpplus.com/episode/17107419589191805801",
                "https://shonenjumpplus.com/rss/series/3269754496881854342",
                "https://shonenjumpplus.com/episode/17107419589191805801",
            ],
            client.calls,
        )

    def test_comicborder_normalize_accepts_episode_and_feed_urls(self):
        episode_work = normalize_seed_url("https://comicborder.com/episode/12207421983437812169?from=share").to_dict()
        rss_work = normalize_seed_url("https://comicborder.com/rss/series/12207421983437805229?from=share").to_dict()
        atom_work = normalize_seed_url("https://comicborder.com/atom/series/12207421983437805229").to_dict()

        self.assertEqual(
            {
                "source": "comicborder",
                "kind": "comicborder",
                "workId": "https://comicborder.com/episode/12207421983437812169",
                "seedUrl": "https://comicborder.com/episode/12207421983437812169",
            },
            episode_work,
        )

        expected_feed = {
            "source": "comicborder",
            "kind": "comicborder",
            "workId": "comicborder:12207421983437805229",
            "seedUrl": "https://comicborder.com/rss/series/12207421983437805229",
            "series": "comicborder:12207421983437805229",
            "seriesId": "12207421983437805229",
            "feedKind": "rss",
        }
        self.assertEqual(expected_feed, rss_work)
        self.assertEqual(expected_feed, atom_work)

    def test_comicborder_fetch_latest_accepts_canonical_feed_seed(self):
        work = WorkDescriptor(
            source="comicborder",
            work_id="comicborder:12207421983437805229",
            seed_url="https://comicborder.com/rss/series/12207421983437805229",
            metadata={
                "series": "comicborder:12207421983437805229",
                "seriesId": "12207421983437805229",
                "feedKind": "rss",
            },
        )
        client = StaticHttpClient(
            {
                "https://comicborder.com/rss/series/12207421983437805229": """
                <rss version="2.0">
                  <channel>
                    <title>コミックボーダー（マヨネーズ王は貧乏になりたい！【男女比１：１００】世界で逝く勘違い出世街道）</title>
                    <item>
                      <title>第01話 死んでサイタマ　～異世界全方位成り上がりRTA開始（※望んでない）～</title>
                      <link>https://comicborder.com/episode/12207421983437812169</link>
                      <description>マヨネーズ王は貧乏になりたい！【男女比１：１００】世界で逝く勘違い出世街道</description>
                    </item>
                  </channel>
                </rss>
                """,
                "https://comicborder.com/episode/12207421983437812169": """
                <html>
                  <head>
                    <title>マヨネーズ王は貧乏になりたい！【男女比１：１００】世界で逝く勘違い出世街道 - 神影龍之介/馬路まんじ / 第01話 死んでサイタマ　～異世界全方位成り上がりRTA開始（※望んでない）～ | コミックボーダー</title>
                  </head>
                </html>
                """,
            }
        )

        latest = fetch_latest_for_work(work, http_client=client).to_dict()

        self.assertEqual("comicborder:12207421983437805229", latest["workId"])
        self.assertEqual("comicborder:12207421983437805229", latest["series"])
        self.assertEqual("https://comicborder.com/episode/12207421983437812169", latest["latestKey"])
        self.assertEqual("マヨネーズ王は貧乏になりたい！【男女比１：１００】世界で逝く勘違い出世街道", latest["seriesTitle"])
        self.assertEqual("第01話 死んでサイタマ　～異世界全方位成り上がりRTA開始（※望んでない）～", latest["episodeTitle"])
        self.assertEqual(
            [
                "https://comicborder.com/rss/series/12207421983437805229",
                "https://comicborder.com/episode/12207421983437812169",
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

    def test_firecross_fetch_latest_requires_explicit_latest_signal(self):
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
                    <a href="https://firecross.jp/reader/19000">第10話</a>
                    <a href="https://firecross.jp/reader/19420">第13話</a>
                  </body>
                </html>
                """,
            }
        )

        with self.assertRaisesRegex(SourceParseError, "firecross: latest reader URL not found"):
            adapter.fetch_latest(work, client)

    def test_firecross_fetch_latest_accepts_ebook_series_url(self):
        adapter = ADAPTERS["firecross"]()
        work = adapter.normalize("https://firecross.jp/ebook/series/358?sort=latest")
        client = StaticHttpClient(
            {
                "https://firecross.jp/ebook/series/358?sort=latest": """
                <html>
                  <head><title>作品E | ファイアCROSS</title></head>
                  <body>
                    <a href="https://firecross.jp/reader/19420?from=series">第13話</a>
                    <a href="https://firecross.jp/reader/19000">第10話</a>
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
        self.assertEqual("firecross:358", latest["series"])
        self.assertEqual("作品E", latest["seriesTitle"])
        self.assertEqual("第13話", latest["episodeTitle"])
        self.assertEqual(
            [
                "https://firecross.jp/ebook/series/358?sort=latest",
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
