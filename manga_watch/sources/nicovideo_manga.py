import html
import re
from typing import Optional, Tuple

from .base import HttpClient, LatestEpisode, SourceAdapter, SourceParseError, WorkDescriptor
from .util import html_title


_CANONICAL_HOST = "manga.nicovideo.jp"
_SP_HOST = "sp.manga.nicovideo.jp"
_COMIC_URL = re.compile(
    r"^https?://(?:sp\.)?manga\.nicovideo\.jp/comic/(\d+)(?:/)?(?:\?.*)?$"
)
_WATCH_URL = re.compile(
    r"https?://manga\.nicovideo\.jp/watch/(mg\d+)(?:[/?\"'&]|$)"
)
_WATCH_PATH = re.compile(r"/watch/(mg\d+)(?:[/?\"'&]|$)")
_TITLE_SUFFIX = " - ニコニコ漫画"
_TITLE_PATTERN = re.compile(r"^(?P<series>.+)\s+(?P<episode>第.+?)\s*/\s*(?P<author>.+)$")


def canonical_nicovideo_manga_comic_url(comic_id: str) -> str:
    return f"https://{_CANONICAL_HOST}/comic/{comic_id}"


def canonical_nicovideo_manga_latest_url(comic_id: str) -> str:
    return f"{canonical_nicovideo_manga_comic_url(comic_id)}/new"


def canonical_nicovideo_manga_watch_url(watch_id: str) -> str:
    return f"https://{_CANONICAL_HOST}/watch/{watch_id}"


def parse_nicovideo_manga_comic_url(seed_url: str) -> Optional[str]:
    match = _COMIC_URL.match(seed_url)
    if not match:
        return None
    return canonical_nicovideo_manga_comic_url(match.group(1))


def extract_nicovideo_manga_comic_id(seed_url: str) -> Optional[str]:
    match = _COMIC_URL.match(seed_url)
    if not match:
        return None
    return match.group(1)


def extract_nicovideo_manga_watch_url(html_text: str) -> Optional[str]:
    if not html_text:
        return None

    normalized = html.unescape(html_text).replace("\\/", "/")
    match = _WATCH_URL.search(normalized)
    if match:
        return canonical_nicovideo_manga_watch_url(match.group(1))

    match = _WATCH_PATH.search(normalized)
    if match:
        return canonical_nicovideo_manga_watch_url(match.group(1))
    return None


def parse_nicovideo_manga_title(page_title: str) -> Tuple[Optional[str], Optional[str]]:
    normalized = str(page_title or "").strip()
    if not normalized:
        return None, None
    if normalized.endswith(_TITLE_SUFFIX):
        normalized = normalized[: -len(_TITLE_SUFFIX)].rstrip()

    match = _TITLE_PATTERN.match(normalized)
    if not match:
        return None, None
    series_title = match.group("series").strip()
    episode_title = match.group("episode").strip()
    return series_title or None, episode_title or None


class NicovideoMangaAdapter(SourceAdapter):
    source = "nicovideo-manga"

    def can_handle(self, seed_url: str) -> bool:
        return bool(parse_nicovideo_manga_comic_url(seed_url))

    def normalize(self, seed_url: str) -> WorkDescriptor:
        normalized_comic_url = parse_nicovideo_manga_comic_url(seed_url)
        comic_id = extract_nicovideo_manga_comic_id(seed_url)
        if not normalized_comic_url or not comic_id:
            raise RuntimeError(f"{self.source}: could not parse comic URL: {seed_url}")

        stable_work_id = f"{self.source}:{comic_id}"
        return WorkDescriptor(
            source=self.source,
            work_id=stable_work_id,
            seed_url=normalized_comic_url,
            metadata={
                "series": stable_work_id,
                "comicId": comic_id,
            },
        )

    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        comic_id = work.metadata.get("comicId") or extract_nicovideo_manga_comic_id(work.seed_url)
        if not comic_id:
            raise RuntimeError(f"{self.source}: comicId is required")

        latest_page_url = canonical_nicovideo_manga_latest_url(comic_id)
        html_text = http_client.get_text(latest_page_url)
        latest_url = extract_nicovideo_manga_watch_url(html_text)
        if not latest_url:
            raise SourceParseError(f"{self.source}: latest watch URL not found")

        page_title = html_title(html_text)
        series_title, episode_title = parse_nicovideo_manga_title(page_title or "")

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
