import re
from typing import Optional, Tuple

from .base import HttpClient, LatestEpisode, SourceAdapter, SourceParseError, WorkDescriptor
from .util import html_title


def parse_comic_walker_title(page_title: str) -> Tuple[Optional[str], Optional[str]]:
    if not page_title:
        return None, None
    left = page_title.split("｜")[0].strip()
    match = re.match(r"^【([^】]+)】\s*(.+)$", left)
    if match:
        return match.group(2).strip() or None, match.group(1).strip() or None
    return left or None, None


class ComicWalkerAdapter(SourceAdapter):
    source = "comic-walker"
    _SUPPORTED_URL = re.compile(
        r"^https?://(?:www\.)?comic-walker\.com/detail/(KC_\d+_S)(?:/episodes/[^/?#]+)?/?(?:\?.*)?$"
    )

    def can_handle(self, seed_url: str) -> bool:
        return bool(self._SUPPORTED_URL.match(seed_url))

    def normalize(self, seed_url: str) -> WorkDescriptor:
        match = self._SUPPORTED_URL.match(seed_url)
        if not match:
            raise RuntimeError("comic-walker: could not parse series code")

        series_code = match.group(1)
        return WorkDescriptor(
            source=self.source,
            work_id=series_code,
            seed_url=f"https://comic-walker.com/detail/{series_code}",
            metadata={
                "series": series_code,
                "seriesCode": series_code,
            },
        )

    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        html = self._fetch_series_page(work, http_client)
        latest_code = self._parse_latest_episode_code(work, html)
        latest_url = f"{work.seed_url}/episodes/{latest_code}?episodeType=latest"

        series_title = None
        episode_title = None
        try:
            episode_html = self._fetch_episode_page(latest_url, http_client)
            title = html_title(episode_html)
            series_title, episode_title = parse_comic_walker_title(title or "")
        except Exception:
            title = html_title(html)
            series_title, _ = parse_comic_walker_title(title or "")

        return LatestEpisode(
            source=self.source,
            work_id=work.work_id,
            latest_key=latest_code,
            url=latest_url,
            series=work.metadata.get("series") or work.work_id,
            series_title=series_title,
            episode_code=latest_code,
            episode_title=episode_title,
        )

    def _fetch_series_page(self, work: WorkDescriptor, http_client: HttpClient) -> str:
        return http_client.get_text(work.seed_url)

    def _fetch_episode_page(self, episode_url: str, http_client: HttpClient) -> str:
        return http_client.get_text(episode_url)

    def _parse_latest_episode_code(self, work: WorkDescriptor, html: str) -> str:
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
        if not match:
            raise SourceParseError("comic-walker: __NEXT_DATA__ not found")

        raw = match.group(1)
        series_code = work.metadata.get("seriesCode") or work.work_id
        prefix = series_code[:-2]
        codes = set(re.findall(rf"{re.escape(prefix)}\d+_E", raw))
        if not codes:
            codes = set(re.findall(r"KC_\d+\d+_E", raw))
        if not codes:
            raise SourceParseError("comic-walker: no episode codes found")

        return max(codes, key=lambda code: self._episode_sort_key(code, prefix))

    def _episode_sort_key(self, episode_code: str, prefix: str) -> int:
        match = re.search(rf"{re.escape(prefix)}(\d+)_E", episode_code)
        return int(match.group(1)) if match else -1
