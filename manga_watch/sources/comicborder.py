from __future__ import annotations

import html
import re
from typing import Optional, Tuple
from xml.etree import ElementTree

from .base import HttpClient, LatestEpisode, SourceAdapter, SourceParseError, WorkDescriptor
from .util import html_title


_EPISODE_URL = re.compile(
    r"^https?://(?:www\.)?comicborder\.com/episode/(\d+)(?:/)?(?:\?.*)?$"
)


def canonical_comicborder_episode_url(episode_id: str) -> str:
    return f"https://comicborder.com/episode/{episode_id}"


def parse_comicborder_episode_url(seed_url: str) -> Optional[str]:
    match = _EPISODE_URL.match(seed_url)
    if not match:
        return None
    return canonical_comicborder_episode_url(match.group(1))


def extract_comicborder_rss_url(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    decoded = html.unescape(html_text)
    match = re.search(
        r'href="(https?://(?:www\.)?comicborder\.com/rss/series/\d+)"',
        decoded,
    )
    if not match:
        return None
    return match.group(1)


def parse_comicborder_title(page_title: str) -> Tuple[Optional[str], Optional[str]]:
    if not page_title:
        return None, None
    left = page_title.split("|")[0].strip()
    match = re.match(r"^(.+?)\s*-\s*(.+?)\s*/\s*(.+)$", left)
    if not match:
        return None, None
    series_title = match.group(1).strip() or None
    episode_title = match.group(3).strip() or None
    return series_title, episode_title


def extract_comicborder_next_update_label(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    match = re.search(r"次回更新[:：]\s*([^<]+)", html_text)
    if not match:
        return None
    label = re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()
    return label or None


def parse_comicborder_rss(feed_text: str) -> Tuple[str, Optional[str], Optional[str]]:
    if not feed_text or not feed_text.strip():
        raise SourceParseError("comicborder: empty RSS feed")

    try:
        root = ElementTree.fromstring(feed_text)
    except ElementTree.ParseError as exc:
        raise SourceParseError(f"comicborder: invalid RSS feed: {exc}") from exc

    channel = root.find("channel")
    if channel is None:
        raise SourceParseError("comicborder: RSS channel not found")

    item = channel.find("item")
    if item is None:
        raise SourceParseError("comicborder: latest episode not found in RSS feed")

    latest_url = (item.findtext("link") or "").strip()
    if not latest_url:
        raise SourceParseError("comicborder: latest episode URL not found in RSS feed")

    latest_url = parse_comicborder_episode_url(latest_url) or latest_url
    channel_title = (channel.findtext("title") or "").strip() or None
    item_title = (item.findtext("title") or "").strip() or None
    return latest_url, channel_title, item_title


def _channel_title_to_series_title(channel_title: Optional[str]) -> Optional[str]:
    if not channel_title:
        return None
    match = re.match(r"^コミックボーダー（(.+)）$", channel_title)
    if match:
        return match.group(1).strip() or None
    return channel_title


class ComicBorderAdapter(SourceAdapter):
    source = "comicborder"

    def can_handle(self, seed_url: str) -> bool:
        return bool(parse_comicborder_episode_url(seed_url))

    def normalize(self, seed_url: str) -> WorkDescriptor:
        normalized_episode_url = parse_comicborder_episode_url(seed_url)
        if not normalized_episode_url:
            raise RuntimeError(f"comicborder: unsupported seed URL: {seed_url}")

        return WorkDescriptor(
            source=self.source,
            work_id=normalized_episode_url,
            seed_url=normalized_episode_url,
        )

    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        seed_html = self._fetch_episode_page(work.seed_url, http_client)
        rss_url = extract_comicborder_rss_url(seed_html)
        if not rss_url:
            raise SourceParseError("comicborder: RSS feed link not found")

        feed_text = http_client.get_text(rss_url)
        latest_url, channel_title, item_title = parse_comicborder_rss(feed_text)

        latest_html = seed_html if latest_url == work.seed_url else self._fetch_episode_page(latest_url, http_client)
        page_title = html_title(latest_html)
        series_title, episode_title = parse_comicborder_title(page_title or "")
        if not series_title:
            series_title = _channel_title_to_series_title(channel_title)
        if not episode_title:
            episode_title = item_title
        next_update_label = extract_comicborder_next_update_label(latest_html)

        return LatestEpisode(
            source=self.source,
            work_id=work.work_id,
            latest_key=latest_url,
            url=latest_url,
            series_title=series_title,
            episode_title=episode_title,
            page_title=page_title,
            extra={"rssUrl": rss_url, "nextUpdateLabel": next_update_label}
            if next_update_label
            else {"rssUrl": rss_url},
        )

    def _fetch_episode_page(self, episode_url: str, http_client: HttpClient) -> str:
        return http_client.get_text(episode_url)
