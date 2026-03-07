import importlib
import inspect
import pkgutil
import unittest

import manga_watch.sources as sources_package
from manga_watch.sources.base import SourceAdapter
from manga_watch.sources.comic_action import ComicActionAdapter
from manga_watch.sources.comic_walker import ComicWalkerAdapter
from manga_watch.sources.kakuyomu import KakuyomuAdapter
from manga_watch.sources.registry import DEFAULT_ADAPTERS, REGISTERED_ADAPTER_TYPES


class FakeHttpClient:
    def __init__(self, pages):
        self.pages = pages

    def get_text(self, url: str) -> str:
        return self.pages[url]


def discover_adapter_types():
    discovered = {}

    for module_info in pkgutil.iter_modules(sources_package.__path__):
        if module_info.name in {"base", "registry", "util"}:
            continue

        module = importlib.import_module(f"{sources_package.__name__}.{module_info.name}")
        for _, adapter_type in inspect.getmembers(module, inspect.isclass):
            if adapter_type is SourceAdapter:
                continue
            if not issubclass(adapter_type, SourceAdapter):
                continue
            if inspect.isabstract(adapter_type):
                continue
            if adapter_type.__module__ != module.__name__:
                continue
            if adapter_type.source in discovered:
                raise AssertionError(f"duplicate adapter source registered in modules: {adapter_type.source}")
            discovered[adapter_type.source] = adapter_type

    return discovered


class SourceAdapterTests(unittest.TestCase):
    def test_registry_contract_covers_all_source_adapter_modules(self):
        discovered = discover_adapter_types()
        registered = {adapter_type.source: adapter_type for adapter_type in REGISTERED_ADAPTER_TYPES}

        self.assertEqual(discovered, registered)
        self.assertEqual(
            tuple(registered.keys()),
            tuple(adapter.source for adapter in DEFAULT_ADAPTERS),
        )

    def test_comic_walker_adapter_fetches_latest_episode_from_fixture(self):
        adapter = ComicWalkerAdapter()
        seed_url = "https://comic-walker.com/detail/KC_123456_S/episodes/KC_123456001_E"
        work = adapter.normalize(seed_url)

        latest_url = "https://comic-walker.com/detail/KC_123456_S/episodes/KC_123456003_E?episodeType=latest"
        client = FakeHttpClient(
            {
                "https://comic-walker.com/detail/KC_123456_S": (
                    '<script id="__NEXT_DATA__" type="application/json">'
                    '{"episodeCodes":["KC_123456001_E","KC_123456003_E"]}'
                    "</script>"
                ),
                latest_url: "<title>【第3話】作品A｜カドコミ (コミックウォーカー)</title>",
            }
        )

        latest = adapter.fetch_latest(work, client)

        self.assertEqual("comic-walker", work.source)
        self.assertEqual("KC_123456_S", work.work_id)
        self.assertEqual("KC_123456003_E", latest.latest_key)
        self.assertEqual("作品A", latest.series_title)
        self.assertEqual("第3話", latest.episode_title)

    def test_comic_action_adapter_follows_next_readable_chain(self):
        adapter = ComicActionAdapter()
        seed_url = "https://comic-action.com/episode/111"
        work = adapter.normalize(seed_url)
        latest_url = "https://comic-action.com/episode/222"
        client = FakeHttpClient(
            {
                seed_url: 'nextReadableProductUri":"https://comic-action.com/episode/222"',
                latest_url: "<title>第2話 / 作品B - webアクション | comic-action</title>",
            }
        )

        latest = adapter.fetch_latest(work, client)

        self.assertEqual("comic-action", work.source)
        self.assertEqual(seed_url, work.work_id)
        self.assertEqual(latest_url, latest.latest_key)
        self.assertEqual("作品B", latest.series_title)
        self.assertEqual("第2話", latest.episode_title)

    def test_kakuyomu_adapter_fetches_latest_episode_from_fixture(self):
        adapter = KakuyomuAdapter()
        seed_url = "https://kakuyomu.jp/works/123/episodes/456"
        work = adapter.normalize(seed_url)
        work_url = "https://kakuyomu.jp/works/123"
        latest_url = "https://kakuyomu.jp/works/123/episodes/789"
        client = FakeHttpClient(
            {
                work_url: (
                    '<script id="__NEXT_DATA__" type="application/json">'
                    '{"Episode:456":{"id":"456","title":"第1話","publishedAt":"2025-01-01T00:00:00Z"},'
                    '"Episode:789":{"id":"789","title":"第2話","publishedAt":"2025-02-01T00:00:00Z"}}'
                    "</script>"
                ),
                latest_url: "<title>第2話 - 作品C - カクヨム</title>",
            }
        )

        latest = adapter.fetch_latest(work, client)

        self.assertEqual("kakuyomu", work.source)
        self.assertEqual("kakuyomu:123", work.work_id)
        self.assertEqual("789", latest.latest_key)
        self.assertEqual("作品C", latest.series_title)
        self.assertEqual("第2話", latest.episode_title)


if __name__ == "__main__":
    unittest.main()
