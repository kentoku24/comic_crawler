import html
import re
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

from .base import HttpClient, LatestEpisode, SourceAdapter, SourceParseError, WorkDescriptor
from .util import html_title


_EPISODE_URL = re.compile(
    r"^https?://(?:www\.)?comic-action\.com/episode/(\d+)/?(?:\?.*)?$"
)
_SERIES_FEED_URL = re.compile(
    r"^https?://(?:www\.)?comic-action\.com/(rss|atom)/series/(\d+)(?:/)?(?:\?.*)?$"
)
_EPISODE_TITLE_NUMBER = re.compile(r"第\s*(\d+)\s*話")


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

    try:
        root = ET.fromstring(html.unescape(feed_text))
    except ET.ParseError:
        return None

    channel = _first_child_named(root, "channel")
    if channel is not None:
        for item in _children_named(channel, "item"):
            latest_url = parse_comic_action_episode_url(_child_text(item, "link"))
            if latest_url:
                return latest_url
        return None

    for entry in _children_named(root, "entry"):
        for link in _children_named(entry, "link"):
            latest_url = parse_comic_action_episode_url((link.get("href") or "").strip())
            if latest_url:
                return latest_url
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children_named(element: ET.Element, name: str) -> Tuple[ET.Element, ...]:
    return tuple(child for child in element if _local_name(child.tag) == name)


def _first_child_named(element: ET.Element, name: str) -> Optional[ET.Element]:
    for child in _children_named(element, name):
        return child
    return None


def _child_text(element: ET.Element, name: str) -> str:
    child = _first_child_named(element, name)
    return (child.text or "").strip() if child is not None else ""


def extract_comic_action_next_update_label(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    match = re.search(r"次回更新[:：]\s*([^<]+)", html_text)
    if not match:
        return None
    label = re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()
    return label or None


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
        latest_url = None
        page_title = None
        series_title = None
        episode_title = None
        next_update_label = None

        feed_match = parse_comic_action_series_feed_url(work.seed_url)
        if feed_match:
            latest_url, page_title, series_title, episode_title, next_update_label, _ = (
                self._fetch_latest_from_series_feed_url(work.seed_url, http_client)
            )
        else:
            entry_episode_url = self._resolve_entry_episode_url(work, http_client)
            entry_html = self._fetch_episode_page(entry_episode_url, http_client)
            next_url = self._parse_next_readable_url(entry_html)
            series_id = extract_comic_action_series_id(entry_html)
            if series_id and (not next_url or next_url == entry_episode_url):
                latest_url, page_title, series_title, episode_title, next_update_label = self._snapshot_from_episode_html(
                    entry_episode_url,
                    entry_html,
                )
                try:
                    feed_snapshot = self._fetch_latest_from_series_feed_url(
                        canonical_comic_action_series_feed_url("rss", series_id),
                        http_client,
                    )
                except Exception:
                    feed_snapshot = None
                if feed_snapshot and self._should_prefer_feed_snapshot(
                    entry_html=entry_html,
                    feed_html=feed_snapshot[5],
                ):
                    latest_url, page_title, series_title, episode_title, next_update_label, _ = feed_snapshot

            if latest_url is None:
                latest_url, page_title, series_title, episode_title, next_update_label = self._walk_to_latest(
                    WorkDescriptor(
                        source=work.source,
                        work_id=work.work_id,
                        seed_url=entry_episode_url,
                        metadata=work.metadata,
                    ),
                    http_client,
                    initial_html=entry_html,
                )

        return LatestEpisode(
            source=self.source,
            work_id=work.work_id,
            latest_key=latest_url,
            url=latest_url,
            series_title=series_title,
            episode_title=episode_title,
            page_title=page_title,
            extra={"nextUpdateLabel": next_update_label} if next_update_label else {},
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

    def _fetch_latest_from_series_feed_url(
        self,
        feed_url: str,
        http_client: HttpClient,
    ) -> Tuple[str, Optional[str], Optional[str], Optional[str], Optional[str], str]:
        feed_text = http_client.get_text(feed_url)
        latest_url = extract_comic_action_episode_url_from_feed(feed_text)
        if not latest_url:
            raise SourceParseError("comic-action: no episode URL found in series feed")
        html = self._fetch_episode_page(latest_url, http_client)
        page_title, series_title, episode_title, next_update_label = self._snapshot_from_episode_html(
            latest_url,
            html,
        )[1:]
        return latest_url, page_title, series_title, episode_title, next_update_label, html

    def _snapshot_from_episode_html(
        self,
        episode_url: str,
        html_text: str,
    ) -> Tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]:
        page_title = html_title(html_text)
        episode_title, series_title = parse_comic_action_title(page_title or "")
        next_update_label = extract_comic_action_next_update_label(html_text)
        return episode_url, page_title, series_title, episode_title, next_update_label

    def _should_prefer_feed_snapshot(
        self,
        *,
        entry_html: str,
        feed_html: str,
    ) -> bool:
        entry_number = self._episode_sort_number(entry_html)
        feed_number = self._episode_sort_number(feed_html)
        if entry_number is None or feed_number is None:
            return False
        return feed_number > entry_number

    def _episode_sort_number(self, html_text: str) -> Optional[int]:
        decoded = html.unescape(html_text or "")
        match = re.search(r'"number"\s*:\s*(\d+)', decoded)
        if match:
            return int(match.group(1))
        title = html_title(html_text or "") or ""
        match = _EPISODE_TITLE_NUMBER.search(title)
        if match:
            return int(match.group(1))
        return None

    def _walk_to_latest(
        self,
        work: WorkDescriptor,
        http_client: HttpClient,
        *,
        initial_html: Optional[str] = None,
    ) -> Tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]:
        current_url = work.seed_url
        seen = set()
        last_html = initial_html

        for _ in range(self.max_hops):
            if current_url in seen:
                break
            seen.add(current_url)
            if current_url == work.seed_url and initial_html is not None:
                html = initial_html
            else:
                html = self._fetch_episode_page(current_url, http_client)
            last_html = html
            next_url = self._parse_next_readable_url(html)
            if not next_url or next_url == current_url:
                page_title = html_title(html)
                episode_title, series_title = parse_comic_action_title(page_title or "")
                next_update_label = extract_comic_action_next_update_label(html)
                return current_url, page_title, series_title, episode_title, next_update_label
            current_url = next_url

        page_title = html_title(last_html or "")
        episode_title, series_title = parse_comic_action_title(page_title or "")
        next_update_label = extract_comic_action_next_update_label(last_html or "")
        return current_url, page_title, series_title, episode_title, next_update_label

    def _fetch_episode_page(self, episode_url: str, http_client: HttpClient) -> str:
        return http_client.get_text(episode_url)

    def _parse_next_readable_url(self, html: str) -> Optional[str]:
        match = re.search(r'nextReadableProductUri\"\s*:\s*\"(https?://[^\"]+)\"', html)
        if not match:
            match = re.search(r'nextReadableProductUri&quot;\s*:\s*&quot;(https?://[^&]+)&quot;', html)
        if not match:
            return None
        return match.group(1)
