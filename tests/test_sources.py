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
from manga_watch.sources.comic_action import ComicActionAdapter
from manga_watch.sources.comic_walker import ComicWalkerAdapter
from manga_watch.sources.kakuyomu import KakuyomuAdapter

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

    def test_registry_pins_supported_sources(self):
        self.assertEqual(
            ("comic-walker", "comic-action", "kakuyomu"),
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
