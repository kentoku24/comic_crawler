import re
from typing import Optional, Tuple

from .base import HttpClient, LatestEpisode, SourceAdapter, WorkDescriptor
from .util import html_title


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


class ComicActionAdapter(SourceAdapter):
    source = "comic-action"

    def __init__(self, max_hops: int = 30):
        self.max_hops = max_hops

    def can_handle(self, seed_url: str) -> bool:
        return "comic-action.com/episode/" in seed_url

    def normalize(self, seed_url: str) -> WorkDescriptor:
        return WorkDescriptor(
            source=self.source,
            work_id=seed_url,
            seed_url=seed_url,
        )

    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        latest_url, page_title, series_title, episode_title = self._walk_to_latest(work, http_client)
        return LatestEpisode(
            source=self.source,
            work_id=work.work_id,
            latest_key=latest_url,
            url=latest_url,
            series_title=series_title,
            episode_title=episode_title,
            page_title=page_title,
        )

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
