import html
import re
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

from .base import HttpClient, LatestEpisode, SourceAdapter, SourceParseError, WorkDescriptor


_HOST = "takecomic.jp"
_EPISODE_URL = re.compile(
    rf"^https?://(?:www\.)?{_HOST}/episodes/([0-9A-Za-z]+)(?:/)?(?:\?.*)?$"
)
_SERIES_URL = re.compile(
    rf"^https?://(?:www\.)?{_HOST}/series/([0-9A-Za-z]+)(?:/)?(?:\?.*)?$"
)
_SERIES_RSS_URL = re.compile(
    rf"^https?://(?:www\.)?{_HOST}/series/([0-9A-Za-z]+)/rss(?:/)?(?:\?.*)?$"
)
_SERIES_HASH_IN_HTML = re.compile(
    rf"https?://(?:www\.)?{_HOST}/series/([0-9A-Za-z]+)(?:/rss)?(?:[/?\"'])"
)
_NEXT_UPDATE_LABEL_IN_PRE_DAY = re.compile(
    r'<a[^>]*class="[^"]*\bseries-h-pre-day\b[^"]*"[^>]*>\s*([^<]+?)\s*</a>',
    re.S,
)
_NEXT_UPDATE_LABEL_IN_DAY_LINK = re.compile(
    r'<a[^>]*class="[^"]*\bseries-h-day-of-week-link\b[^"]*"[^>]*>.*?'
    r'<span[^>]*class="[^"]*\bseries-h-tag-label\b[^"]*"[^>]*>\s*([^<]+?)\s*</span>',
    re.S,
)
_DAYS_OF_WEEK_IN_SERIALIZED_DATA = re.compile(r'"daysOfWeek":"([^"]+)"')
_DAYS_OF_WEEK_LABELS = {
    "0": "日",
    "1": "月",
    "2": "火",
    "3": "水",
    "4": "木",
    "5": "金",
    "6": "土",
}


def canonical_takecomic_episode_url(episode_hash: str) -> str:
    return f"https://{_HOST}/episodes/{episode_hash}"


def canonical_takecomic_series_url(series_hash: str) -> str:
    return f"https://{_HOST}/series/{series_hash}"


def canonical_takecomic_series_rss_url(series_hash: str) -> str:
    return f"{canonical_takecomic_series_url(series_hash)}/rss"


def parse_takecomic_episode_url(seed_url: str) -> Optional[str]:
    match = _EPISODE_URL.match(seed_url)
    if not match:
        return None
    return canonical_takecomic_episode_url(match.group(1))


def parse_takecomic_series_url(seed_url: str) -> Optional[str]:
    match = _SERIES_URL.match(seed_url)
    if not match:
        return None
    return canonical_takecomic_series_url(match.group(1))


def parse_takecomic_series_rss_url(seed_url: str) -> Optional[str]:
    match = _SERIES_RSS_URL.match(seed_url)
    if not match:
        return None
    return canonical_takecomic_series_rss_url(match.group(1))


def extract_takecomic_series_hash_from_seed_url(seed_url: str) -> Optional[str]:
    for pattern in (_SERIES_RSS_URL, _SERIES_URL):
        match = pattern.match(seed_url)
        if match:
            return match.group(1)
    return None


def extract_takecomic_series_hash(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    normalized = html.unescape(html_text).replace("\\/", "/")
    match = _SERIES_HASH_IN_HTML.search(normalized)
    if not match:
        return None
    return match.group(1)


def extract_takecomic_next_update_label(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    normalized = html.unescape(html_text).replace("\\/", "/").replace('\\"', '"')
    for pattern in (_NEXT_UPDATE_LABEL_IN_PRE_DAY, _NEXT_UPDATE_LABEL_IN_DAY_LINK):
        match = pattern.search(normalized)
        if not match:
            continue
        label = re.sub(r"\s+", " ", match.group(1)).strip()
        if label:
            return label

    match = _DAYS_OF_WEEK_IN_SERIALIZED_DATA.search(normalized)
    if not match:
        return None
    return _format_takecomic_days_of_week(match.group(1))


def _format_takecomic_days_of_week(raw_value: str) -> Optional[str]:
    tokens = [token.strip() for token in raw_value.split(",") if token.strip()]
    if not tokens:
        return None

    labels = []
    for token in tokens:
        label = _DAYS_OF_WEEK_LABELS.get(token)
        if not label:
            return None
        labels.append(label)

    return f"{'・'.join(labels)}曜更新"


def parse_takecomic_rss_latest(feed_text: str) -> Tuple[str, Optional[str], Optional[str]]:
    if not feed_text or not feed_text.strip():
        raise SourceParseError("takecomic: empty RSS feed")

    try:
        root = ET.fromstring(feed_text)
    except ET.ParseError as exc:
        raise SourceParseError(f"takecomic: invalid RSS feed: {exc}") from exc

    channel = root.find("channel")
    if channel is None:
        raise SourceParseError("takecomic: RSS channel not found")

    series_title = (channel.findtext("title") or "").strip() or None
    for item in channel.findall("item"):
        latest_url = parse_takecomic_episode_url((item.findtext("link") or "").strip())
        if not latest_url:
            continue
        episode_title = (item.findtext("title") or "").strip() or None
        return latest_url, episode_title, series_title

    raise SourceParseError("takecomic: latest episode not found in RSS feed")


class TakecomicAdapter(SourceAdapter):
    source = "takecomic"

    def can_handle(self, seed_url: str) -> bool:
        return bool(
            parse_takecomic_episode_url(seed_url)
            or parse_takecomic_series_url(seed_url)
            or parse_takecomic_series_rss_url(seed_url)
        )

    def normalize(self, seed_url: str) -> WorkDescriptor:
        normalized_episode_url = parse_takecomic_episode_url(seed_url)
        if normalized_episode_url:
            return WorkDescriptor(
                source=self.source,
                work_id=normalized_episode_url,
                seed_url=normalized_episode_url,
            )

        series_hash = extract_takecomic_series_hash_from_seed_url(seed_url)
        if not series_hash:
            raise RuntimeError(f"takecomic: could not parse seed URL: {seed_url}")

        stable_work_id = f"{self.source}:{series_hash}"
        normalized_series_rss_url = parse_takecomic_series_rss_url(seed_url)
        if normalized_series_rss_url:
            return WorkDescriptor(
                source=self.source,
                work_id=stable_work_id,
                seed_url=normalized_series_rss_url,
                metadata={
                    "series": stable_work_id,
                    "seriesHash": series_hash,
                    "feedKind": "rss",
                },
            )

        normalized_series_url = parse_takecomic_series_url(seed_url)
        if normalized_series_url:
            return WorkDescriptor(
                source=self.source,
                work_id=stable_work_id,
                seed_url=normalized_series_url,
                metadata={
                    "series": stable_work_id,
                    "seriesHash": series_hash,
                },
            )

        raise RuntimeError(f"takecomic: unsupported seed URL: {seed_url}")

    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        series_hash, rss_url, seed_episode_html = self._resolve_series_hash_and_rss_url(work, http_client)
        feed_text = http_client.get_text(rss_url)
        latest_url, episode_title, series_title = parse_takecomic_rss_latest(feed_text)

        latest_episode_html = seed_episode_html
        if latest_episode_html is None or latest_url != parse_takecomic_episode_url(work.seed_url):
            latest_episode_html = http_client.get_text(latest_url)
        next_update_label = extract_takecomic_next_update_label(latest_episode_html)

        extra = {}
        if next_update_label:
            extra["nextUpdateLabel"] = next_update_label
        return LatestEpisode(
            source=self.source,
            work_id=work.work_id,
            latest_key=latest_url,
            url=latest_url,
            series=f"{self.source}:{series_hash}",
            series_title=series_title,
            episode_title=episode_title,
            extra=extra,
        )

    def _resolve_series_hash_and_rss_url(
        self,
        work: WorkDescriptor,
        http_client: HttpClient,
    ) -> Tuple[str, str, Optional[str]]:
        series_hash = (
            work.metadata.get("seriesHash")
            or extract_takecomic_series_hash_from_seed_url(work.seed_url)
        )
        if series_hash:
            return series_hash, canonical_takecomic_series_rss_url(series_hash), None

        normalized_episode_url = parse_takecomic_episode_url(work.seed_url)
        if not normalized_episode_url:
            raise RuntimeError("takecomic: unsupported seed URL")

        episode_html = http_client.get_text(normalized_episode_url)
        series_hash = extract_takecomic_series_hash(episode_html)
        if not series_hash:
            raise SourceParseError("takecomic: series hash not found")

        return series_hash, canonical_takecomic_series_rss_url(series_hash), episode_html
