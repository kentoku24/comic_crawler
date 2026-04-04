import os
import unittest
from unittest import mock

from manga_watch.watchlist import WatchlistAddError


class FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        return self._json_data


class FakeRequestsSession:
    def __init__(self, get_responses=None, post_responses=None):
        self.get_responses = list(get_responses or [])
        self.post_responses = list(post_responses or [])
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        if not self.get_responses:
            raise AssertionError("unexpected GET")
        return self.get_responses.pop(0)

    def post(self, url, **kwargs):
        self.post_calls.append({"url": url, **kwargs})
        if not self.post_responses:
            raise AssertionError("unexpected POST")
        return self.post_responses.pop(0)


class GitHubIssueReportingTests(unittest.TestCase):
    def test_build_reporter_from_env_returns_none_when_unconfigured(self):
        from manga_watch.github_issue_reporting import build_unsupported_source_issue_reporter_from_env

        with mock.patch.dict(os.environ, {}, clear=True):
            reporter = build_unsupported_source_issue_reporter_from_env()

        self.assertIsNone(reporter)

    def test_build_reporter_from_env_returns_none_when_only_token_is_present(self):
        from manga_watch.github_issue_reporting import build_unsupported_source_issue_reporter_from_env

        with mock.patch.dict(
            os.environ,
            {
                "MANGA_WATCH_GITHUB_TOKEN": "github-token",
            },
            clear=True,
        ):
            reporter = build_unsupported_source_issue_reporter_from_env()

        self.assertIsNone(reporter)

    def test_build_reporter_from_env_returns_none_when_only_repository_is_present(self):
        from manga_watch.github_issue_reporting import build_unsupported_source_issue_reporter_from_env

        with mock.patch.dict(
            os.environ,
            {
                "MANGA_WATCH_GITHUB_REPOSITORY": "kentoku24/comic_crawler",
            },
            clear=True,
        ):
            reporter = build_unsupported_source_issue_reporter_from_env()

        self.assertIsNone(reporter)

    def test_report_unsupported_source_creates_issue(self):
        from manga_watch.github_issue_reporting import GitHubIssueReporter, GitHubIssueReporterConfig

        session = FakeRequestsSession(
            get_responses=[FakeResponse(status_code=200, json_data=[])],
            post_responses=[
                FakeResponse(
                    status_code=201,
                    json_data={
                        "number": 174,
                        "html_url": "https://github.com/kentoku24/comic_crawler/issues/174",
                    },
                )
            ],
        )
        reporter = GitHubIssueReporter(
            GitHubIssueReporterConfig(
                token="github-token",
                repository="kentoku24/comic_crawler",
            ),
            session=session,
        )

        outcome = reporter.report_unsupported_source(
            url="https://example.com/work/1",
            error=WatchlistAddError(
                "unsupported_source",
                "Unsupported source host: example.com",
                "Use one of the supported sources.",
            ),
        )

        self.assertEqual("created", outcome["action"])
        self.assertEqual(174, outcome["issue_number"])
        self.assertEqual(1, len(session.get_calls))
        self.assertEqual(1, len(session.post_calls))
        self.assertIn("/repos/kentoku24/comic_crawler/issues", session.post_calls[0]["url"])
        self.assertEqual(
            "Bearer github-token",
            session.post_calls[0]["headers"]["Authorization"],
        )
        self.assertIn("https://example.com/work/1", session.post_calls[0]["json"]["body"])

    def test_report_unsupported_source_redacts_query_and_userinfo_from_issue_body(self):
        from manga_watch.github_issue_reporting import GitHubIssueReporter, GitHubIssueReporterConfig

        session = FakeRequestsSession(
            get_responses=[FakeResponse(status_code=200, json_data=[])],
            post_responses=[
                FakeResponse(
                    status_code=201,
                    json_data={
                        "number": 174,
                        "html_url": "https://github.com/kentoku24/comic_crawler/issues/174",
                    },
                )
            ],
        )
        reporter = GitHubIssueReporter(
            GitHubIssueReporterConfig(
                token="github-token",
                repository="kentoku24/comic_crawler",
            ),
            session=session,
        )

        reporter.report_unsupported_source(
            url="https://user:pass@example.com:443/work/1?token=secret#frag",
            error=WatchlistAddError(
                "unsupported_source",
                "Unsupported source host: example.com",
                "Use one of the supported sources.",
            ),
        )

        body = session.post_calls[0]["json"]["body"]
        self.assertIn("- Input URL: `https://example.com/work/1`", body)
        self.assertNotIn("user:pass", body)
        self.assertNotIn("token=secret", body)
        self.assertNotIn(":443", body)

    def test_report_unsupported_source_reuses_existing_open_issue(self):
        from manga_watch.github_issue_reporting import GitHubIssueReporter, GitHubIssueReporterConfig

        session = FakeRequestsSession(
            get_responses=[
                FakeResponse(
                    status_code=200,
                    json_data=[
                        {
                            "number": 175,
                            "html_url": "https://github.com/kentoku24/comic_crawler/issues/175",
                            "title": "Unsupported source request from Discord /add: example.com",
                            "body": (
                                "<!-- unsupported-source-request -->\n"
                                "- Input URL: `https://example.com/work/1`\n"
                                "- Host: `example.com`\n"
                            ),
                        }
                    ],
                )
            ],
        )
        reporter = GitHubIssueReporter(
            GitHubIssueReporterConfig(
                token="github-token",
                repository="kentoku24/comic_crawler",
            ),
            session=session,
        )

        outcome = reporter.report_unsupported_source(
            url="https://example.com/work/1",
            error=WatchlistAddError(
                "unsupported_source",
                "Unsupported source host: example.com",
                "Use one of the supported sources.",
            ),
        )

        self.assertEqual("duplicate", outcome["action"])
        self.assertEqual(175, outcome["issue_number"])
        self.assertEqual(1, len(session.get_calls))
        self.assertEqual(0, len(session.post_calls))

    def test_report_unsupported_source_deduplicates_by_hostname_without_port(self):
        from manga_watch.github_issue_reporting import GitHubIssueReporter, GitHubIssueReporterConfig

        session = FakeRequestsSession(
            get_responses=[
                FakeResponse(
                    status_code=200,
                    json_data=[
                        {
                            "number": 175,
                            "html_url": "https://github.com/kentoku24/comic_crawler/issues/175",
                            "title": "Unsupported source request from Discord /add: example.com",
                            "body": (
                                "<!-- unsupported-source-request -->\n"
                                "- Input URL: `https://example.com/work/1`\n"
                                "- Host: `example.com`\n"
                            ),
                        }
                    ],
                )
            ],
        )
        reporter = GitHubIssueReporter(
            GitHubIssueReporterConfig(
                token="github-token",
                repository="kentoku24/comic_crawler",
            ),
            session=session,
        )

        outcome = reporter.report_unsupported_source(
            url="https://example.com:443/work/1?token=secret",
            error=WatchlistAddError(
                "unsupported_source",
                "Unsupported source host: example.com",
                "Use one of the supported sources.",
            ),
        )

        self.assertEqual("duplicate", outcome["action"])
        self.assertEqual(175, outcome["issue_number"])
        self.assertEqual(0, len(session.post_calls))

    def test_build_reporter_from_env_uses_namespaced_token_and_repository(self):
        from manga_watch.github_issue_reporting import build_unsupported_source_issue_reporter_from_env

        with mock.patch.dict(
            os.environ,
            {
                "MANGA_WATCH_GITHUB_TOKEN": "github-token",
                "MANGA_WATCH_GITHUB_REPOSITORY": "kentoku24/comic_crawler",
            },
            clear=True,
        ):
            reporter = build_unsupported_source_issue_reporter_from_env()

        self.assertIsNotNone(reporter)
        self.assertEqual("kentoku24/comic_crawler", reporter.config.repository)


if __name__ == "__main__":
    unittest.main()
