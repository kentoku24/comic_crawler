import html
import re
from typing import Optional, Tuple

from .base import HttpClient, LatestEpisode, SourceAdapter, SourceParseError, WorkDescriptor
from .util import html_title


_EPISODE_URL = re.compile(
    r"^https?://(?:www\.)?comic-action\.com/episode/(\d+)/?(?:\?.*)?$"
)
_SERIES_FEED_URL = re.compile(
    r"^https?://(?:www\.)?comic-action\.com/(rss|atom)/series/(\d+)(?:/)?(?:\?.*)?$"
)


def parse_comic_action_title(page_title: str) -> Tuple[Optional[str], Optional[str]]:
    if not page_title:
        return None, None
    main = page_title.split("|")[0].strip()
    parts = [part.strip() for part in main.split("/")]
    if len(parts) >= 2:
        episode_title = parts[0]
        rest = parts[1]
        series_title = rest.split("-")[0].strip()
        return episode_title or None, series_title or None
    return None, None


def extract_comic_action_series_id(html: str) -> Optional[str]:
    if not html:
        return None
    patterns = (
        r'"series_id"\s*:\s*"(\d+)"',
        r'&quot;series_id&quot;\s*:\s*&quot;(\d+)&quot;',
    )
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return None


def canonical_comic_action_episode_url(episode_id: str) -> str:
    return f"https://comic-action.com/episode/{episode_id}"


def canonical_comic_action_series_feed_url(feed_kind: str, series_id: str) -> str:
    return f"https://comic-action.com/{feed_kind}/series/{series_id}"


def parse_comic_action_episode_url(seed_url: str) -> Optional[str]:
    match = _EPISODE_URL.match(seed_url)
    if not match:
        return None
    return canonical_comic_action_episode_url(match.group(1))


def parse_comic_action_series_feed_url(seed_url: str) -> Optional[Tuple[str, str]]:
    match = _SERIES_FEED_URL.match(seed_url)
    if not match:
        return None
    return match.group(1), match.group(2)


def extract_comic_action_series_id_from_seed_url(seed_url: str) -> Optional[str]:
    parsed = parse_comic_action_series_feed_url(seed_url)
    if not parsed:
        return None
    _, series_id = parsed
    return series_id


def extract_comic_action_episode_url_from_feed(feed_text: str) -> Optional[str]:
    if not feed_text:
        return None
    decoded = html.unescape(feed_text)
    match = re.search(r"https?://comic-action\.com/episode/(\d+)", decoded)
    if not match:
        return None
    return canonical_comic_action_episode_url(match.group(1))


class ComicActionAdapter(SourceAdapter):
    source = "comic-action"

    def __init__(self, max_hops: int = 30):
        self.max_hops = max_hops

    def can_handle(self, seed_url: str) -> bool:
        return bool(parse_comic_action_episode_url(seed_url) or parse_comic_action_series_feed_url(seed_url))

    def normalize(self, seed_url: str) -> WorkDescriptor:
        normalized_episode_url = parse_comic_action_episode_url(seed_url)
        if normalized_episode_url:
            return WorkDescriptor(
                source=self.source,
                work_id=normalized_episode_url,
                seed_url=normalized_episode_url,
            )

        feed_match = parse_comic_action_series_feed_url(seed_url)
        if not feed_match:
            raise RuntimeError("comic-action: could not parse episode or series feed URL")

        feed_kind, series_id = feed_match
        stable_work_id = f"comic-action:{series_id}"
        return WorkDescriptor(
            source=self.source,
            work_id=stable_work_id,
            seed_url=canonical_comic_action_series_feed_url(feed_kind, series_id),
            metadata={
                "series": stable_work_id,
                "seriesId": series_id,
                "feedKind": feed_kind,
            },
        )

    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        entry_episode_url = self._resolve_entry_episode_url(work, http_client)
        latest_url, page_title, series_title, episode_title = self._walk_to_latest(
            WorkDescriptor(
                source=work.source,
                work_id=work.work_id,
                seed_url=entry_episode_url,
                metadata=work.metadata,
            ),
            http_client,
        )
        return LatestEpisode(
            source=self.source,
            work_id=work.work_id,
            latest_key=latest_url,
            url=latest_url,
            series_title=series_title,
            episode_title=episode_title,
            page_title=page_title,
        )

    def _resolve_entry_episode_url(self, work: WorkDescriptor, http_client: HttpClient) -> str:
        normalized_episode_url = parse_comic_action_episode_url(work.seed_url)
        if normalized_episode_url:
            return normalized_episode_url

        if not parse_comic_action_series_feed_url(work.seed_url):
            raise RuntimeError("comic-action: unsupported seed URL")

        feed_text = http_client.get_text(work.seed_url)
        episode_url = extract_comic_action_episode_url_from_feed(feed_text)
        if not episode_url:
            raise SourceParseError("comic-action: no episode URL found in series feed")
        return episode_url

    def _walk_to_latest(
        self,
        work: WorkDescriptor,
        http_client: HttpClient,
    ) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
        current_url = work.seed_url
        seen = set()
        last_html = None

        for _ in range(self.max_hops):
            if current_url in seen:
                break
            seen.add(current_url)
            html = self._fetch_episode_page(current_url, http_client)
            last_html = html
            next_url = self._parse_next_readable_url(html)
            if not next_url or next_url == current_url:
                page_title = html_title(html)
                episode_title, series_title = parse_comic_action_title(page_title or "")
                return current_url, page_title, series_title, episode_title
            current_url = next_url

        page_title = html_title(last_html or "")
        episode_title, series_title = parse_comic_action_title(page_title or "")
        return current_url, page_title, series_title, episode_title

    def _fetch_episode_page(self, episode_url: str, http_client: HttpClient) -> str:
        return http_client.get_text(episode_url)

    def _parse_next_readable_url(self, html: str) -> Optional[str]:
        match = re.search(r'nextReadableProductUri\"\s*:\s*\"(https?://[^\"]+)\"', html)
        if not match:
            match = re.search(r'nextReadableProductUri&quot;\s*:\s*&quot;(https?://[^&]+)&quot;', html)
        if not match:
            return None
        return match.group(1)
