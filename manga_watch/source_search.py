from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Callable, Dict, List, Optional
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from manga_watch.sources.base import HttpClient, RequestsHttpClient

SUPPORTED_SEARCH_SOURCES: tuple[str, ...] = ("champion-cross", "kakuyomu")
DEFAULT_SEARCH_LIMIT = 10
SEARCH_RESULT_LIMIT = 25


@dataclass(frozen=True)
class SearchResult:
    source: str
    title: str
    seed_url: str
    subtitle: Optional[str] = None


class UnsupportedSourceSearchError(ValueError):
    pass


def supported_search_sources() -> tuple[str, ...]:
    return SUPPORTED_SEARCH_SOURCES


def searchable_source_choices() -> List[Dict[str, str]]:
    return [{"name": source, "value": source} for source in supported_search_sources()]


def search_source(
    source: str,
    query: str,
    *,
    http_client: Optional[HttpClient] = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> List[SearchResult]:
    normalized_source = str(source or "").strip()
    normalized_query = str(query or "").strip()
    if not normalized_source:
        raise ValueError("search source is required")
    if not normalized_query:
        raise ValueError("search query is required")

    searcher = _SEARCHERS.get(normalized_source)
    if searcher is None:
        raise UnsupportedSourceSearchError(f"unsupported search source: {normalized_source}")

    client = http_client or RequestsHttpClient()
    safe_limit = max(1, min(int(limit), SEARCH_RESULT_LIMIT))
    return searcher(normalized_query, client, limit=safe_limit)


def _search_kakuyomu(query: str, http_client: HttpClient, *, limit: int) -> List[SearchResult]:
    html = http_client.get_text(f"https://kakuyomu.jp/search?q={quote(query)}")
    return _extract_anchor_results(
        html,
        source="kakuyomu",
        base_url="https://kakuyomu.jp",
        href_pattern="/works/",
        limit=limit,
    )


def _search_champion_cross(query: str, http_client: HttpClient, *, limit: int) -> List[SearchResult]:
    html = http_client.get_text(f"https://championcross.jp/search?keyword={quote(query)}")
    results: List[SearchResult] = []
    seen_urls = set()
    for match in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.I | re.S):
        href = unescape(match.group(1)).replace("\\/", "/")
        if "/series/" not in href:
            continue
        title = ""
        alt_match = re.search(r'alt="([^"]+)"', match.group(2), re.I | re.S)
        if alt_match:
            title = _normalize_anchor_text(alt_match.group(1))
            title = re.sub(r"【.*$", "", title).strip()
        if not title:
            title = _normalize_anchor_text(match.group(2))
        if not title:
            continue
        seed_url = _normalize_result_url(urljoin("https://championcross.jp", href))
        if seed_url in seen_urls:
            continue
        seen_urls.add(seed_url)
        results.append(
            SearchResult(
                source="champion-cross",
                title=title,
                seed_url=seed_url,
                subtitle="champion-cross",
            )
        )
        if len(results) >= limit:
            break
    return results


def _extract_anchor_results(
    html_text: str,
    *,
    source: str,
    base_url: str,
    href_pattern: str,
    limit: int,
) -> List[SearchResult]:
    results: List[SearchResult] = []
    seen_urls = set()
    for match in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html_text, re.I | re.S):
        href = unescape(match.group(1)).replace("\\/", "/")
        if href_pattern not in href:
            continue
        if source == "kakuyomu" and "/episodes/" in href:
            continue
        title_attr_match = re.search(r'title="([^"]+)"', match.group(0), re.I | re.S)
        title = _normalize_anchor_text(title_attr_match.group(1) if title_attr_match else match.group(2))
        if not title:
            continue
        seed_url = _normalize_result_url(urljoin(base_url, href))
        if seed_url in seen_urls:
            continue
        seen_urls.add(seed_url)
        results.append(
            SearchResult(
                source=source,
                title=title,
                seed_url=seed_url,
                subtitle=source,
            )
        )
        if len(results) >= limit:
            break
    return results


def _normalize_anchor_text(text: str) -> str:
    normalized = re.sub(r"<[^>]+>", "", text or "")
    normalized = unescape(re.sub(r"\s+", " ", normalized)).strip()
    normalized = re.sub(r"^最新UP!?\s*", "", normalized)
    return normalized


def _normalize_result_url(url: str) -> str:
    parts = urlsplit(url)
    normalized = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return normalized.rstrip("/")


_SEARCHERS: Dict[str, Callable[..., List[SearchResult]]] = {
    "champion-cross": _search_champion_cross,
    "kakuyomu": _search_kakuyomu,
}
