import html
import re
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

from .base import HttpClient, LatestEpisode, SourceAdapter, SourceParseError, WorkDescriptor
from .util import html_title


_HOST = "kuragebunch.com"
_EPISODE_URL = re.compile(rf"^https?://(?:www\.)?{_HOST}/episode/(\d+)(?:/)?(?:\?.*)?$")
_SERIES_FEED_URL = re.compile(
    rf"^https?://(?:www\.)?{_HOST}/(rss|atom)/series/(\d+)(?:/)?(?:\?.*)?$"
)
_RSS_LINK = re.compile(
    rf'<link[^>]+rel="alternate"[^>]+type="application/rss\+xml"[^>]+href="(https?://(?:www\.)?{_HOST}/rss/series/\d+(?:\?[^"]*)?)"',
    re.I,
)
_SERIES_ID_PATTERNS = (
    re.compile(r'"series_id"\s*:\s*"(\d+)"'),
    re.compile(r'&quot;series_id&quot;\s*:\s*&quot;(\d+)&quot;'),
    re.compile(rf"https?://(?:www\.)?{_HOST}/(?:rss|atom)/series/(\d+)"),
)


def canonical_kuragebunch_episode_url(episode_id: str) -> str:
    return f"https://{_HOST}/episode/{episode_id}"


def canonical_kuragebunch_series_feed_url(series_id: str, feed_kind: str = "rss") -> str:
    return f"https://{_HOST}/{feed_kind}/series/{series_id}"


def parse_kuragebunch_episode_url(seed_url: str) -> Optional[str]:
    match = _EPISODE_URL.match(seed_url)
    if not match:
        return None
    return canonical_kuragebunch_episode_url(match.group(1))


def parse_kuragebunch_series_feed_url(seed_url: str) -> Optional[Tuple[str, str]]:
    match = _SERIES_FEED_URL.match(seed_url)
    if not match:
        return None
    return match.group(1), match.group(2)


def extract_kuragebunch_series_id_from_seed_url(seed_url: str) -> Optional[str]:
    parsed = parse_kuragebunch_series_feed_url(seed_url)
    if parsed:
        return parsed[1]
    return None


def extract_kuragebunch_series_id(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    normalized = html.unescape(html_text).replace("\\/", "/")
    for pattern in _SERIES_ID_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return match.group(1)
    return None


def extract_kuragebunch_series_feed_url(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    normalized = html.unescape(html_text).replace("\\/", "/")
    match = _RSS_LINK.search(normalized)
    if match:
        return canonical_kuragebunch_series_feed_url(match.group(1).rsplit("/", 1)[-1].split("?", 1)[0])
    series_id = extract_kuragebunch_series_id(normalized)
    if not series_id:
        return None
    return canonical_kuragebunch_series_feed_url(series_id)


def parse_kuragebunch_feed_latest(feed_text: str) -> Tuple[str, Optional[str], Optional[str]]:
    if not feed_text or not feed_text.strip():
        raise SourceParseError("kuragebunch: empty feed")

    try:
        root = ET.fromstring(feed_text)
    except ET.ParseError as exc:
        raise SourceParseError(f"kuragebunch: invalid feed: {exc}") from exc

    channel = root.find("channel")
    if channel is not None:
        series_title = _series_title_from_channel_title((channel.findtext("title") or "").strip())
        for item in channel.findall("item"):
            latest_url = parse_kuragebunch_episode_url((item.findtext("link") or "").strip())
            if not latest_url:
                continue
            episode_title = (item.findtext("title") or "").strip() or None
            item_series_title = (item.findtext("description") or "").strip() or None
            return latest_url, episode_title, item_series_title or series_title
        raise SourceParseError("kuragebunch: latest episode not found in RSS feed")

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    title_text = (root.findtext("atom:title", default="", namespaces=ns) or "").strip()
    series_title = _series_title_from_channel_title(title_text)
    for entry in root.findall("atom:entry", ns):
        for link in entry.findall("atom:link", ns):
            latest_url = parse_kuragebunch_episode_url((link.get("href") or "").strip())
            if latest_url:
                episode_title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip() or None
                content = (entry.findtext("atom:content", default="", namespaces=ns) or "").strip() or None
                return latest_url, episode_title, content or series_title
    raise SourceParseError("kuragebunch: latest episode not found in Atom feed")


def parse_kuragebunch_title(page_title: str) -> Tuple[Optional[str], Optional[str]]:
    title = str(page_title or "").strip()
    if not title:
        return None, None
    main = title.split("|", 1)[0].strip()
    left, separator, right = main.rpartition(" / ")
    if not separator:
        return None, None
    episode_title = right.strip() or None
    series_part = left.strip()
    series_title = series_part.split(" - ", 1)[0].strip() or None
    return episode_title, series_title


def _series_title_from_channel_title(channel_title: str) -> Optional[str]:
    if not channel_title:
        return None
    match = re.search(r"くらげバンチ（(.+?)）", channel_title)
    if match:
        return match.group(1).strip() or None
    return channel_title or None


class KuragebunchAdapter(SourceAdapter):
    source = "kuragebunch"

    def can_handle(self, seed_url: str) -> bool:
        return bool(
            parse_kuragebunch_episode_url(seed_url)
            or parse_kuragebunch_series_feed_url(seed_url)
        )

    def normalize(self, seed_url: str) -> WorkDescriptor:
        normalized_episode_url = parse_kuragebunch_episode_url(seed_url)
        if normalized_episode_url:
            return WorkDescriptor(
                source=self.source,
                work_id=normalized_episode_url,
                seed_url=normalized_episode_url,
            )

        feed_match = parse_kuragebunch_series_feed_url(seed_url)
        if not feed_match:
            raise RuntimeError(f"kuragebunch: unsupported seed URL: {seed_url}")

        _, series_id = feed_match
        stable_work_id = f"{self.source}:{series_id}"
        return WorkDescriptor(
            source=self.source,
            work_id=stable_work_id,
            seed_url=canonical_kuragebunch_series_feed_url(series_id),
            metadata={
                "series": stable_work_id,
                "seriesId": series_id,
                "feedKind": "rss",
            },
        )

    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        series = str(work.metadata.get("series") or work.work_id)
        series_id = str(work.metadata.get("seriesId") or "")

        feed_match = parse_kuragebunch_series_feed_url(work.seed_url)
        if feed_match:
            feed_url = canonical_kuragebunch_series_feed_url(feed_match[1])
            series_id = series_id or feed_match[1]
        else:
            episode_url = parse_kuragebunch_episode_url(work.seed_url)
            if not episode_url:
                raise RuntimeError("kuragebunch: unsupported seed URL")
            episode_html = http_client.get_text(episode_url)
            feed_url = extract_kuragebunch_series_feed_url(episode_html)
            series_id = series_id or extract_kuragebunch_series_id(episode_html) or ""
            if not series_id:
                raise SourceParseError("kuragebunch: series id not found")
            if not feed_url:
                raise SourceParseError("kuragebunch: series feed URL not found")
            series = f"{self.source}:{series_id}"

        feed_text = http_client.get_text(feed_url)
        latest_url, episode_title, series_title = parse_kuragebunch_feed_latest(feed_text)
        page_title = html_title(http_client.get_text(latest_url))
        parsed_episode_title, parsed_series_title = parse_kuragebunch_title(page_title or "")
        if not episode_title:
            episode_title = parsed_episode_title
        if not series_title:
            series_title = parsed_series_title

        return LatestEpisode(
            source=self.source,
            work_id=work.work_id if work.work_id.startswith(f"{self.source}:") else series,
            latest_key=latest_url,
            url=latest_url,
            series=series,
            series_title=series_title,
            episode_title=episode_title,
            page_title=page_title,
        )
