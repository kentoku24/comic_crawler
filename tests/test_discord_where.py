from pathlib import Path
import tempfile
import unittest

from manga_watch.discord_where import (
    StoredWhereContextStore,
    WHERE_COMMAND,
    WHERE_NO_RESULTS_MESSAGE,
    WhereCommandHandler,
)
from manga_watch.availability import supported_availability_sources
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


class FailingSourceSearchSource(MultiSourceSearchSource):
    def __init__(self, results_by_source, failing_sources):
        super().__init__(results_by_source)
        self.failing_sources = set(failing_sources)

    def __call__(self, source, query, *, http_client=None, limit=10):
        if source in self.failing_sources:
            raise RuntimeError(f"{source} search failed")
        return super().__call__(source, query, http_client=http_client, limit=limit)


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

        self.assertEqual(list(supported_availability_sources()), [call["source"] for call in search_source.calls])
        self.assertTrue(
            all(
                {
                    "query": "ニセモノの錬金術師",
                    "http_client": None,
                    "limit": 3,
                }.items()
                <= call.items()
                for call in search_source.calls
            )
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

    def test_handle_component_uses_selected_candidate_when_same_source_titles_collide(self):
        search_source = MultiSourceSearchSource(
            {
                "comic-walker": [
                    SearchResult(
                        source="comic-walker",
                        title="同名作品",
                        seed_url="https://comic-walker.com/detail/first",
                    ),
                    SearchResult(
                        source="comic-walker",
                        title="同名作品",
                        seed_url="https://comic-walker.com/detail/selected",
                    ),
                ],
                "nicovideo-manga": [
                    SearchResult(
                        source="nicovideo-manga",
                        title="同名作品",
                        seed_url="https://manga.nicovideo.jp/comic/selected",
                    )
                ],
            }
        )
        resolver = FakeAvailabilityResolver()
        handler = WhereCommandHandler(search_source=search_source, availability_resolver=resolver)
        start_response = handler.start(query="同名作品", episode="1話")
        select = start_response["components"][0]["components"][0]

        handler.handle_component({"custom_id": select["custom_id"], "values": ["1"]})

        self.assertEqual("https://comic-walker.com/detail/selected", resolver.calls[0]["seed_url"])
        self.assertEqual("https://manga.nicovideo.jp/comic/selected", resolver.calls[1]["seed_url"])

    def test_handle_component_loads_context_from_storage_across_handler_instances(self):
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
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = str(Path(tmpdir) / "state.json")
            first_handler = WhereCommandHandler(
                search_source=search_source,
                context_store=StoredWhereContextStore(state_path=state_path, backend="json"),
            )
            start_response = first_handler.start(query="ニセモノの錬金術師", episode="1話")
            select = start_response["components"][0]["components"][0]
            second_handler = WhereCommandHandler(
                availability_resolver=resolver,
                context_store=StoredWhereContextStore(state_path=state_path, backend="json"),
            )

            response = second_handler.handle_component(
                {"custom_id": select["custom_id"], "values": ["0"]},
            )

        self.assertIn("ComicWalker: 今すぐ無料", response["content"])
        self.assertIn("ニコニコ漫画: 今すぐ無料", response["content"])
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

    def test_handle_component_deletes_storage_context_after_selection(self):
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
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = str(Path(tmpdir) / "state.json")
            handler = WhereCommandHandler(
                search_source=search_source,
                availability_resolver=resolver,
                context_store=StoredWhereContextStore(state_path=state_path, backend="json"),
            )
            start_response = handler.start(query="ニセモノの錬金術師", episode="1話")
            select = start_response["components"][0]["components"][0]

            first_response = handler.handle_component({"custom_id": select["custom_id"], "values": ["0"]})
            second_response = handler.handle_component({"custom_id": select["custom_id"], "values": ["0"]})

        self.assertIn("ComicWalker: 今すぐ無料", first_response["content"])
        self.assertIn("有効期限が切れた", second_response["content"])

    def test_start_generates_unique_context_token_for_identical_searches(self):
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
        handler = WhereCommandHandler(search_source=search_source, availability_resolver=FakeAvailabilityResolver())
        first_response = handler.start(query="ニセモノの錬金術師", episode="1話")
        second_response = handler.start(query="ニセモノの錬金術師", episode="1話")
        first_select = first_response["components"][0]["components"][0]
        second_select = second_response["components"][0]["components"][0]

        self.assertNotEqual(first_select["custom_id"], second_select["custom_id"])

        first_result = handler.handle_component({"custom_id": first_select["custom_id"], "values": ["0"]})
        second_result = handler.handle_component({"custom_id": second_select["custom_id"], "values": ["0"]})

        self.assertIn("ComicWalker: 今すぐ無料", first_result["content"])
        self.assertIn("ComicWalker: 今すぐ無料", second_result["content"])

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

    def test_handle_component_renders_needs_check_for_failed_source_search(self):
        search_source = FailingSourceSearchSource(
            {
                "nicovideo-manga": [
                    SearchResult(
                        source="nicovideo-manga",
                        title="ニセモノの錬金術師",
                        seed_url="https://manga.nicovideo.jp/comic/62782",
                    )
                ],
            },
            failing_sources={"comic-walker"},
        )
        resolver = FakeAvailabilityResolver()
        handler = WhereCommandHandler(search_source=search_source, availability_resolver=resolver)
        start_response = handler.start(query="ニセモノの錬金術師", episode="1話")
        select = start_response["components"][0]["components"][0]

        response = handler.handle_component({"custom_id": select["custom_id"], "values": ["0"]})

        self.assertIn("ComicWalker: 要確認", response["content"])
        self.assertIn("ニコニコ漫画: 今すぐ無料", response["content"])
        self.assertEqual(
            [
                {
                    "source": "nicovideo-manga",
                    "seed_url": "https://manga.nicovideo.jp/comic/62782",
                    "episode": "1話",
                    "http_client": None,
                }
            ],
            resolver.calls,
        )

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

    def test_handle_component_renders_needs_check_for_unimplemented_source_candidate(self):
        search_source = MultiSourceSearchSource(
            {
                "bookwalker": [
                    SearchResult(
                        source="bookwalker",
                        title="くまぐらし",
                        seed_url="https://bookwalker.jp/series/519222/list/",
                    )
                ],
            }
        )
        handler = WhereCommandHandler(search_source=search_source)
        start_response = handler.start(query="くまぐらし", episode="第1話")
        select = start_response["components"][0]["components"][0]

        response = handler.handle_component({"custom_id": select["custom_id"], "values": ["0"]})

        self.assertIn("BOOK☆WALKER: 要確認", response["content"])
        self.assertIn("https://bookwalker.jp/series/519222/list/", response["content"])

    def test_handle_component_renders_needs_check_with_seed_url_for_uncertain_result(self):
        search_source = MultiSourceSearchSource(
            {
                "piccoma": [
                    SearchResult(
                        source="piccoma",
                        title="くまぐらし",
                        seed_url="https://piccoma.com/web/product/123",
                    )
                ],
            }
        )
        resolver = StaticAvailabilityResolver(
            {
                "piccoma": {
                    "source": "piccoma",
                    "status": "needs_check",
                    "url": "https://piccoma.com/web/product/123",
                },
            }
        )
        handler = WhereCommandHandler(
            search_source=search_source,
            availability_resolver=resolver,
            availability_sources=lambda: ("piccoma",),
        )
        start_response = handler.start(query="くまぐらし", episode="第1話")
        select = start_response["components"][0]["components"][0]

        response = handler.handle_component({"custom_id": select["custom_id"], "values": ["0"]})

        self.assertIn("ピッコマ: 要確認", response["content"])
        self.assertIn("https://piccoma.com/web/product/123", response["content"])
        self.assertNotIn("ピッコマ: 見つからない", response["content"])


if __name__ == "__main__":
    unittest.main()
