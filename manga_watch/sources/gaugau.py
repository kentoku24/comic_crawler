import re
from typing import Optional, Tuple

from .base import HttpClient, LatestEpisode, SourceAdapter, SourceParseError, WorkDescriptor
from .util import html_title


_WORK_URL = re.compile(
    r"^https?://gaugau\.futabanet\.jp/list/work/([A-Za-z0-9]+)(?:/)?(?:\?.*)?$"
)


def canonical_gaugau_work_url(work_token: str) -> str:
    return f"https://gaugau.futabanet.jp/list/work/{work_token}"


def parse_gaugau_work_url(seed_url: str) -> Optional[str]:
    match = _WORK_URL.match(seed_url)
    if not match:
        return None
    return canonical_gaugau_work_url(match.group(1))


def extract_gaugau_work_token(seed_url: str) -> Optional[str]:
    match = _WORK_URL.match(seed_url)
    if not match:
        return None
    return match.group(1)


def extract_gaugau_latest_episode_url(html_text: str, work_token: str) -> Optional[str]:
    if not html_text or not work_token:
        return None
    episode_url_pattern = rf"https?://gaugau\.futabanet\.jp/list/work/{re.escape(work_token)}/episodes/\d+"
    grid_pattern = rf'<div\b[^>]*episode__grid[^>]*>.*?href="({episode_url_pattern})"'
    for match in re.finditer(grid_pattern, html_text, re.I | re.S):
        href_match = re.search(episode_url_pattern, match.group(1))
        if href_match:
            return href_match.group(0)

    fallback_match = re.search(episode_url_pattern, html_text)
    if fallback_match:
        return fallback_match.group(0)
    return None


def parse_gaugau_title(page_title: str) -> Tuple[Optional[str], Optional[str]]:
    normalized = str(page_title or "").strip()
    if not normalized:
        return None, None

    match = re.match(r"^公式-(?P<series>.+?)\s+(?P<episode>第[^|]+?)\s*\|", normalized)
    if match:
        return match.group("series").strip() or None, match.group("episode").strip() or None

    match = re.match(r"^公式-(?P<series>.+?)\s*\|", normalized)
    if match:
        return match.group("series").strip() or None, None

    return None, None


class GaugauAdapter(SourceAdapter):
    source = "gaugau"

    def can_handle(self, seed_url: str) -> bool:
        return bool(parse_gaugau_work_url(seed_url))

    def normalize(self, seed_url: str) -> WorkDescriptor:
        normalized_work_url = parse_gaugau_work_url(seed_url)
        work_token = extract_gaugau_work_token(seed_url)
        if not normalized_work_url or not work_token:
            raise RuntimeError(f"{self.source}: could not parse work URL: {seed_url}")

        stable_work_id = f"{self.source}:{work_token}"
        return WorkDescriptor(
            source=self.source,
            work_id=stable_work_id,
            seed_url=normalized_work_url,
            metadata={
                "series": stable_work_id,
                "workToken": work_token,
            },
        )

    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        work_token = work.metadata.get("workToken") or extract_gaugau_work_token(work.seed_url)
        if not work_token:
            raise RuntimeError(f"{self.source}: workToken is required")

        work_url = canonical_gaugau_work_url(work_token)
        work_html = http_client.get_text(work_url)
        latest_url = extract_gaugau_latest_episode_url(work_html, work_token)
        if not latest_url:
            raise SourceParseError(f"{self.source}: latest episode URL not found")

        latest_html = http_client.get_text(latest_url)
        page_title = html_title(latest_html)
        series_title, episode_title = parse_gaugau_title(page_title or "")
        if not series_title:
            work_page_title = html_title(work_html)
            series_title, _ = parse_gaugau_title(work_page_title or "")
        if not episode_title:
            match = re.search(r'<h1[^>]*class="detailHead__title"[^>]*>(.*?)</h1>', latest_html, re.I | re.S)
            if match:
                episode_title = re.sub(r"<[^>]+>", "", match.group(1)).strip() or None

        return LatestEpisode(
            source=self.source,
            work_id=work.work_id,
            latest_key=latest_url,
            url=latest_url,
            series=work.metadata.get("series"),
            series_title=series_title,
            episode_title=episode_title,
            page_title=page_title,
        )
