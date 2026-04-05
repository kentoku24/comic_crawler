import html
import re
from typing import Optional, Tuple

from .base import HttpClient, LatestEpisode, SourceAdapter, SourceParseError, WorkDescriptor
from .util import html_title


_HOST = "firecross.jp"
_READER_URL = re.compile(
    rf"^https?://(?:www\.)?{_HOST}/reader/([0-9A-Za-z_-]+)(?:/)?(?:\?.*)?$"
)
_SERIES_URL = re.compile(
    rf"^https?://(?:www\.)?{_HOST}/series/([0-9A-Za-z_-]+)(?:/)?(?:\?.*)?$"
)
_SERIES_URL_IN_HTML = re.compile(
    rf"(?:https?://(?:www\.)?{_HOST})?/series/([0-9A-Za-z_-]+)(?:[/?#\"']|$)"
)
_ANCHOR_TAG_IN_HTML = re.compile(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>", re.IGNORECASE | re.DOTALL)
_ANCHOR_HREF = re.compile(r"""href\s*=\s*(["'])(?P<href>.*?)\1""", re.IGNORECASE | re.DOTALL)
_TITLE_SITE_SUFFIX = re.compile(r"\s*\|\s*ファイアCROSS\s*$")


def canonical_firecross_reader_url(reader_id: str) -> str:
    return f"https://{_HOST}/reader/{reader_id}"


def canonical_firecross_series_url(series_id: str) -> str:
    return f"https://{_HOST}/series/{series_id}"


def parse_firecross_reader_url(seed_url: str) -> Optional[str]:
    match = _READER_URL.match(seed_url)
    if not match:
        return None
    return canonical_firecross_reader_url(match.group(1))


def parse_firecross_series_url(url: str) -> Optional[str]:
    match = _SERIES_URL.match(url)
    if not match:
        return None
    return canonical_firecross_series_url(match.group(1))


def extract_firecross_series_url(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    normalized = html.unescape(html_text).replace("\\/", "/").replace('\\"', '"')
    match = _SERIES_URL_IN_HTML.search(normalized)
    if not match:
        return None
    return canonical_firecross_series_url(match.group(1))


def extract_firecross_series_id(html_text: str) -> Optional[str]:
    series_url = extract_firecross_series_url(html_text)
    if not series_url:
        return None
    match = _SERIES_URL.match(series_url)
    if not match:
        return None
    return match.group(1)


def extract_firecross_latest_reader_url(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    normalized = html.unescape(html_text).replace("\\/", "/").replace('\\"', '"')
    for match in _ANCHOR_TAG_IN_HTML.finditer(normalized):
        attrs = match.group("attrs") or ""
        body = match.group("body") or ""
        href_match = _ANCHOR_HREF.search(attrs)
        if not href_match:
            continue
        latest_signal = "latest" in attrs.lower() or "最新" in attrs or "最新" in body
        if not latest_signal:
            continue
        parsed = parse_firecross_reader_url(href_match.group("href"))
        if parsed:
            return parsed
    return None


def parse_firecross_reader_title(page_title: str) -> Tuple[Optional[str], Optional[str]]:
    normalized = _TITLE_SITE_SUFFIX.sub("", str(page_title or "").strip())
    if not normalized:
        return None, None
    for separator in (" / ", "／"):
        if separator not in normalized:
            continue
        episode_title, series_title = normalized.split(separator, 1)
        episode_title = episode_title.strip() or None
        series_title = series_title.strip() or None
        return episode_title, series_title
    return normalized, None


def parse_firecross_series_title(page_title: str) -> Optional[str]:
    normalized = _TITLE_SITE_SUFFIX.sub("", str(page_title or "").strip())
    return normalized or None


class FirecrossAdapter(SourceAdapter):
    source = "firecross"

    def can_handle(self, seed_url: str) -> bool:
        return bool(parse_firecross_reader_url(seed_url))

    def normalize(self, seed_url: str) -> WorkDescriptor:
        normalized_reader_url = parse_firecross_reader_url(seed_url)
        if not normalized_reader_url:
            raise RuntimeError(f"firecross: could not parse seed URL: {seed_url}")
        return WorkDescriptor(
            source=self.source,
            work_id=normalized_reader_url,
            seed_url=normalized_reader_url,
        )

    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        series_id, series_url = self._resolve_series(work, http_client)
        series_html = http_client.get_text(series_url)
        latest_url = extract_firecross_latest_reader_url(series_html)
        if not latest_url:
            raise SourceParseError("firecross: latest reader URL not found")

        latest_html = http_client.get_text(latest_url)
        episode_title, series_title_from_reader = parse_firecross_reader_title(html_title(latest_html) or "")
        series_title = parse_firecross_series_title(html_title(series_html) or "") or series_title_from_reader

        return LatestEpisode(
            source=self.source,
            work_id=work.work_id,
            latest_key=latest_url,
            url=latest_url,
            series=f"{self.source}:{series_id}",
            series_title=series_title,
            episode_title=episode_title,
        )

    def _resolve_series(self, work: WorkDescriptor, http_client: HttpClient) -> Tuple[str, str]:
        series_id = str(work.metadata.get("seriesId") or "")
        if not series_id and str(work.work_id).startswith(f"{self.source}:"):
            series_id = str(work.work_id).split(":", 1)[1]
        if series_id:
            return series_id, canonical_firecross_series_url(series_id)

        normalized_reader_url = parse_firecross_reader_url(work.seed_url)
        if not normalized_reader_url:
            raise RuntimeError("firecross: unsupported seed URL")

        reader_html = http_client.get_text(normalized_reader_url)
        series_id = extract_firecross_series_id(reader_html) or ""
        if not series_id:
            raise SourceParseError("firecross: series id not found")
        return series_id, canonical_firecross_series_url(series_id)
