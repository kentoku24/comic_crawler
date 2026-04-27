import unittest

from manga_watch.discord_where import (
    WHERE_COMMAND,
    WHERE_NO_RESULTS_MESSAGE,
    WhereCommandHandler,
)
from manga_watch.source_search import SearchResult


class MultiSourceSearchSource:
    def __init__(self, results_by_source):
        self.results_by_source = {key: list(value) for key, value in results_by_source.items()}
        self.calls = []

    def __call__(self, source, query, *, http_client=None, limit=10):
        self.calls.append(
            {
                "source": source,
                "query": query,
                "http_client": http_client,
                "limit": limit,
            }
        )
        return list(self.results_by_source.get(source, []))


class FakeAvailabilityResolver:
    def __init__(self):
        self.calls = []

    def __call__(self, source, seed_url, episode, *, http_client=None):
        self.calls.append(
            {
                "source": source,
                "seed_url": seed_url,
                "episode": episode,
                "http_client": http_client,
            }
        )
        if source == "comic-walker":
            return {
                "source": source,
                "status": "free_now",
                "url": "https://comic-walker.com/detail/KC_004800_S/episodes/KC_0048000000100012_E",
            }
        if source == "nicovideo-manga":
            return {
                "source": source,
                "status": "free_now",
                "url": "https://manga.nicovideo.jp/watch/mg1000001",
            }
        return {"source": source, "status": "unsupported", "url": None}


class StaticAvailabilityResolver:
    def __init__(self, results_by_source):
        self.results_by_source = dict(results_by_source)
        self.calls = []

    def __call__(self, source, seed_url, episode, *, http_client=None):
        self.calls.append(
            {
                "source": source,
                "seed_url": seed_url,
                "episode": episode,
                "http_client": http_client,
            }
        )
        result = self.results_by_source[source]
        if isinstance(result, Exception):
            raise result
        return result


class DiscordWhereTests(unittest.TestCase):
    def test_where_command_name_is_exported(self):
        self.assertEqual("where", WHERE_COMMAND)

    def test_start_searches_availability_sources_and_returns_select_menu(self):
        search_source = MultiSourceSearchSource(
            {
                "comic-walker": [
                    SearchResult(
                        source="comic-walker",
                        title="ニセモノの錬金術師",
                        seed_url="https://comic-walker.com/detail/KC_004800_S",
                    )
                ],
                "nicovideo-manga": [
                    SearchResult(
                        source="nicovideo-manga",
                        title="ニセモノの錬金術師",
                        seed_url="https://manga.nicovideo.jp/comic/62782",
                    )
                ],
            }
        )
        handler = WhereCommandHandler(search_source=search_source)

        response = handler.start(query="ニセモノの錬金術師", episode="第1話")

        self.assertEqual(
            [
                {"source": "comic-walker", "query": "ニセモノの錬金術師", "http_client": None, "limit": 3},
                {"source": "nicovideo-manga", "query": "ニセモノの錬金術師", "http_client": None, "limit": 3},
            ],
            search_source.calls,
        )
        self.assertIn("候補", response["content"])
        select = response["components"][0]["components"][0]
        self.assertTrue(select["custom_id"].startswith("where_select:"))
        self.assertEqual("availability を確認する作品を選択", select["placeholder"])
        self.assertEqual(
            [
                {
                    "label": "ニセモノの錬金術師",
                    "value": "0",
                    "description": "comic-walker",
                },
                {
                    "label": "ニセモノの錬金術師",
                    "value": "1",
                    "description": "nicovideo-manga",
                },
            ],
            select["options"],
        )

    def test_handle_component_resolves_selected_title_across_availability_sources(self):
        search_source = MultiSourceSearchSource(
            {
                "comic-walker": [
                    SearchResult(
                        source="comic-walker",
                        title="ニセモノの錬金術師",
                        seed_url="https://comic-walker.com/detail/KC_004800_S",
                    )
                ],
                "nicovideo-manga": [
                    SearchResult(
                        source="nicovideo-manga",
                        title="ニセモノの錬金術師",
                        seed_url="https://manga.nicovideo.jp/comic/62782",
                    )
                ],
            }
        )
        resolver = FakeAvailabilityResolver()
        handler = WhereCommandHandler(search_source=search_source, availability_resolver=resolver)
        start_response = handler.start(query="ニセモノの錬金術師", episode="1話")
        select = start_response["components"][0]["components"][0]

        response = handler.handle_component(
            {"custom_id": select["custom_id"], "values": ["0"]},
        )

        self.assertIn("「ニセモノの錬金術師」 第1話", response["content"])
        self.assertIn("ComicWalker: 今すぐ無料", response["content"])
        self.assertIn("https://comic-walker.com/detail/KC_004800_S/episodes/KC_0048000000100012_E", response["content"])
        self.assertIn("ニコニコ漫画: 今すぐ無料", response["content"])
        self.assertIn("https://manga.nicovideo.jp/watch/mg1000001", response["content"])
        self.assertEqual(
            [
                {
                    "source": "comic-walker",
                    "seed_url": "https://comic-walker.com/detail/KC_004800_S",
                    "episode": "1話",
                    "http_client": None,
                },
                {
                    "source": "nicovideo-manga",
                    "seed_url": "https://manga.nicovideo.jp/comic/62782",
                    "episode": "1話",
                    "http_client": None,
                },
            ],
            resolver.calls,
        )

    def test_start_returns_no_results_when_supported_sources_have_no_candidates(self):
        handler = WhereCommandHandler(search_source=MultiSourceSearchSource({}))

        response = handler.start(query="存在しない作品", episode="1話")

        self.assertEqual({"content": WHERE_NO_RESULTS_MESSAGE, "components": []}, response)

    def test_handle_component_renders_not_found_when_episode_is_missing(self):
        search_source = MultiSourceSearchSource(
            {
                "comic-walker": [
                    SearchResult(
                        source="comic-walker",
                        title="ニセモノの錬金術師",
                        seed_url="https://comic-walker.com/detail/KC_004800_S",
                    )
                ],
                "nicovideo-manga": [
                    SearchResult(
                        source="nicovideo-manga",
                        title="ニセモノの錬金術師",
                        seed_url="https://manga.nicovideo.jp/comic/62782",
                    )
                ],
            }
        )
        resolver = StaticAvailabilityResolver(
            {
                "comic-walker": {"source": "comic-walker", "status": "not_found", "url": None},
                "nicovideo-manga": {"source": "nicovideo-manga", "status": "not_found", "url": None},
            }
        )
        handler = WhereCommandHandler(search_source=search_source, availability_resolver=resolver)
        start_response = handler.start(query="ニセモノの錬金術師", episode="第99話")
        select = start_response["components"][0]["components"][0]

        response = handler.handle_component({"custom_id": select["custom_id"], "values": ["0"]})

        self.assertIn("ComicWalker: 見つからない", response["content"])
        self.assertIn("ニコニコ漫画: 見つからない", response["content"])

    def test_handle_component_renders_needs_check_with_seed_url_when_resolution_fails(self):
        search_source = MultiSourceSearchSource(
            {
                "comic-walker": [
                    SearchResult(
                        source="comic-walker",
                        title="ニセモノの錬金術師",
                        seed_url="https://comic-walker.com/detail/KC_004800_S",
                    )
                ],
                "nicovideo-manga": [
                    SearchResult(
                        source="nicovideo-manga",
                        title="ニセモノの錬金術師",
                        seed_url="https://manga.nicovideo.jp/comic/62782",
                    )
                ],
            }
        )
        resolver = StaticAvailabilityResolver(
            {
                "comic-walker": RuntimeError("temporary fetch failure"),
                "nicovideo-manga": {
                    "source": "nicovideo-manga",
                    "status": "free_now",
                    "url": "https://manga.nicovideo.jp/watch/mg1000001",
                },
            }
        )
        handler = WhereCommandHandler(search_source=search_source, availability_resolver=resolver)
        start_response = handler.start(query="ニセモノの錬金術師", episode="第1話")
        select = start_response["components"][0]["components"][0]

        response = handler.handle_component({"custom_id": select["custom_id"], "values": ["0"]})

        self.assertIn("ComicWalker: 要確認", response["content"])
        self.assertIn("https://comic-walker.com/detail/KC_004800_S", response["content"])


if __name__ == "__main__":
    unittest.main()
