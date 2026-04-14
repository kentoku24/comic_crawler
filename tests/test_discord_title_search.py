import unittest

from manga_watch.discord_title_search import TITLE_COMMAND, TITLE_USAGE_MESSAGE, handle_title_query


class RecordingSearchSource:
    def __init__(self):
        self.calls = []

    def __call__(self, source, query, *, limit=10, http_client=None):
        self.calls.append(
            {
                "source": source,
                "query": query,
                "limit": limit,
                "http_client": http_client,
            }
        )
        return []


class PartiallyFailingSearchSource:
    def __init__(self):
        self.calls = []

    def __call__(self, source, query, *, limit=10, http_client=None):
        self.calls.append(
            {
                "source": source,
                "query": query,
                "limit": limit,
                "http_client": http_client,
            }
        )
        if source == "comic-walker":
            raise RuntimeError("timeout")
        return []


class DiscordTitleSearchTests(unittest.TestCase):
    def test_title_command_name_is_exported(self):
        self.assertEqual("title", TITLE_COMMAND)

    def test_handle_title_query_returns_none_for_non_title_messages(self):
        self.assertIsNone(handle_title_query("latest"))
        self.assertIsNone(handle_title_query("titleworks"))

    def test_handle_title_query_returns_usage_for_empty_query(self):
        self.assertEqual(TITLE_USAGE_MESSAGE, handle_title_query("title"))
        self.assertEqual(TITLE_USAGE_MESSAGE, handle_title_query(" title   "))

    def test_handle_title_query_calls_supported_sources_with_query(self):
        search_source = RecordingSearchSource()

        response = handle_title_query(
            "title ダンジョン飯",
            search_source_fn=search_source,
            supported_sources_fn=lambda: ("comic-walker", "magapoke"),
        )

        self.assertEqual(
            [
                {
                    "source": "comic-walker",
                    "query": "ダンジョン飯",
                    "limit": 1,
                    "http_client": None,
                },
                {
                    "source": "magapoke",
                    "query": "ダンジョン飯",
                    "limit": 1,
                    "http_client": None,
                },
            ],
            search_source.calls,
        )
        self.assertEqual("`ダンジョン飯` の title 検索を開始しました。対象媒体数: 2", response)

    def test_handle_title_query_ignores_source_failures_in_skeleton_mode(self):
        search_source = PartiallyFailingSearchSource()

        response = handle_title_query(
            "title ダンジョン飯",
            search_source_fn=search_source,
            supported_sources_fn=lambda: ("comic-walker", "magapoke"),
        )

        self.assertEqual(
            [
                {
                    "source": "comic-walker",
                    "query": "ダンジョン飯",
                    "limit": 1,
                    "http_client": None,
                },
                {
                    "source": "magapoke",
                    "query": "ダンジョン飯",
                    "limit": 1,
                    "http_client": None,
                },
            ],
            search_source.calls,
        )
        self.assertEqual("`ダンジョン飯` の title 検索を開始しました。対象媒体数: 2", response)


if __name__ == "__main__":
    unittest.main()
