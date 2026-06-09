import html
import re
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

from .base import HttpClient, LatestEpisode, SourceParseError, WorkDescriptor
from .gigaviewer import GigaViewerAdapter
from .util import html_title


_HOST = "comic-trail.com"
_EPISODE_URL = re.compile(
    rf"^https?://(?:www\.)?{_HOST}/episode/(\d+)(?:/)?(?:\?.*)?$"
)
_SERIES_FEED_URL = re.compile(
    rf"^https?://(?:www\.)?{_HOST}/(rss|atom)/series/(\d+)(?:/)?(?:\?.*)?$"
)
_SERIES_ID_PATTERNS = (
    re.compile(r'"series_id"\s*:\s*"(\d+)"'),
    re.compile(r'&quot;series_id&quot;\s*:\s*&quot;(\d+)&quot;'),
    re.compile(rf"https?://(?:www\.)?{_HOST}/(?:rss|atom)/series/(\d+)"),
)
_RSS_LINK = re.compile(
    rf'<link[^>]+rel="alternate"[^>]+type="application/rss\+xml"[^>]+href="(https?://(?:www\.)?{_HOST}/rss/series/\d+(?:\?[^"]*)?)"',
    re.I,
)
_ATOM_LINK = re.compile(
    rf'<link[^>]+rel="alternate"[^>]+type="application/atom\+xml"[^>]+href="(https?://(?:www\.)?{_HOST}/atom/series/\d+(?:\?[^"]*)?)"',
    re.I,
)


def canonical_comic_trail_episode_url(episode_id: str) -> str:
    return f"https://{_HOST}/episode/{episode_id}"


def canonical_comic_trail_series_feed_url(series_id: str, feed_kind: str = "rss") -> str:
    return f"https://{_HOST}/{feed_kind}/series/{series_id}"


def parse_comic_trail_episode_url(seed_url: str) -> Optional[str]:
    match = _EPISODE_URL.match(seed_url)
    if not match:
        return None
    return canonical_comic_trail_episode_url(match.group(1))


def parse_comic_trail_series_feed_url(seed_url: str) -> Optional[Tuple[str, str]]:
    match = _SERIES_FEED_URL.match(seed_url)
    if not match:
        return None
    return match.group(1), match.group(2)


def extract_comic_trail_series_id_from_seed_url(seed_url: str) -> Optional[str]:
    parsed = parse_comic_trail_series_feed_url(seed_url)
    if parsed:
        return parsed[1]
    return None


def extract_comic_trail_series_id(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    normalized = html.unescape(html_text).replace("\\/", "/")
    for pattern in _SERIES_ID_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return match.group(1)
    return None


def extract_comic_trail_series_feed_url(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    normalized = html.unescape(html_text).replace("\\/", "/")
    for pattern in (_RSS_LINK, _ATOM_LINK):
        match = pattern.search(normalized)
        if match:
            return canonical_comic_trail_series_feed_url(match.group(1).rsplit("/", 1)[-1].split("?", 1)[0])
    series_id = extract_comic_trail_series_id(normalized)
    if not series_id:
        return None
    return canonical_comic_trail_series_feed_url(series_id)


def parse_comic_trail_feed_latest(feed_text: str) -> Tuple[str, Optional[str], Optional[str]]:
    if not feed_text or not feed_text.strip():
        raise SourceParseError("comic-trail: empty feed")

    try:
        root = ET.fromstring(feed_text)
    except ET.ParseError as exc:
        raise SourceParseError(f"comic-trail: invalid feed: {exc}") from exc

    channel = root.find("channel")
    if channel is not None:
        series_title = _series_title_from_channel_title((channel.findtext("title") or "").strip())
        for item in channel.findall("item"):
            latest_url = parse_comic_trail_episode_url((item.findtext("link") or "").strip())
            if not latest_url:
                continue
            episode_title = (item.findtext("title") or "").strip() or None
            item_series_title = (item.findtext("description") or "").strip() or None
            return latest_url, episode_title, item_series_title or series_title
        raise SourceParseError("comic-trail: latest episode not found in RSS feed")

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    title_text = (root.findtext("atom:title", default="", namespaces=ns) or "").strip()
    series_title = _series_title_from_channel_title(title_text)
    for entry in root.findall("atom:entry", ns):
        for link in entry.findall("atom:link", ns):
            latest_url = parse_comic_trail_episode_url((link.get("href") or "").strip())
            if latest_url:
                episode_title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip() or None
                content = (entry.findtext("atom:content", default="", namespaces=ns) or "").strip() or None
                return latest_url, episode_title, content or series_title
    raise SourceParseError("comic-trail: latest episode not found in Atom feed")


def parse_comic_trail_title(page_title: str) -> Tuple[Optional[str], Optional[str]]:
    title = str(page_title or "").strip()
    if not title:
        return None, None
    main = title.split("|", 1)[0].strip()
    left, separator, right = main.rpartition(" / ")
    if not separator:
        return None, None
    episode_title = left.strip() or None
    series_part = right.strip()
    series_title = series_part.split(" - ", 1)[0].strip() or None
    return episode_title, series_title


def extract_comic_trail_next_update_label(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    normalized = html.unescape(html_text)
    match = re.search(r"次回更新[:：]\s*([^<]+)", normalized)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(0)).strip() or None


def _series_title_from_channel_title(channel_title: str) -> Optional[str]:
    if not channel_title:
        return None
    match = re.search(r"コミックトレイル（(.+?)）", channel_title)
    if match:
        return match.group(1).strip() or None
    return channel_title or None


class ComicTrailAdapter(GigaViewerAdapter):
    source = "comic-trail"

    parse_episode_url = staticmethod(parse_comic_trail_episode_url)
    parse_series_feed_url = staticmethod(parse_comic_trail_series_feed_url)
    canonical_series_feed_url = staticmethod(canonical_comic_trail_series_feed_url)
    extract_series_id_from_seed_url = staticmethod(extract_comic_trail_series_id_from_seed_url)
    extract_series_id = staticmethod(extract_comic_trail_series_id)
    extract_series_feed_url = staticmethod(extract_comic_trail_series_feed_url)
    parse_feed_latest = staticmethod(parse_comic_trail_feed_latest)
    parse_page_title = staticmethod(parse_comic_trail_title)

    # comic-trail keeps a bespoke fetch_latest: it builds the feed URL directly
    # from the series id (no feed-link discovery), reuses already-fetched HTML,
    # raises strictly when the page title cannot be parsed, and emits a
    # nextUpdateLabel scraped from the episode page.
    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        series = str(work.metadata.get("series") or work.work_id)
        series_id = str(work.metadata.get("seriesId") or "") or extract_comic_trail_series_id_from_seed_url(work.seed_url)
        latest_page_html = None

        if not series_id:
            episode_url = parse_comic_trail_episode_url(work.seed_url)
            if not episode_url:
                raise RuntimeError("comic-trail: unsupported seed URL")
            latest_page_html = http_client.get_text(episode_url)
            series_id = extract_comic_trail_series_id(latest_page_html) or ""
            if not series_id:
                raise SourceParseError("comic-trail: series id not found")
            series = f"{self.source}:{series_id}"

        feed_url = canonical_comic_trail_series_feed_url(series_id)
        feed_text = http_client.get_text(feed_url)
        latest_url, episode_title, series_title = parse_comic_trail_feed_latest(feed_text)
        if latest_page_html is None or latest_url != parse_comic_trail_episode_url(work.seed_url):
            latest_page_html = http_client.get_text(latest_url)
        page_title = html_title(latest_page_html)
        parsed_episode_title, parsed_series_title = parse_comic_trail_title(page_title or "")
        if not parsed_episode_title:
            raise SourceParseError("comic-trail: latest episode title could not be parsed from page title")
        if not parsed_series_title:
            raise SourceParseError("comic-trail: series title could not be parsed from page title")
        if not episode_title:
            episode_title = parsed_episode_title
        if not series_title:
            series_title = parsed_series_title
        next_update_label = extract_comic_trail_next_update_label(latest_page_html)

        return LatestEpisode(
            source=self.source,
            work_id=work.work_id if work.work_id.startswith(f"{self.source}:") else series,
            latest_key=latest_url,
            url=latest_url,
            series=series,
            series_title=series_title,
            episode_title=episode_title,
            page_title=page_title,
            extra={"nextUpdateLabel": next_update_label} if next_update_label else {},
        )
