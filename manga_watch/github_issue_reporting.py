from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Mapping, Optional, Protocol
from urllib.parse import urlparse

import requests

from manga_watch.secret_redaction import redact_secret_text
from manga_watch.secret_resolver import resolve_env_value
from manga_watch.watchlist import WatchlistAddError

DEFAULT_GITHUB_API_BASE_URL = "https://api.github.com"
DEFAULT_GITHUB_TIMEOUT = 15
UNSUPPORTED_SOURCE_ISSUE_MARKER = "<!-- unsupported-source-request -->"
UNSUPPORTED_SOURCE_ISSUE_TITLE_PREFIX = "Unsupported source request from Discord /add"


def _coerce_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class RequestsSession(Protocol):
    def get(self, url: str, **kwargs): ...

    def post(self, url: str, **kwargs): ...


@dataclass(frozen=True)
class GitHubIssueReporterConfig:
    token: str
    repository: str
    api_base_url: str = DEFAULT_GITHUB_API_BASE_URL
    timeout: int = DEFAULT_GITHUB_TIMEOUT

    @classmethod
    def from_env(
        cls,
        *,
        secret_resolver: Callable[[str], Optional[str]] = resolve_env_value,
    ) -> "GitHubIssueReporterConfig":
        token = secret_resolver("MANGA_WATCH_GITHUB_TOKEN")
        if not token:
            raise ValueError(
                "MANGA_WATCH_GITHUB_TOKEN or MANGA_WATCH_GITHUB_TOKEN_SECRET_VERSION is required"
            )
        repository = _coerce_text(
            os.environ.get("MANGA_WATCH_GITHUB_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY")
        )
        if not repository:
            raise ValueError("MANGA_WATCH_GITHUB_REPOSITORY is required")
        api_base_url = (_coerce_text(os.environ.get("MANGA_WATCH_GITHUB_API_BASE_URL")) or DEFAULT_GITHUB_API_BASE_URL).rstrip("/")
        return cls(
            token=token,
            repository=repository,
            api_base_url=api_base_url,
        )


def build_unsupported_source_issue_reporter_from_env(
    *,
    secret_resolver: Callable[[str], Optional[str]] = resolve_env_value,
    session: RequestsSession = requests,
) -> Optional["GitHubIssueReporter"]:
    token = secret_resolver("MANGA_WATCH_GITHUB_TOKEN")
    repository = _coerce_text(
        os.environ.get("MANGA_WATCH_GITHUB_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY")
    )
    if token is None and repository is None:
        return None
    return GitHubIssueReporter(
        GitHubIssueReporterConfig.from_env(secret_resolver=secret_resolver),
        session=session,
    )


def build_unsupported_source_issue_title(host: str) -> str:
    return f"{UNSUPPORTED_SOURCE_ISSUE_TITLE_PREFIX}: {host}"


def build_unsupported_source_issue_body(
    *,
    url: str,
    host: str,
    error: WatchlistAddError,
    reported_at: str,
) -> str:
    return "\n".join(
        [
            UNSUPPORTED_SOURCE_ISSUE_MARKER,
            "## Unsupported Source Request",
            f"- Input URL: `{url}`",
            f"- Host: `{host}`",
            "- Requested from: Discord `/add`",
            f"- Requested at: `{reported_at}`",
            f"- Add error: `{error.message}`",
            "",
            "## Requested Outcome",
            "- Add formal source support so this URL can be accepted by `watchlist add` and Discord `/add`.",
        ]
    )


class GitHubIssueReporter:
    def __init__(
        self,
        config: GitHubIssueReporterConfig,
        *,
        session: RequestsSession = requests,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.config = config
        self.session = session
        self.now = now

    def report_unsupported_source(
        self,
        *,
        url: str,
        error: WatchlistAddError,
    ) -> Dict[str, object]:
        host = urlparse(url).netloc.lower()
        title = build_unsupported_source_issue_title(host)
        existing = self._find_existing_open_issue(url=url, host=host, title=title)
        if existing is not None:
            return existing

        reported_at = self.now().astimezone(timezone.utc).replace(microsecond=0).isoformat()
        body = build_unsupported_source_issue_body(
            url=url,
            host=host,
            error=error,
            reported_at=reported_at,
        )
        response = self._request(
            "post",
            f"{self.config.api_base_url}/repos/{self.config.repository}/issues",
            json={
                "title": title,
                "body": body,
            },
        )
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise RuntimeError("GitHub issue creation returned unexpected response")
        issue_number = payload.get("number")
        issue_url = _coerce_text(payload.get("html_url"))
        if not issue_number or not issue_url:
            raise RuntimeError("GitHub issue creation returned no issue number or URL")
        return {
            "action": "created",
            "issue_number": int(issue_number),
            "issue_url": issue_url,
        }

    def _find_existing_open_issue(
        self,
        *,
        url: str,
        host: str,
        title: str,
    ) -> Optional[Dict[str, object]]:
        response = self._request(
            "get",
            f"{self.config.api_base_url}/repos/{self.config.repository}/issues",
            params={"state": "open", "per_page": 100},
        )
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("GitHub issue list returned unexpected response")
        url_line = f"- Input URL: `{url}`"
        host_line = f"- Host: `{host}`"
        for item in payload:
            if not isinstance(item, Mapping) or item.get("pull_request") is not None:
                continue
            body = str(item.get("body") or "")
            item_title = str(item.get("title") or "")
            if UNSUPPORTED_SOURCE_ISSUE_MARKER not in body:
                continue
            if url_line not in body and host_line not in body and item_title != title:
                continue
            issue_number = item.get("number")
            issue_url = _coerce_text(item.get("html_url"))
            if not issue_number or not issue_url:
                continue
            return {
                "action": "duplicate",
                "issue_number": int(issue_number),
                "issue_url": issue_url,
            }
        return None

    def _request(self, method: str, url: str, **kwargs):
        headers = {
            "Authorization": f"Bearer {self.config.token}",
            "Accept": "application/vnd.github+json",
        }
        request = getattr(self.session, method)
        try:
            response = request(
                url,
                headers=headers,
                timeout=self.config.timeout,
                allow_redirects=False,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"GitHub issue request failed: {redact_secret_text(exc, secrets=(self.config.token,))}"
            ) from exc
        if 200 <= response.status_code < 300:
            return response
        detail = redact_secret_text(
            str(getattr(response, "text", "")).strip().replace("\n", " "),
            secrets=(self.config.token,),
        )
        raise RuntimeError(f"GitHub returned HTTP {response.status_code}: {detail[:300]}")
