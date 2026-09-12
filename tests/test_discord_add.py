import json
import tempfile
import unittest
from pathlib import Path

from manga_watch.discord_add import (
    ADD_MISSING_URL_MESSAGE,
    AddCommandHandler,
    UNSUPPORTED_SOURCE_REPORTED_MESSAGE,
    UNSUPPORTED_SOURCE_REPORT_FAILURE_MESSAGE,
)
from manga_watch.watchlist import WatchlistAddError, add_watchlist_url


class DiscordAddTests(unittest.TestCase):
    def test_start_returns_missing_url_message_when_url_is_empty(self):
        handler = AddCommandHandler()

        payload = handler.start(url="  ")

        self.assertEqual(ADD_MISSING_URL_MESSAGE, payload["content"])

    def test_start_formats_added_result(self):
        def add_subscription(url, *, watchlist_path=None):
            self.assertEqual("https://kakuyomu.jp/works/123", url)
            self.assertEqual("watchlist.json", watchlist_path)
            return {
                "action": "added",
                "entry": {
                    "id": "kakuyomu:123",
                    "seed_url": "https://kakuyomu.jp/works/123",
                },
            }

        handler = AddCommandHandler(add_subscription=add_subscription)

        payload = handler.start(
            url="https://kakuyomu.jp/works/123",
            watchlist_path="watchlist.json",
        )

        self.assertIn("追加しました", payload["content"])
        self.assertIn("kakuyomu:123", payload["content"])

    def test_start_formats_duplicate_result(self):
        handler = AddCommandHandler(
            add_subscription=lambda *_args, **_kwargs: {
                "action": "duplicate",
                "entry": {"id": "kakuyomu:123"},
                "existing": {"seed_url": "https://kakuyomu.jp/works/123"},
            }
        )

        payload = handler.start(url="https://kakuyomu.jp/works/123")

        self.assertIn("既に登録済み", payload["content"])

    def test_start_formats_watchlist_error(self):
        def add_subscription(_url, *, watchlist_path=None):
            raise WatchlistAddError(
                "unsupported_source",
                "Unsupported source host: example.com",
                "Use one of the supported sources.",
            )

        handler = AddCommandHandler(add_subscription=add_subscription)

        payload = handler.start(url="https://example.com/work/1")

        self.assertIn("追加できませんでした", payload["content"])
        self.assertIn("Unsupported source host: example.com", payload["content"])

    def test_start_source_and_issue_report_branch_matrix(self):
        def run_accepts_nicovideo_sp_comic_url_via_watchlist_logic(test):
            with tempfile.TemporaryDirectory() as tmpdir:
                watchlist_path = Path(tmpdir) / "watchlist.json"
                watchlist_path.write_text(
                    json.dumps({"version": 2, "works": []}, ensure_ascii=False),
                    encoding="utf-8",
                )

                handler = AddCommandHandler(
                    add_subscription=lambda url, *, watchlist_path=None: add_watchlist_url(
                        url,
                        watchlist_path=watchlist_path,
                    )
                )

                payload = handler.start(
                    url="https://sp.manga.nicovideo.jp/comic/53764?track=share",
                    watchlist_path=str(watchlist_path),
                )

            test.assertIn("追加しました", payload["content"])
            test.assertIn("nicovideo-manga:53764", payload["content"])

        def run_accepts_firecross_reader_url_via_watchlist_logic(test):
            with tempfile.TemporaryDirectory() as tmpdir:
                watchlist_path = Path(tmpdir) / "watchlist.json"
                watchlist_path.write_text(
                    json.dumps({"version": 2, "works": []}, ensure_ascii=False),
                    encoding="utf-8",
                )

                handler = AddCommandHandler(
                    add_subscription=lambda url, *, watchlist_path=None: add_watchlist_url(
                        url,
                        watchlist_path=watchlist_path,
                        http_client=type(
                            "StaticHttpClient",
                            (),
                            {
                                "get_text": lambda self, request_url: {
                                    "https://firecross.jp/reader/19386": """
                                    <html>
                                      <body>
                                        <a href="https://firecross.jp/series/series-abc">作品詳細</a>
                                      </body>
                                    </html>
                                    """
                                }[request_url]
                            },
                        )(),
                    )
                )

                payload = handler.start(
                    url="https://firecross.jp/reader/19386?trial=0&token=temp&vertical=0",
                    watchlist_path=str(watchlist_path),
                )

            test.assertIn("追加しました", payload["content"])
            test.assertIn("firecross:series-abc", payload["content"])

        def run_reports_unsupported_source_to_github_issue(test):
            calls = []

            class FakeIssueReporter:
                def report_unsupported_source(self, *, url, error):
                    calls.append({"url": url, "error": error})
                    return {
                        "action": "created",
                        "issue_number": 174,
                        "issue_url": "https://github.com/kentoku24/comic_crawler/issues/174",
                    }

            def add_subscription(_url, *, watchlist_path=None):
                raise WatchlistAddError(
                    "unsupported_source",
                    "Unsupported source host: example.com",
                    "Use one of the supported sources.",
                )

            handler = AddCommandHandler(
                add_subscription=add_subscription,
                unsupported_source_reporter=FakeIssueReporter(),
            )

            payload = handler.start(url="https://example.com/work/1")

            test.assertEqual("https://example.com/work/1", calls[0]["url"])
            test.assertEqual("unsupported_source", calls[0]["error"].kind)
            test.assertIn("追加できませんでした", payload["content"])
            test.assertIn(UNSUPPORTED_SOURCE_REPORTED_MESSAGE, payload["content"])
            test.assertIn("#174", payload["content"])

        def run_reports_issue_creation_failure_for_unsupported_source(test):
            class FailingIssueReporter:
                def report_unsupported_source(self, *, url, error):
                    raise RuntimeError("GitHub issue creation failed")

            def add_subscription(_url, *, watchlist_path=None):
                raise WatchlistAddError(
                    "unsupported_source",
                    "Unsupported source host: example.com",
                    "Use one of the supported sources.",
                )

            handler = AddCommandHandler(
                add_subscription=add_subscription,
                unsupported_source_reporter=FailingIssueReporter(),
            )

            payload = handler.start(url="https://example.com/work/1")

            test.assertIn("追加できませんでした", payload["content"])
            test.assertIn("Unsupported source host: example.com", payload["content"])
            test.assertIn(UNSUPPORTED_SOURCE_REPORT_FAILURE_MESSAGE, payload["content"])

        def run_does_not_report_supported_source_url_type_errors(test):
            class RecordingIssueReporter:
                def __init__(self):
                    self.calls = 0

                def report_unsupported_source(self, *, url, error):
                    self.calls += 1
                    return {}

            reporter = RecordingIssueReporter()

            def add_subscription(_url, *, watchlist_path=None):
                raise WatchlistAddError(
                    "unsupported_url_type",
                    "comic-action does not support this URL type",
                    "Supported input types for comic-action: episode URL, series feed URL.",
                )

            handler = AddCommandHandler(
                add_subscription=add_subscription,
                unsupported_source_reporter=reporter,
            )

            payload = handler.start(url="https://comic-action.com/series/123")

            test.assertEqual(0, reporter.calls)
            test.assertIn("追加できませんでした", payload["content"])
            test.assertNotIn(UNSUPPORTED_SOURCE_REPORTED_MESSAGE, payload["content"])

        cases = [
            ("nicovideo_sp_comic_url", run_accepts_nicovideo_sp_comic_url_via_watchlist_logic),
            ("firecross_reader_url", run_accepts_firecross_reader_url_via_watchlist_logic),
            ("unsupported_source_reported", run_reports_unsupported_source_to_github_issue),
            ("issue_creation_failure", run_reports_issue_creation_failure_for_unsupported_source),
            ("url_type_error_not_reported", run_does_not_report_supported_source_url_type_errors),
        ]
        for case, run in cases:
            with self.subTest(case=case):
                run(self)


if __name__ == "__main__":
    unittest.main()
