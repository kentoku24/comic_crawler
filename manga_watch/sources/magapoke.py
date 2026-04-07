import re
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

from .base import HttpClient, LatestEpisode, SourceAdapter, SourceParseError, WorkDescriptor


_TITLE_OR_EPISODE_URL = re.compile(
    r"^https?://(?:www\.)?pocket\.shonenmagazine\.com/title/(\d+)(?:/episode/(\d+))?/?(?:\?.*)?$"
)
_RSS_URL = re.compile(
    r'<link[^>]+rel="alternate"[^>]+type="application/rss\+xml"[^>]+href="([^"]+)"',
    re.I,
)


def normalize_magapoke_title_id(raw_title_id: str) -> Tuple[str, str]:
    title_slug = str(raw_title_id or "").strip()
    if not title_slug or not title_slug.isdigit():
        raise RuntimeError("magapoke: could not parse title id")
    numeric_title_id = str(int(title_slug))
    return numeric_title_id, title_slug


def canonical_magapoke_title_url(title_slug: str) -> str:
    return f"https://pocket.shonenmagazine.com/title/{title_slug}"


def canonical_magapoke_rss_url(title_id: str) -> str:
    return f"https://mgpk-cdn.magazinepocket.com/static/rss/{title_id}/feed.xml"


def extract_magapoke_rss_url(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    match = _RSS_URL.search(html_text)
    if not match:
        return None
    return match.group(1).strip() or None


def extract_magapoke_next_update_label(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    match = re.search(r"次回更新[^<]+予定です。", html_text)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(0)).strip() or None


def classification_page_title_for_magapoke(episode_title: Optional[str]) -> Optional[str]:
    if not episode_title:
        return None
    return episode_title.replace("＃", "#")


def parse_magapoke_rss_latest(feed_text: str) -> Tuple[str, Optional[str], Optional[str]]:
    if not feed_text or not feed_text.strip():
        raise SourceParseError("magapoke: empty RSS feed")

    try:
        root = ET.fromstring(feed_text)
    except ET.ParseError as exc:
        raise SourceParseError(f"magapoke: invalid RSS feed: {exc}") from exc

    channel = root.find("channel")
    if channel is None:
        raise SourceParseError("magapoke: RSS channel not found")

    channel_title = (channel.findtext("title") or "").strip()
    for item in channel.findall("item"):
        latest_url = (item.findtext("link") or "").strip()
        if not _TITLE_OR_EPISODE_URL.match(latest_url):
            continue
        episode_title = (item.findtext("title") or "").strip() or None
        series_title = (item.findtext("description") or "").strip() or None
        if not series_title:
            match = re.search(r"マガポケ（(.+?)）", channel_title)
            if match:
                series_title = match.group(1).strip() or None
        return latest_url, episode_title, series_title

    raise SourceParseError("magapoke: latest episode not found in RSS feed")


class MagapokeAdapter(SourceAdapter):
    source = "magapoke"

    def can_handle(self, seed_url: str) -> bool:
        return bool(_TITLE_OR_EPISODE_URL.match(seed_url))

    def normalize(self, seed_url: str) -> WorkDescriptor:
        match = _TITLE_OR_EPISODE_URL.match(seed_url)
        if not match:
            raise RuntimeError("magapoke: could not parse title/episode URL")

        numeric_title_id, title_slug = normalize_magapoke_title_id(match.group(1))
        work_id = f"{self.source}:{numeric_title_id}"
        return WorkDescriptor(
            source=self.source,
            work_id=work_id,
            seed_url=canonical_magapoke_title_url(title_slug),
            metadata={
                "series": work_id,
                "titleId": numeric_title_id,
                "titleSlug": title_slug,
            },
        )

    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        title_id = str(work.metadata.get("titleId") or "")
        title_slug = str(work.metadata.get("titleSlug") or "")
        if not title_id or not title_slug:
            match = _TITLE_OR_EPISODE_URL.match(work.seed_url)
            if not match:
                raise RuntimeError("magapoke: work descriptor missing title id")
            title_id, title_slug = normalize_magapoke_title_id(match.group(1))

        title_url = canonical_magapoke_title_url(title_slug)
        title_html = http_client.get_text(title_url)
        rss_url = extract_magapoke_rss_url(title_html) or canonical_magapoke_rss_url(title_id)
        feed_text = http_client.get_text(rss_url)
        latest_url, episode_title, series_title = parse_magapoke_rss_latest(feed_text)
        next_update_label = extract_magapoke_next_update_label(title_html)

        return LatestEpisode(
            source=self.source,
            work_id=work.work_id,
            latest_key=latest_url,
            url=latest_url,
            series=work.metadata.get("series") or work.work_id,
            series_title=series_title,
            episode_title=episode_title,
            page_title=classification_page_title_for_magapoke(episode_title),
            extra={"nextUpdateLabel": next_update_label} if next_update_label else {},
        )
