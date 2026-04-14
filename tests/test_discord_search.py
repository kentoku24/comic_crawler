import unittest

from manga_watch.discord_search import (
    SEARCH_COMMAND,
    SEARCH_MISSING_SOURCE_MESSAGE,
    SEARCH_NO_RESULTS_MESSAGE,
    SearchCommandHandler,
)
from manga_watch.source_search import SearchResult


class FakeSearchSource:
    def __init__(self, results):
        self.results = list(results)
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
        return list(self.results)


class FakeAddSubscription:
    def __init__(self):
        self.calls = []

    def __call__(self, url, *, watchlist_path=None, hidden=False):
        self.calls.append(
            {
                "url": url,
                "watchlist_path": watchlist_path,
                "hidden": hidden,
            }
        )
        return {
            "action": "added",
            "entry": {
                "id": "champion-cross:e349a3791821b",
                "seed_url": url,
                "hidden": hidden,
            },
            "work_count": 1,
        }


class DiscordSearchTests(unittest.TestCase):
    def test_search_command_name_is_exported(self):
        self.assertEqual("search", SEARCH_COMMAND)

    def test_start_returns_ephemeral_select_menu_for_results(self):
        search_source = FakeSearchSource(
            [
                SearchResult(
                    source="champion-cross",
                    title="酒井美羽の少女まんが戦記",
                    seed_url="https://championcross.jp/series/e349a3791821b",
                    subtitle="champion-cross",
                ),
                SearchResult(
                    source="champion-cross",
                    title="別の作品",
                    seed_url="https://championcross.jp/series/aaaaaaaaaaaaa",
                    subtitle="champion-cross",
                ),
            ]
        )
        handler = SearchCommandHandler(search_source=search_source)

        response = handler.start(
            source="champion-cross",
            query="まんが",
            visibility="hidden",
            watchlist_path="/tmp/watchlist.json",
        )

        self.assertEqual(
            {
                "source": "champion-cross",
                "query": "まんが",
                "http_client": None,
                "limit": 10,
            },
            search_source.calls[0],
        )
        self.assertIn("検索結果", response["content"])
        self.assertEqual("search_select:hidden", response["components"][0]["components"][0]["custom_id"])
        self.assertEqual(
            [
                {
                    "label": "酒井美羽の少女まんが戦記",
                    "value": "https://championcross.jp/series/e349a3791821b",
                    "description": "champion-cross",
                },
                {
                    "label": "別の作品",
                    "value": "https://championcross.jp/series/aaaaaaaaaaaaa",
                    "description": "champion-cross",
                },
            ],
            response["components"][0]["components"][0]["options"],
        )

    def test_start_truncates_option_text_and_tokenizes_long_urls(self):
        long_title = "作品" + "あ" * 120
        long_subtitle = "説明" + "い" * 120
        long_url = "https://example.com/" + "x" * 180
        search_source = FakeSearchSource(
            [
                SearchResult(
                    source="champion-cross",
                    title=long_title,
                    seed_url=long_url,
                    subtitle=long_subtitle,
                )
            ]
        )
        add_subscription = FakeAddSubscription()
        handler = SearchCommandHandler(search_source=search_source, add_subscription=add_subscription)

        response = handler.start(source="champion-cross", query="長い", watchlist_path="/tmp/watchlist.json")
        option = response["components"][0]["components"][0]["options"][0]

        self.assertLessEqual(len(option["label"]), 100)
        self.assertLessEqual(len(option["value"]), 100)
        self.assertLessEqual(len(option["description"]), 100)
        self.assertNotEqual(long_url, option["value"])
        self.assertTrue(option["value"].startswith("u:"))

        add_response = handler.handle_component(
            {"custom_id": "search_select:visible", "values": [option["value"]]},
            watchlist_path="/tmp/watchlist.json",
        )

        self.assertEqual(
            [
                {
                    "url": long_url,
                    "watchlist_path": "/tmp/watchlist.json",
                    "hidden": False,
                }
            ],
            add_subscription.calls,
        )
        self.assertIn(long_url, add_response["content"])

    def test_start_accepts_missing_source_without_old_error(self):
        search_source = FakeSearchSource([])
        handler = SearchCommandHandler(search_source=search_source)

        response = handler.start(source=None, query="まんが")

        self.assertEqual({"content": SEARCH_NO_RESULTS_MESSAGE, "components": []}, response)
        self.assertNotEqual(SEARCH_MISSING_SOURCE_MESSAGE, response["content"])
        self.assertEqual([], search_source.calls)

    def test_handle_component_adds_selected_result_with_hidden_flag(self):
        add_subscription = FakeAddSubscription()
        handler = SearchCommandHandler(
            search_source=lambda *_args, **_kwargs: [],
            add_subscription=add_subscription,
        )

        response = handler.handle_component(
            {"custom_id": "search_select:hidden", "values": ["https://championcross.jp/series/e349a3791821b"]},
            watchlist_path="/tmp/watchlist.json",
        )

        self.assertEqual(
            [
                {
                    "url": "https://championcross.jp/series/e349a3791821b",
                    "watchlist_path": "/tmp/watchlist.json",
                    "hidden": True,
                }
            ],
            add_subscription.calls,
        )
        self.assertIn("非表示", response["content"])

    def test_handle_component_rejects_stale_tokenized_url(self):
        add_subscription = FakeAddSubscription()
        handler = SearchCommandHandler(
            search_source=lambda *_args, **_kwargs: [],
            add_subscription=add_subscription,
        )

        response = handler.handle_component(
            {"custom_id": "search_select:visible", "values": ["u:stale-token"]},
            watchlist_path="/tmp/watchlist.json",
        )

        self.assertEqual([], add_subscription.calls)
        self.assertIn("選択された作品URLが見つかりませんでした", response["content"])


if __name__ == "__main__":
    unittest.main()
