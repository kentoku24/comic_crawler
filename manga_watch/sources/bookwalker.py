import re
from html import unescape
from typing import Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from .base import HttpClient, LatestEpisode, SourceAdapter, SourceParseError, WorkDescriptor
from .util import html_title


_BOOK_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_SERIES_URL = re.compile(r"^https?://(?:www\.)?bookwalker\.jp/series/(\d+)(/list)?/?(?:\?.*)?$")
_BOOK_URL = re.compile(rf"^https?://(?:www\.)?bookwalker\.jp/de({_BOOK_UUID})/?(?:\?.*)?$")


def canonical_bookwalker_series_url(series_id: str, *, list_page: bool) -> str:
    suffix = "list/" if list_page else ""
    return f"https://bookwalker.jp/series/{series_id}/{suffix}"


def canonical_bookwalker_book_url(book_uuid: str) -> str:
    return f"https://bookwalker.jp/de{book_uuid}/"


def parse_bookwalker_url(seed_url: str) -> Optional[Tuple[str, str, str]]:
    normalized = _strip_query(seed_url)
    series_match = _SERIES_URL.match(normalized)
    if series_match:
        series_id = series_match.group(1)
        list_page = bool(series_match.group(2))
        return (
            "series",
            series_id,
            canonical_bookwalker_series_url(series_id, list_page=list_page),
        )

    book_match = _BOOK_URL.match(normalized)
    if book_match:
        book_uuid = book_match.group(1)
        return ("book", book_uuid, canonical_bookwalker_book_url(book_uuid))

    return None


def parse_bookwalker_series_title(page_title: str) -> Optional[str]:
    title = _clean_text(page_title)
    if not title:
        return None
    title = re.sub(r"^【話・連載】", "", title)
    title = re.split(r"\s*[|-]\s*(?:話・連載.*|BOOK☆WALKER|電子書籍.*)$", title, maxsplit=1)[0]
    title = re.sub(r"一覧$", "", title).strip()
    return title or None


def _strip_query(url: str) -> str:
    parsed = urlsplit(str(url or "").strip())
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")).rstrip("/") + "/"


def _clean_text(text: str) -> str:
    value = re.sub(r"<[^>]+>", "", text or "")
    value = unescape(value).replace("\u3000", " ")
    return re.sub(r"\s+", " ", value).strip()


def _attribute(markup: str, name: str) -> str:
    match = re.search(rf'\b{name}\s*=\s*(["\'])(.*?)\1', markup, re.I | re.S)
    return unescape(match.group(2)) if match else ""


def _book_key(book_uuid: str) -> str:
    return f"bookwalker:book:{book_uuid}"


class BookwalkerAdapter(SourceAdapter):
    source = "bookwalker"

    def can_handle(self, seed_url: str) -> bool:
        return parse_bookwalker_url(seed_url) is not None

    def normalize(self, seed_url: str) -> WorkDescriptor:
        parsed = parse_bookwalker_url(seed_url)
        if not parsed:
            raise RuntimeError("bookwalker: could not parse series or book URL")

        kind, identifier, canonical_url = parsed
        if kind == "series":
            series = f"bookwalker:series:{identifier}"
            return WorkDescriptor(
                source=self.source,
                work_id=series,
                seed_url=canonical_url,
                metadata={
                    "series": series,
                    "seriesId": identifier,
                },
            )

        return WorkDescriptor(
            source=self.source,
            work_id=_book_key(identifier),
            seed_url=canonical_url,
            metadata={"bookUuid": identifier},
        )

    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        html = http_client.get_text(work.seed_url)
        series_title = parse_bookwalker_series_title(html_title(html) or "")
        next_update_label = _extract_next_update_label(html)

        latest = _extract_latest_episode_item(html)
        if latest is None:
            latest = _extract_latest_book_item(html)
        if latest is None:
            raise SourceParseError("bookwalker: latest book item not found")

        book_uuid, episode_title, public_url = latest
        series = work.metadata.get("series")
        if series is None:
            series_id = _extract_series_id(html)
            if series_id:
                series = f"bookwalker:series:{series_id}"

        return LatestEpisode(
            source=self.source,
            work_id=work.work_id,
            latest_key=_book_key(book_uuid),
            url=public_url or work.seed_url,
            series=series,
            series_title=series_title,
            episode_code=book_uuid,
            episode_title=episode_title,
            page_title=episode_title,
            update_type="main_story",
            classification_reason="bookwalker latest item is treated as a primary release",
            extra={"nextUpdateLabel": next_update_label} if next_update_label else {},
        )


def _extract_latest_episode_item(html: str) -> Optional[Tuple[str, str, str]]:
    items = []
    for match in re.finditer(r"<a\b(?=[^>]*data-book-uuid=)[^>]*>", html, re.I | re.S):
        anchor = match.group(0)
        uuid = _attribute(anchor, "data-book-uuid")
        title = _clean_text(_attribute(anchor, "data-book-title"))
        if not uuid or not title:
            continue
        items.append((uuid, title, ""))
    return items[-1] if items else None


def _extract_latest_book_item(html: str) -> Optional[Tuple[str, str, str]]:
    for block in _iter_book_blocks(html):
        link_match = re.search(rf'<a\b[^>]*href="(https://bookwalker\.jp/de({_BOOK_UUID})/[^"]*)"[^>]*>(.*?)</a>', block, re.I | re.S)
        if not link_match:
            continue

        url = canonical_bookwalker_book_url(link_match.group(2))
        title = _attribute(link_match.group(0), "title") or _clean_text(link_match.group(3))
        if not title:
            image_match = re.search(r"<img\b[^>]*>", block, re.I | re.S)
            title = _attribute(image_match.group(0), "alt") if image_match else ""
        title = _clean_text(title)
        if not title:
            continue
        return (link_match.group(2), title, url)
    return None


def _iter_book_blocks(html: str):
    patterns = (
        r'<(?:article|div)\b[^>]*class="[^"]*\bm-book-item\b[^"]*"[^>]*>.*?(?=<(?:article|div)\b[^>]*class="[^"]*\bm-book-item\b|</ul>|</section>|$)',
        r'<article\b[^>]*class="[^"]*\bt-c-series-card\b[^"]*"[^>]*>.*?(?=<article\b[^>]*class="[^"]*\bt-c-series-card\b|</ul>|</section>|$)',
    )
    for pattern in patterns:
        for match in re.finditer(pattern, html, re.I | re.S):
            yield match.group(0)


def _extract_next_update_label(html: str) -> Optional[str]:
    time_match = re.search(r"<time\b[^>]*>(.*?)</time>\s*([^<]{0,20}配信予定)", html, re.I | re.S)
    if time_match:
        label = _clean_text(f"{time_match.group(1)} {time_match.group(2)}")
        if label:
            return label

    update_match = re.search(r"(\d{4}/\d{1,2}/\d{1,2}\([^)]*\)\s*更新)", html)
    if update_match:
        return _clean_text(update_match.group(1))
    return None


def _extract_series_id(html: str) -> Optional[str]:
    for pattern in (r'data-book-series-id="(\d+)"', r'data-series-id="(\d+)"', r"/series/(\d+)/"):
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return None
