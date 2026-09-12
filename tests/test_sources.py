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
    normalize_seed_url,
)
from manga_watch.sources.bookwalker import BookwalkerAdapter
from manga_watch.sources.base import SourceParseError, WorkDescriptor
from manga_watch.sources.champion_cross import ChampionCrossAdapter
from manga_watch.sources.comic_action import ComicActionAdapter
from manga_watch.sources.comic_trail import parse_comic_trail_title
from manga_watch.sources.comic_walker import ComicWalkerAdapter
from manga_watch.sources.gaugau import GaugauAdapter
from manga_watch.sources.kakuyomu import KakuyomuAdapter
from manga_watch.sources.magapoke import MagapokeAdapter
from manga_watch.sources.nicovideo_manga import NicovideoMangaAdapter
from manga_watch.sources.piccoma import PiccomaAdapter
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
    "comic-earthstar": (
        "normal",
        "broken_missing_series_id",
    ),
    "comicborder": (
        "normal",
        "broken_missing_series_id",
    ),
    "comic-trail": (
        "normal",
        "broken_missing_series_id",
    ),
    "comic-days": (
        "normal",
        "broken_missing_series_id",
    ),
    "kuragebunch": (
        "normal",
        "broken_missing_series_id",
    ),
    "shonenjumpplus": (
        "broken_missing_series_id",
        "normal",
    ),
    "sunday-webry": (
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
    "gaugau": (
        "normal",
    ),
    "piccoma": (
        "normal",
        "broken_missing_episode",
        "broken_missing_episode_list",
    ),
    "bookwalker": (
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
    "comic-earthstar": {
        "normal": "main_story",
    },
    "comicborder": {
        "normal": "main_story",
    },
    "comic-trail": {
        "normal": "main_story",
    },
    "comic-days": {
        "normal": "unknown",
    },
    "kuragebunch": {
        "normal": "main_story",
    },
    "shonenjumpplus": {
        "normal": "main_story",
    },
    "sunday-webry": {
        "normal": "unknown",
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
    "gaugau": {
        "normal": "main_story",
    },
    "piccoma": {
        "normal": "main_story",
    },
    "bookwalker": {
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
        body = self.responses[url]
        if isinstance(body, Exception):
            raise body
        return body


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
                "comic-earthstar",
                "comicborder",
                "comic-trail",
                "comic-days",
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

    def test_comic_earthstar_fixtures(self):
        self._assert_fixture_matrix("comic-earthstar")

    def test_comicborder_fixtures(self):
        self._assert_fixture_matrix("comicborder")

    def test_sunday_webry_fixtures(self):
        self._assert_fixture_matrix("sunday-webry")

    def test_comic_trail_fixtures(self):
        self._assert_fixture_matrix("comic-trail")

    def test_comic_days_fixtures(self):
        self._assert_fixture_matrix("comic-days")

    def test_kuragebunch_fixtures(self):
        self._assert_fixture_matrix("kuragebunch")

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

    def test_gaugau_fixtures(self):
        self._assert_fixture_matrix("gaugau")

    def test_piccoma_fixtures(self):
        self._assert_fixture_matrix("piccoma")

    def test_piccoma_normalize_accepts_product_url(self):
        work = PiccomaAdapter().normalize("https://piccoma.com/web/product/58170?etype=episode")

        self.assertEqual(
            {
                "source": "piccoma",
                "kind": "piccoma",
                "workId": "piccoma:58170",
                "seedUrl": "https://piccoma.com/web/product/58170?etype=episode",
                "series": "piccoma:58170",
                "productId": "58170",
            },
            work.to_dict(),
        )

    def test_piccoma_normalize_canonicalizes_query_variants(self):
        work = PiccomaAdapter().normalize("https://piccoma.com/web/product/58170?foo=bar")

        self.assertEqual("https://piccoma.com/web/product/58170?etype=episode", work.seed_url)

    def test_bookwalker_fixtures(self):
        self._assert_fixture_matrix("bookwalker")

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

    def test_feed_family_normalize_and_canonicalize_matrix(self):
        family = (
            {
                "source": "comic-earthstar",
                "episode_input": "https://comic-earthstar.com/episode/12207421983526541742?from=share",
                "episode_url": "https://comic-earthstar.com/episode/12207421983526541742",
                "rss_input": "https://comic-earthstar.com/rss/series/12207421983526538413?from=share",
                "atom_input": "https://comic-earthstar.com/atom/series/12207421983526538413",
                "rss_url": "https://comic-earthstar.com/rss/series/12207421983526538413",
                "series_id": "12207421983526538413",
                "canonical_input": "https://comic-earthstar.com/episode/12207421983526541742?from=share",
                "normalize_cases": ("episode", "rss", "atom"),
            },
            {
                "source": "comicborder",
                "episode_input": "https://comicborder.com/episode/12207421983437812169?from=share",
                "episode_url": "https://comicborder.com/episode/12207421983437812169",
                "rss_input": "https://comicborder.com/rss/series/12207421983437805229?from=share",
                "atom_input": "https://comicborder.com/atom/series/12207421983437805229",
                "rss_url": "https://comicborder.com/rss/series/12207421983437805229",
                "series_id": "12207421983437805229",
                "canonical_input": "https://comicborder.com/episode/12207421983437812169?from=share",
                "normalize_cases": ("episode", "rss", "atom"),
            },
            {
                "source": "comic-trail",
                "episode_input": "https://comic-trail.com/episode/2550689798402927313?from=share",
                "episode_url": "https://comic-trail.com/episode/2550689798402927313",
                "rss_input": "https://comic-trail.com/rss/series/14079602755560047206?from=share",
                "atom_input": "https://comic-trail.com/atom/series/14079602755560047206?from=share",
                "rss_url": "https://comic-trail.com/rss/series/14079602755560047206",
                "series_id": "14079602755560047206",
                "canonical_input": "https://comic-trail.com/episode/2550689798402927313?from=share",
                "normalize_cases": ("episode", "rss", "atom"),
            },
            {
                "source": "comic-days",
                "episode_url": "https://comic-days.com/episode/12207421983746014850",
                "rss_url": "https://comic-days.com/rss/series/13933686331650127004",
                "series_id": "13933686331650127004",
                "canonical_input": "https://comic-days.com/episode/12207421983746014850?from=share",
                "normalize_cases": (),
            },
            {
                "source": "kuragebunch",
                "episode_input": "https://kuragebunch.com/episode/2550912964856491139?from=share",
                "episode_url": "https://kuragebunch.com/episode/2550912964856491139",
                "rss_input": "https://kuragebunch.com/rss/series/2550912964856487532?from=share",
                "atom_input": "https://kuragebunch.com/atom/series/2550912964856487532",
                "rss_url": "https://kuragebunch.com/rss/series/2550912964856487532",
                "series_id": "2550912964856487532",
                "canonical_input": "https://kuragebunch.com/episode/2550912964856491139?from=share",
                "normalize_cases": ("episode", "rss", "atom"),
            },
            {
                "source": "shonenjumpplus",
                "episode_url": "https://shonenjumpplus.com/episode/17107419589191805801",
                "rss_url": "https://shonenjumpplus.com/rss/series/3269754496881854342",
                "series_id": "3269754496881854342",
                "canonical_input": "https://shonenjumpplus.com/episode/17107419589191805801?from=episode",
                "normalize_cases": (),
            },
            {
                "source": "sunday-webry",
                "episode_input": "https://www.sunday-webry.com/episode/12207421983581042977?from=share",
                "episode_url": "https://www.sunday-webry.com/episode/12207421983581042977",
                "rss_input": "https://www.sunday-webry.com/rss/series/12207421983580960894?from=share",
                "atom_input": "https://www.sunday-webry.com/atom/series/12207421983580960894",
                "rss_url": "https://www.sunday-webry.com/rss/series/12207421983580960894",
                "series_id": "12207421983580960894",
                "canonical_input": "https://www.sunday-webry.com/episode/12207421983581042977?from=episode",
                "normalize_cases": ("episode", "rss", "atom"),
            },
        )

        for entry in family:
            source = entry["source"]
            expected_episode = {
                "source": source,
                "kind": source,
                "workId": entry["episode_url"],
                "seedUrl": entry["episode_url"],
            }
            expected_feed = {
                "source": source,
                "kind": source,
                "workId": f"{source}:{entry['series_id']}",
                "seedUrl": entry["rss_url"],
                "series": f"{source}:{entry['series_id']}",
                "seriesId": entry["series_id"],
                "feedKind": "rss",
            }
            inputs = {
                "episode": entry.get("episode_input"),
                "rss": entry.get("rss_input"),
                "atom": entry.get("atom_input"),
            }
            for case in (*entry["normalize_cases"], "canonicalize"):
                with self.subTest(source=source, case=case):
                    if case == "canonicalize":
                        item = normalize_seed_url(entry["canonical_input"]).to_dict()
                        client = StaticHttpClient(
                            {
                                item["seedUrl"]: (
                                    "<html><head>"
                                    f'<link rel="alternate" type="application/rss+xml" href="{entry["rss_url"]}">'
                                    "</head></html>"
                                ),
                            }
                        )
                        descriptor = ADAPTERS[source]().canonicalize_item(item, client).to_dict()

                        self.assertEqual(
                            normalize_seed_url(entry["rss_url"]).to_dict(),
                            descriptor,
                        )
                        self.assertEqual([item["seedUrl"]], client.calls)
                    elif case == "episode":
                        self.assertEqual(
                            expected_episode,
                            normalize_seed_url(inputs[case]).to_dict(),
                        )
                    else:
                        self.assertEqual(
                            expected_feed,
                            normalize_seed_url(inputs[case]).to_dict(),
                        )

    def _assert_fetch_cases(self, cases):
        for entry in cases:
            source = entry["source"]
            with self.subTest(source=source, case=entry["case"]):
                adapter = ADAPTERS[source]()
                if "work" in entry:
                    work_id, seed_url, metadata = entry["work"]
                    work = WorkDescriptor(
                        source=source,
                        work_id=work_id,
                        seed_url=seed_url,
                        metadata=metadata,
                    )
                else:
                    work = adapter.normalize(entry["seed_url"])
                client = StaticHttpClient(entry["responses"])
                expected_error = entry.get("expected_error")
                if expected_error is not None:
                    with self.assertRaisesRegex(SourceParseError, re.escape(expected_error)):
                        adapter.fetch_latest(work, client)
                else:
                    latest = adapter.fetch_latest(work, client).to_dict()
                    for key, value in entry.get("expected_latest", {}).items():
                        self.assertEqual(value, latest[key])
                    for key in entry.get("missing_latest_keys", ()):
                        self.assertNotIn(key, latest)
                    if "expected_calls" in entry:
                        self.assertEqual(entry["expected_calls"], client.calls)

    def test_feed_family_fetch_latest_matrix(self):
        self._assert_fetch_cases(
            (
                {
                    "source": "comic-trail",
                    "case": "canonical_feed_seed",
                    "work": (
                        "comic-trail:14079602755560047206",
                        "https://comic-trail.com/rss/series/14079602755560047206",
                        {
                            "series": "comic-trail:14079602755560047206",
                            "seriesId": "14079602755560047206",
                            "feedKind": "rss",
                        },
                    ),
                    "responses": {
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
                    },
                    "expected_latest": {
                        "workId": "comic-trail:14079602755560047206",
                        "series": "comic-trail:14079602755560047206",
                        "latestKey": "https://comic-trail.com/episode/2550912965721039352",
                        "seriesTitle": "作品E",
                        "episodeTitle": "第3話 新章",
                        "nextUpdateLabel": "次回更新：毎月第2金曜",
                    },
                    "expected_calls": [
                        "https://comic-trail.com/rss/series/14079602755560047206",
                        "https://comic-trail.com/episode/2550912965721039352",
                    ],
                },
                {
                    "source": "shonenjumpplus",
                    "case": "backfills_series_title_from_page_title",
                    "work": (
                        "shonenjumpplus:3269754496881854342",
                        "https://shonenjumpplus.com/rss/series/3269754496881854342",
                        {
                            "series": "shonenjumpplus:3269754496881854342",
                            "seriesId": "3269754496881854342",
                            "feedKind": "rss",
                        },
                    ),
                    "responses": {
                        "https://shonenjumpplus.com/rss/series/3269754496881854342": """
                        <rss version="2.0">
                          <channel>
                            <title>少年ジャンプ＋</title>
                            <item>
                              <title>[159話]マリッジトキシン</title>
                              <link>https://shonenjumpplus.com/episode/17107419589191805801</link>
                            </item>
                          </channel>
                        </rss>
                        """,
                        "https://shonenjumpplus.com/episode/17107419589191805801": """
                        <html>
                          <head>
                            <title>[159話]マリッジトキシン - 静脈/依田瑞稀 | 少年ジャンプ＋</title>
                          </head>
                        </html>
                        """,
                    },
                    "expected_latest": {
                        "seriesTitle": "マリッジトキシン",
                        "episodeTitle": "[159話]マリッジトキシン",
                    },
                },
                {
                    "source": "shonenjumpplus",
                    "case": "episode_seed",
                    "seed_url": "https://shonenjumpplus.com/episode/17107419589191805801?from=episode",
                    "responses": {
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
                    },
                    "expected_latest": {
                        "latestKey": "https://shonenjumpplus.com/episode/17107419589191805801",
                        "seriesTitle": "マリッジトキシン",
                        "episodeTitle": "[159話]マリッジトキシン",
                    },
                    "expected_calls": [
                        "https://shonenjumpplus.com/episode/17107419589191805801",
                        "https://shonenjumpplus.com/rss/series/3269754496881854342",
                        "https://shonenjumpplus.com/episode/17107419589191805801",
                    ],
                },
                {
                    "source": "comic-earthstar",
                    "case": "canonical_feed_seed",
                    "work": (
                        "comic-earthstar:12207421983526538413",
                        "https://comic-earthstar.com/rss/series/12207421983526538413",
                        {
                            "series": "comic-earthstar:12207421983526538413",
                            "seriesId": "12207421983526538413",
                            "feedKind": "rss",
                        },
                    ),
                    "responses": {
                        "https://comic-earthstar.com/rss/series/12207421983526538413": """
                        <rss version="2.0">
                          <channel>
                            <title>コミック アース・スター｜毎週木曜・最新話更新！無料で漫画が読めるWEBコミック誌（魔物（マンドラゴラ）ってバレたら討伐ですか？ ～花の魔女のほほえみは勘違いの種を蒔く～）</title>
                            <item>
                              <title>第2話②</title>
                              <link>https://comic-earthstar.com/episode/12207421983562435589</link>
                              <description>魔物（マンドラゴラ）ってバレたら討伐ですか？ ～花の魔女のほほえみは勘違いの種を蒔く～</description>
                            </item>
                          </channel>
                        </rss>
                        """,
                        "https://comic-earthstar.com/episode/12207421983562435589": """
                        <html>
                          <head>
                            <title>第2話② / 魔物（マンドラゴラ）ってバレたら討伐ですか？ ～花の魔女のほほえみは勘違いの種を蒔く～ - 漫画：大林ポチ子/原作：Mikura/キャラクター原案：中西達哉 | コミック アース・スター</title>
                          </head>
                        </html>
                        """,
                    },
                    "expected_latest": {
                        "workId": "comic-earthstar:12207421983526538413",
                        "series": "comic-earthstar:12207421983526538413",
                        "latestKey": "https://comic-earthstar.com/episode/12207421983562435589",
                        "seriesTitle": "魔物（マンドラゴラ）ってバレたら討伐ですか？ ～花の魔女のほほえみは勘違いの種を蒔く～",
                        "episodeTitle": "第2話②",
                    },
                    "expected_calls": [
                        "https://comic-earthstar.com/rss/series/12207421983526538413",
                        "https://comic-earthstar.com/episode/12207421983562435589",
                    ],
                },
                {
                    "source": "comic-earthstar",
                    "case": "nested_parentheses_in_series_title_fallback",
                    "work": (
                        "comic-earthstar:12207421983526538413",
                        "https://comic-earthstar.com/rss/series/12207421983526538413",
                        {
                            "series": "comic-earthstar:12207421983526538413",
                            "seriesId": "12207421983526538413",
                            "feedKind": "rss",
                        },
                    ),
                    "responses": {
                        "https://comic-earthstar.com/rss/series/12207421983526538413": """
                        <rss version="2.0">
                          <channel>
                            <title>コミック アース・スター｜毎週木曜・最新話更新！無料で漫画が読めるWEBコミック誌（魔物（マンドラゴラ）ってバレたら討伐ですか？ ～花の魔女のほほえみは勘違いの種を蒔く～）</title>
                            <item>
                              <title>第2話②</title>
                              <link>https://comic-earthstar.com/episode/12207421983562435589</link>
                            </item>
                          </channel>
                        </rss>
                        """,
                        "https://comic-earthstar.com/episode/12207421983562435589": """
                        <html>
                          <head>
                            <title>第2話② / 魔物（マンドラゴラ）ってバレたら討伐ですか？ ～花の魔女のほほえみは勘違いの種を蒔く～ - 漫画：大林ポチ子/原作：Mikura/キャラクター原案：中西達哉 | コミック アース・スター</title>
                          </head>
                        </html>
                        """,
                    },
                    "expected_latest": {
                        "latestKey": "https://comic-earthstar.com/episode/12207421983562435589",
                        "episodeTitle": "第2話②",
                        "seriesTitle": "魔物（マンドラゴラ）ってバレたら討伐ですか？ ～花の魔女のほほえみは勘違いの種を蒔く～",
                    },
                },
                {
                    "source": "comicborder",
                    "case": "canonical_feed_seed",
                    "work": (
                        "comicborder:12207421983437805229",
                        "https://comicborder.com/rss/series/12207421983437805229",
                        {
                            "series": "comicborder:12207421983437805229",
                            "seriesId": "12207421983437805229",
                            "feedKind": "rss",
                        },
                    ),
                    "responses": {
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
                    },
                    "expected_latest": {
                        "workId": "comicborder:12207421983437805229",
                        "series": "comicborder:12207421983437805229",
                        "latestKey": "https://comicborder.com/episode/12207421983437812169",
                        "seriesTitle": "マヨネーズ王は貧乏になりたい！【男女比１：１００】世界で逝く勘違い出世街道",
                        "episodeTitle": "第01話 死んでサイタマ　～異世界全方位成り上がりRTA開始（※望んでない）～",
                    },
                    "expected_calls": [
                        "https://comicborder.com/rss/series/12207421983437805229",
                        "https://comicborder.com/episode/12207421983437812169",
                    ],
                },
                {
                    "source": "sunday-webry",
                    "case": "episode_seed",
                    "seed_url": "https://www.sunday-webry.com/episode/12207421983581042977?from=episode",
                    "responses": {
                        "https://www.sunday-webry.com/episode/12207421983581042977": """
                        <html>
                          <head>
                            <title>diary1 つきこと先生 / しっぽと逆鱗 - 由田果 | サンデーうぇぶり</title>
                            <link rel="alternate" type="application/atom+xml" title="Atom" href="https://www.sunday-webry.com/atom/series/12207421983580960894">
                            <link rel="alternate" type="application/rss+xml" title="RSS2.0" href="https://www.sunday-webry.com/rss/series/12207421983580960894">
                          </head>
                          <body>
                            <script id="episode-json" type="text/json" data-value='{&quot;readableProduct&quot;:{&quot;series&quot;:{&quot;id&quot;:&quot;12207421983580960894&quot;},&quot;nextReadableProductUri&quot;:null}}'></script>
                          </body>
                        </html>
                        """,
                        "https://www.sunday-webry.com/rss/series/12207421983580960894": """
                        <rss version="2.0">
                          <channel>
                            <title>サンデーうぇぶり（しっぽと逆鱗）</title>
                            <item>
                              <title>diary1 つきこと先生</title>
                              <link>https://www.sunday-webry.com/episode/12207421983581042977</link>
                              <description>しっぽと逆鱗</description>
                            </item>
                          </channel>
                        </rss>
                        """,
                    },
                    "expected_latest": {
                        "workId": "sunday-webry:12207421983580960894",
                        "series": "sunday-webry:12207421983580960894",
                        "latestKey": "https://www.sunday-webry.com/episode/12207421983581042977",
                        "seriesTitle": "しっぽと逆鱗",
                        "episodeTitle": "diary1 つきこと先生",
                        "pageTitle": "diary1 つきこと先生 / しっぽと逆鱗 - 由田果 | サンデーうぇぶり",
                    },
                    "expected_calls": [
                        "https://www.sunday-webry.com/episode/12207421983581042977",
                        "https://www.sunday-webry.com/rss/series/12207421983580960894",
                    ],
                },
                {
                    "source": "sunday-webry",
                    "case": "stale_episode_seed_uses_latest_page_title",
                    "seed_url": "https://www.sunday-webry.com/episode/12207421983581042977?from=episode",
                    "responses": {
                        "https://www.sunday-webry.com/episode/12207421983581042977": """
                        <html>
                          <head>
                            <title>diary1 つきこと先生 / しっぽと逆鱗 - 由田果 | サンデーうぇぶり</title>
                            <link rel="alternate" type="application/rss+xml" title="RSS2.0" href="https://www.sunday-webry.com/rss/series/12207421983580960894">
                          </head>
                          <body>
                            <script id="episode-json" type="text/json" data-value='{&quot;readableProduct&quot;:{&quot;series&quot;:{&quot;id&quot;:&quot;12207421983580960894&quot;}}}'></script>
                          </body>
                        </html>
                        """,
                        "https://www.sunday-webry.com/rss/series/12207421983580960894": """
                        <rss version="2.0">
                          <channel>
                            <title>サンデーうぇぶり（しっぽと逆鱗）</title>
                            <item>
                              <title></title>
                              <link>https://www.sunday-webry.com/episode/12207421983581043001</link>
                              <description></description>
                            </item>
                          </channel>
                        </rss>
                        """,
                        "https://www.sunday-webry.com/episode/12207421983581043001": """
                        <html>
                          <head>
                            <title>diary2 新しい話 / しっぽと逆鱗 - 由田果 | サンデーうぇぶり</title>
                          </head>
                          <body></body>
                        </html>
                        """,
                    },
                    "expected_latest": {
                        "latestKey": "https://www.sunday-webry.com/episode/12207421983581043001",
                        "episodeTitle": "diary2 新しい話",
                        "seriesTitle": "しっぽと逆鱗",
                        "pageTitle": "diary2 新しい話 / しっぽと逆鱗 - 由田果 | サンデーうぇぶり",
                    },
                    "expected_calls": [
                        "https://www.sunday-webry.com/episode/12207421983581042977",
                        "https://www.sunday-webry.com/rss/series/12207421983580960894",
                        "https://www.sunday-webry.com/episode/12207421983581043001",
                    ],
                },
                {
                    "source": "kuragebunch",
                    "case": "canonical_feed_seed",
                    "work": (
                        "kuragebunch:2550912964856487532",
                        "https://kuragebunch.com/rss/series/2550912964856487532",
                        {
                            "series": "kuragebunch:2550912964856487532",
                            "seriesId": "2550912964856487532",
                            "feedKind": "rss",
                        },
                    ),
                    "responses": {
                        "https://kuragebunch.com/rss/series/2550912964856487532": """
                        <rss version="2.0">
                          <channel>
                            <title>くらげバンチ（赤と青のガウン）</title>
                            <item>
                              <title>第15話</title>
                              <link>https://kuragebunch.com/episode/12207421983430264919</link>
                              <description>赤と青のガウン</description>
                            </item>
                          </channel>
                        </rss>
                        """,
                        "https://kuragebunch.com/episode/12207421983430264919": """
                        <html>
                          <head>
                            <title>赤と青のガウン - 彬子女王/池辺葵 / 第15話 | くらげバンチ</title>
                          </head>
                        </html>
                        """,
                    },
                    "expected_latest": {
                        "workId": "kuragebunch:2550912964856487532",
                        "series": "kuragebunch:2550912964856487532",
                        "latestKey": "https://kuragebunch.com/episode/12207421983430264919",
                        "seriesTitle": "赤と青のガウン",
                        "episodeTitle": "第15話",
                    },
                    "expected_calls": [
                        "https://kuragebunch.com/rss/series/2550912964856487532",
                        "https://kuragebunch.com/episode/12207421983430264919",
                    ],
                },
            ),
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

    def test_parse_comic_trail_title_strips_author_suffix_from_live_title_shape(self):
        page_title = (
            "Pain.1 僕の好きな人 / 僕の彼女は春を売る - 後藤ねぎ | "
            "コミックトレイル｜漫画とつながるフェス空間！"
        )

        self.assertEqual(
            ("Pain.1 僕の好きな人", "僕の彼女は春を売る"),
            parse_comic_trail_title(page_title),
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
        cases = (
            (
                "https://championcross.jp/series/abc123/rss?ref=top",
                {
                    "source": "champion-cross",
                    "kind": "champion-cross",
                    "workId": "champion-cross:abc123",
                    "seedUrl": "https://championcross.jp/series/abc123/rss",
                    "series": "champion-cross:abc123",
                    "seriesHash": "abc123",
                    "feedKind": "rss",
                },
            ),
            (
                "https://championcross.jp/series/4756324e1c1b1/rss?from=share",
                {
                    "source": "champion-cross",
                    "kind": "champion-cross",
                    "workId": "champion-cross:4756324e1c1b1",
                    "seedUrl": "https://championcross.jp/series/4756324e1c1b1/rss",
                    "series": "champion-cross:4756324e1c1b1",
                    "seriesHash": "4756324e1c1b1",
                    "feedKind": "rss",
                },
            ),
        )

        for query, expected in cases:
            with self.subTest(query=query):
                work = ChampionCrossAdapter().normalize(query)

                self.assertEqual(expected, work.to_dict())

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

    def test_comic_action_fetch_latest_matrix(self):
        self._assert_fetch_cases(
            (
                {
                    "source": "comic-action",
                    "case": "series_feed_seed",
                    "seed_url": "https://comic-action.com/atom/series/13933686331606207128",
                    "responses": {
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
                    },
                    "expected_latest": {
                        "workId": "comic-action:13933686331606207128",
                        "latestKey": "https://comic-action.com/episode/11341664176570134078",
                        "seriesTitle": "つぐもも",
                        "episodeTitle": "第1話 母さんの形見",
                    },
                    "expected_calls": [
                        "https://comic-action.com/atom/series/13933686331606207128",
                        "https://comic-action.com/episode/11341664176570134078",
                    ],
                },
                {
                    "source": "comic-action",
                    "case": "next_update_label_from_latest_page",
                    "seed_url": "https://comic-action.com/episode/111",
                    "responses": {
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
                    },
                    "expected_latest": {
                        "nextUpdateLabel": "4月3日",
                    },
                },
                {
                    "source": "comic-action",
                    "case": "series_rss_fallback_when_readable_chain_stops",
                    "seed_url": "https://comic-action.com/episode/2550689798784879524",
                    "responses": {
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
                    },
                    "expected_latest": {
                        "latestKey": "https://comic-action.com/episode/2551460910007760899",
                        "seriesTitle": "ダンジョンの中のひと",
                        "episodeTitle": "第51話",
                        "nextUpdateLabel": "4月4日",
                    },
                    "expected_calls": [
                        "https://comic-action.com/episode/2550689798784879524",
                        "https://comic-action.com/rss/series/13933686331663374228",
                        "https://comic-action.com/episode/2551460910007760899",
                    ],
                },
                {
                    "source": "comic-action",
                    "case": "entry_episode_when_series_rss_fetch_fails",
                    "seed_url": "https://comic-action.com/episode/2550689798784879524",
                    "responses": {
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
                        "https://comic-action.com/rss/series/13933686331663374228": RuntimeError(
                            "temporary feed outage"
                        ),
                    },
                    "expected_latest": {
                        "latestKey": "https://comic-action.com/episode/2550689798784879524",
                        "seriesTitle": "ダンジョンの中のひと",
                        "episodeTitle": "第39話",
                    },
                    "expected_calls": [
                        "https://comic-action.com/episode/2550689798784879524",
                        "https://comic-action.com/rss/series/13933686331663374228",
                    ],
                },
                {
                    "source": "comic-action",
                    "case": "entry_episode_when_series_rss_is_stale",
                    "seed_url": "https://comic-action.com/episode/2550689798784879524",
                    "responses": {
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
                    },
                    "expected_latest": {
                        "latestKey": "https://comic-action.com/episode/2550689798784879524",
                        "seriesTitle": "ダンジョンの中のひと",
                        "episodeTitle": "第39話",
                    },
                    "expected_calls": [
                        "https://comic-action.com/episode/2550689798784879524",
                        "https://comic-action.com/rss/series/13933686331663374228",
                        "https://comic-action.com/episode/2551460909780695609",
                    ],
                },
                {
                    "source": "comic-action",
                    "case": "www_episode_links_from_feed",
                    "seed_url": "https://comic-action.com/rss/series/13933686331606207128",
                    "responses": {
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
                    },
                    "expected_latest": {
                        "workId": "comic-action:13933686331606207128",
                        "latestKey": "https://comic-action.com/episode/11341664176570134078",
                    },
                    "expected_calls": [
                        "https://comic-action.com/rss/series/13933686331606207128",
                        "https://comic-action.com/episode/11341664176570134078",
                    ],
                },
            ),
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

    def test_kakuyomu_fetch_latest_matrix(self):
        self._assert_fetch_cases(
            (
                {
                    "source": "kakuyomu",
                    "case": "next_update_label_from_schedule",
                    "seed_url": "https://kakuyomu.jp/works/123",
                    "responses": {
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
                    },
                    "expected_latest": {
                        "nextUpdateLabel": "毎日 12:08",
                    },
                },
                {
                    "source": "kakuyomu",
                    "case": "null_schedule",
                    "seed_url": "https://kakuyomu.jp/works/123",
                    "responses": {
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
                    },
                    "missing_latest_keys": ("nextUpdateLabel",),
                },
            ),
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

    def test_firecross_fetch_latest_matrix(self):
        self._assert_fetch_cases(
            (
                {
                    "source": "firecross",
                    "case": "reader_seed",
                    "seed_url": "https://firecross.jp/reader/19386?trial=0&token=temp",
                    "responses": {
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
                    },
                    "expected_latest": {
                        "latestKey": "https://firecross.jp/reader/19420",
                        "url": "https://firecross.jp/reader/19420",
                        "series": "firecross:series-abc",
                        "seriesTitle": "作品E",
                        "episodeTitle": "第13話",
                    },
                    "expected_calls": [
                        "https://firecross.jp/reader/19386",
                        "https://firecross.jp/series/series-abc",
                        "https://firecross.jp/reader/19420",
                    ],
                },
                {
                    "source": "firecross",
                    "case": "requires_explicit_latest_signal",
                    "seed_url": "https://firecross.jp/reader/19386?trial=0&token=temp",
                    "responses": {
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
                    },
                    "expected_error": "firecross: latest reader URL not found",
                },
                {
                    "source": "firecross",
                    "case": "ebook_series_seed",
                    "seed_url": "https://firecross.jp/ebook/series/358?sort=latest",
                    "responses": {
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
                    },
                    "expected_latest": {
                        "latestKey": "https://firecross.jp/reader/19420",
                        "url": "https://firecross.jp/reader/19420",
                        "series": "firecross:358",
                        "seriesTitle": "作品E",
                        "episodeTitle": "第13話",
                    },
                    "expected_calls": [
                        "https://firecross.jp/ebook/series/358?sort=latest",
                        "https://firecross.jp/reader/19420",
                    ],
                },
            ),
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

    def test_gaugau_normalize_accepts_work_url(self):
        work = GaugauAdapter().normalize("https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000?from=search")

        self.assertEqual(
            {
                "source": "gaugau",
                "kind": "gaugau",
                "workId": "gaugau:600a5fd37765610d30010000",
                "seedUrl": "https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000",
                "series": "gaugau:600a5fd37765610d30010000",
                "workToken": "600a5fd37765610d30010000",
            },
            work.to_dict(),
        )

    def test_gaugau_fetch_latest_prefers_first_episode_grid_entry_over_earlier_misc_link(self):
        adapter = GaugauAdapter()
        work = adapter.normalize("https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000")
        client = StaticHttpClient(
            {
                "https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000": """
                <html>
                  <head><title>公式-ダンジョンの中のひと | 作品詳細 | がうがうモンスター＋</title></head>
                  <body>
                    <h1>ダンジョンの中のひと</h1>
                    <div class="hero">
                      <a href="https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000/episodes/1">
                        古い導線
                      </a>
                    </div>
                    <div class="episode__grid">
                      <a href="https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000/episodes/99">
                        <div class="episode__num">第51話(2)</div>
                      </a>
                    </div>
                    <div class="episode__grid">
                      <a href="https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000/episodes/5">
                        <div class="episode__num">第5話</div>
                      </a>
                    </div>
                  </body>
                </html>
                """,
                "https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000/episodes/99": """
                <html>
                  <head>
                    <title>公式-ダンジョンの中のひと 第51話(2) | 無料・試し読み豊富、Web漫画・コミックサイト がうがうモンスター＋</title>
                  </head>
                  <body></body>
                </html>
                """,
            }
        )

        latest = adapter.fetch_latest(work, client).to_dict()

        self.assertEqual("gaugau:600a5fd37765610d30010000", latest["workId"])
        self.assertEqual(
            "https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000/episodes/99",
            latest["latestKey"],
        )
        self.assertEqual("ダンジョンの中のひと", latest["seriesTitle"])
        self.assertEqual("第51話(2)", latest["episodeTitle"])
        self.assertEqual(
            [
                "https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000",
                "https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000/episodes/99",
            ],
            client.calls,
        )

    def test_bookwalker_normalize_accepts_series_and_product_urls(self):
        adapter = BookwalkerAdapter()

        self.assertEqual(
            {
                "source": "bookwalker",
                "kind": "bookwalker",
                "workId": "bookwalker:series:519222",
                "seedUrl": "https://bookwalker.jp/series/519222/list/",
                "series": "bookwalker:series:519222",
                "seriesId": "519222",
            },
            adapter.normalize("https://bookwalker.jp/series/519222/list/?order=release").to_dict(),
        )
        self.assertEqual(
            {
                "source": "bookwalker",
                "kind": "bookwalker",
                "workId": "bookwalker:series:559081",
                "seedUrl": "https://bookwalker.jp/series/559081/",
                "series": "bookwalker:series:559081",
                "seriesId": "559081",
            },
            adapter.normalize("https://bookwalker.jp/series/559081/").to_dict(),
        )
        self.assertEqual(
            {
                "source": "bookwalker",
                "kind": "bookwalker",
                "workId": "bookwalker:book:2b0ecd13-4ad0-405e-9fe9-a625ad80c74c",
                "seedUrl": "https://bookwalker.jp/de2b0ecd13-4ad0-405e-9fe9-a625ad80c74c/",
                "bookUuid": "2b0ecd13-4ad0-405e-9fe9-a625ad80c74c",
            },
            adapter.normalize("https://bookwalker.jp/de2b0ecd13-4ad0-405e-9fe9-a625ad80c74c/?sample=1").to_dict(),
        )

    def test_bookwalker_fetch_latest_matrix(self):
        self._assert_fetch_cases(
            (
                {
                    "source": "bookwalker",
                    "case": "latest_series_card",
                    "seed_url": "https://bookwalker.jp/series/519222/list/",
                    "responses": {
                        "https://bookwalker.jp/series/519222/list/": """
                        <html>
                          <head><title>くまぐらし（MANGAバル コミックス）一覧 - BOOK☆WALKER</title></head>
                          <body>
                            <article class="m-book-item">
                              <a href="https://bookwalker.jp/de893cb2ba-dc87-4c1b-90cb-a1cd13d33a0f/"
                                 class="m-book-item__title"
                                 title="くまぐらし　（０６）">くまぐらし　（０６）</a>
                              <time datetime="2026-05-14 00:00">2026/5/14(木)</time> 配信予定
                            </article>
                            <article class="m-book-item">
                              <a href="https://bookwalker.jp/de2b0ecd13-4ad0-405e-9fe9-a625ad80c74c/"
                                 class="m-book-item__title"
                                 title="くまぐらし　（０５）">くまぐらし　（０５）</a>
                            </article>
                          </body>
                        </html>
                        """
                    },
                    "expected_latest": {
                        "workId": "bookwalker:series:519222",
                        "series": "bookwalker:series:519222",
                        "latestKey": "bookwalker:book:893cb2ba-dc87-4c1b-90cb-a1cd13d33a0f",
                        "seriesTitle": "くまぐらし（MANGAバル コミックス）",
                        "episodeTitle": "くまぐらし （０６）",
                        "nextUpdateLabel": "2026/5/14(木) 配信予定",
                    },
                    "expected_calls": ["https://bookwalker.jp/series/519222/list/"],
                },
                {
                    "source": "bookwalker",
                    "case": "wauri_series_episode_titles",
                    "seed_url": "https://bookwalker.jp/series/559081/",
                    "responses": {
                        "https://bookwalker.jp/series/559081/": """
                        <html>
                          <head><title>【話・連載】救世のアルル【分冊版】（ノヴァコミックス） - BOOK☆WALKER</title></head>
                          <body>
                            <p class="p-top-block__update">2026/3/25(水) 更新</p>
                            <a data-ga-category="話読みタブリスト"
                               data-book-uuid="7702b31c-c3c4-4382-804a-05a4461133db"
                               data-book-title="&#x6551;&#x4E16;&#x306E;&#x30A2;&#x30EB;&#x30EB;&#x3010;&#x5206;&#x518A;&#x7248;&#x3011;1">
                              <h3 class="o-ttsk-list-item__title">1</h3>
                            </a>
                            <a data-ga-category="話読みタブリスト"
                               data-book-uuid="b5c239d6-7f48-4d79-b2ee-c0fb0e481a35"
                               data-book-title="&#x6551;&#x4E16;&#x306E;&#x30A2;&#x30EB;&#x30EB;&#x3010;&#x5206;&#x518A;&#x7248;&#x3011;8">
                              <h3 class="o-ttsk-list-item__title">8</h3>
                            </a>
                          </body>
                        </html>
                        """
                    },
                    "expected_latest": {
                        "workId": "bookwalker:series:559081",
                        "latestKey": "bookwalker:book:b5c239d6-7f48-4d79-b2ee-c0fb0e481a35",
                        "seriesTitle": "救世のアルル【分冊版】（ノヴァコミックス）",
                        "episodeTitle": "救世のアルル【分冊版】8",
                        "url": "https://bookwalker.jp/deb5c239d6-7f48-4d79-b2ee-c0fb0e481a35/",
                        "nextUpdateLabel": "2026/3/25(水) 更新",
                    },
                },
            ),
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
