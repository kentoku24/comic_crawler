import html
import re
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

from .base import SourceParseError
from .gigaviewer import GigaViewerAdapter


_HOST = "www.sunday-webry.com"
_EPISODE_URL = re.compile(
    rf"^https?://(?:www\.)?sunday-webry\.com/episode/(\d+)(?:/)?(?:\?.*)?$"
)
_SERIES_FEED_URL = re.compile(
    rf"^https?://(?:www\.)?sunday-webry\.com/(rss|atom)/series/(\d+)(?:/)?(?:\?.*)?$"
)
_RSS_LINK = re.compile(
    rf'<link[^>]+rel="alternate"[^>]+type="application/rss\+xml"[^>]+href="(https?://(?:www\.)?sunday-webry\.com/rss/series/\d+(?:\?[^"]*)?)"',
    re.I,
)
_SERIES_ID_PATTERNS = (
    re.compile(r'"series_id"\s*:\s*"(\d+)"'),
    re.compile(r'&quot;series_id&quot;\s*:\s*&quot;(\d+)&quot;'),
    re.compile(r'"series"\s*:\s*\{\s*"id"\s*:\s*"(\d+)"'),
    re.compile(r'&quot;series&quot;\s*:\s*\{\s*&quot;id&quot;\s*:\s*&quot;(\d+)&quot;'),
    re.compile(r"https?://(?:www\.)?sunday-webry\.com/(?:rss|atom)/series/(\d+)"),
)


def canonical_sunday_webry_episode_url(episode_id: str) -> str:
    return f"https://{_HOST}/episode/{episode_id}"


def canonical_sunday_webry_series_feed_url(series_id: str, feed_kind: str = "rss") -> str:
    return f"https://{_HOST}/{feed_kind}/series/{series_id}"


def parse_sunday_webry_episode_url(seed_url: str) -> Optional[str]:
    match = _EPISODE_URL.match(seed_url)
    if not match:
        return None
    return canonical_sunday_webry_episode_url(match.group(1))


def parse_sunday_webry_series_feed_url(seed_url: str) -> Optional[Tuple[str, str]]:
    match = _SERIES_FEED_URL.match(seed_url)
    if not match:
        return None
    return match.group(1), match.group(2)


def extract_sunday_webry_series_id_from_seed_url(seed_url: str) -> Optional[str]:
    parsed = parse_sunday_webry_series_feed_url(seed_url)
    if parsed:
        return parsed[1]
    return None


def extract_sunday_webry_series_id(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    normalized = html.unescape(html_text).replace("\\/", "/")
    for pattern in _SERIES_ID_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return match.group(1)
    return None


def extract_sunday_webry_series_feed_url(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    normalized = html.unescape(html_text).replace("\\/", "/")
    match = _RSS_LINK.search(normalized)
    if match:
        return canonical_sunday_webry_series_feed_url(
            match.group(1).rsplit("/", 1)[-1].split("?", 1)[0]
        )
    series_id = extract_sunday_webry_series_id(normalized)
    if not series_id:
        return None
    return canonical_sunday_webry_series_feed_url(series_id)


def parse_sunday_webry_feed_latest(feed_text: str) -> Tuple[str, Optional[str], Optional[str]]:
    if not feed_text or not feed_text.strip():
        raise SourceParseError("sunday-webry: empty feed")

    try:
        root = ET.fromstring(feed_text)
    except ET.ParseError as exc:
        raise SourceParseError(f"sunday-webry: invalid feed: {exc}") from exc

    channel = root.find("channel")
    if channel is not None:
        series_title = _series_title_from_channel_title((channel.findtext("title") or "").strip())
        for item in channel.findall("item"):
            latest_url = parse_sunday_webry_episode_url((item.findtext("link") or "").strip())
            if not latest_url:
                continue
            episode_title = (item.findtext("title") or "").strip() or None
            item_series_title = (item.findtext("description") or "").strip() or None
            return latest_url, episode_title, item_series_title or series_title
        raise SourceParseError("sunday-webry: latest episode not found in RSS feed")

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    title_text = (root.findtext("atom:title", default="", namespaces=ns) or "").strip()
    series_title = _series_title_from_channel_title(title_text)
    for entry in root.findall("atom:entry", ns):
        for link in entry.findall("atom:link", ns):
            latest_url = parse_sunday_webry_episode_url((link.get("href") or "").strip())
            if latest_url:
                episode_title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip() or None
                content = (entry.findtext("atom:content", default="", namespaces=ns) or "").strip() or None
                return latest_url, episode_title, content or series_title
    raise SourceParseError("sunday-webry: latest episode not found in Atom feed")


def parse_sunday_webry_title(page_title: str) -> Tuple[Optional[str], Optional[str]]:
    title = str(page_title or "").strip()
    if not title:
        return None, None
    main = title.split("|", 1)[0].strip()
    episode_part, separator, remainder = main.partition(" / ")
    if not separator:
        return None, None
    series_title = remainder.split(" - ", 1)[0].strip() or None
    episode_title = episode_part.strip() or None
    return episode_title, series_title


def _series_title_from_channel_title(channel_title: str) -> Optional[str]:
    if not channel_title:
        return None
    match = re.search(r"サンデーうぇぶり（(.+?)）", channel_title)
    if match:
        return match.group(1).strip() or None
    return channel_title or None


class SundayWebryAdapter(GigaViewerAdapter):
    source = "sunday-webry"
    reuse_episode_page_title = True

    parse_episode_url = staticmethod(parse_sunday_webry_episode_url)
    parse_series_feed_url = staticmethod(parse_sunday_webry_series_feed_url)
    canonical_series_feed_url = staticmethod(canonical_sunday_webry_series_feed_url)
    extract_series_id_from_seed_url = staticmethod(extract_sunday_webry_series_id_from_seed_url)
    extract_series_id = staticmethod(extract_sunday_webry_series_id)
    extract_series_feed_url = staticmethod(extract_sunday_webry_series_feed_url)
    parse_feed_latest = staticmethod(parse_sunday_webry_feed_latest)
    parse_page_title = staticmethod(parse_sunday_webry_title)
