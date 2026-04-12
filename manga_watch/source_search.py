from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Callable, Dict, List, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlsplit, urlunsplit

from manga_watch.sources import REGISTERED_SOURCES, normalize_seed_url
from manga_watch.sources.base import HttpClient, RequestsHttpClient

UNSUPPORTED_SEARCH_SOURCES: tuple[str, ...] = ("comic-walker",)
SUPPORTED_SEARCH_SOURCES: tuple[str, ...] = tuple(
    source for source in REGISTERED_SOURCES if source not in UNSUPPORTED_SEARCH_SOURCES
)
DEFAULT_SEARCH_LIMIT = 10
SEARCH_RESULT_LIMIT = 25
_DDG_SEARCH_URL = "https://duckduckgo.com/html/?q={query}"

_SOURCE_SEARCH_TARGETS: Dict[str, tuple[str, ...]] = {
    "champion-cross": ("championcross.jp",),
    "comic-action": ("comic-action.com",),
    "comic-earthstar": ("comic-earthstar.com",),
    "comic-trail": ("comic-trail.com",),
    "comicborder": ("comicborder.com",),
    "firecross": ("firecross.jp",),
    "kakuyomu": ("kakuyomu.jp",),
    "kuragebunch": ("kuragebunch.com",),
    "magapoke": ("pocket.shonenmagazine.com", "pocket.shonenmagazine.com/rss"),
    "nicovideo-manga": ("manga.nicovideo.jp", "sp.manga.nicovideo.jp"),
    "shonenjumpplus": ("shonenjumpplus.com",),
    "sunday-webry": ("sunday-webry.com",),
    "takecomic": ("takecomic.jp",),
}


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


def _search_with_duckduckgo(
    source: str,
    query: str,
    http_client: HttpClient,
    *,
    limit: int,
) -> List[SearchResult]:
    domains = _SOURCE_SEARCH_TARGETS.get(source)
    if not domains:
        raise UnsupportedSourceSearchError(f"unsupported search source: {source}")

    search_query = f"{query} {' OR '.join(f'site:{domain}' for domain in domains)}"
    html_text = http_client.get_text(_DDG_SEARCH_URL.format(query=quote_plus(search_query)))
    return _extract_duckduckgo_results(html_text, source=source, limit=limit)


def _extract_duckduckgo_results(html_text: str, *, source: str, limit: int) -> List[SearchResult]:
    results: List[SearchResult] = []
    seen_seed_urls = set()

    for match in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html_text, re.I | re.S):
        resolved_url = _resolve_duckduckgo_result_url(match.group(1))
        if not resolved_url:
            continue

        canonical_seed_url = _canonical_seed_url_for_source(source, resolved_url)
        if not canonical_seed_url or canonical_seed_url in seen_seed_urls:
            continue

        title = _normalize_anchor_text(match.group(2))
        if not title:
            title = canonical_seed_url

        seen_seed_urls.add(canonical_seed_url)
        results.append(
            SearchResult(
                source=source,
                title=title,
                seed_url=canonical_seed_url,
                subtitle=source,
            )
        )
        if len(results) >= limit:
            break

    return results


def _resolve_duckduckgo_result_url(href: str) -> Optional[str]:
    normalized = unescape(str(href or "")).strip().replace("\\/", "/")
    if not normalized:
        return None

    if normalized.startswith("/"):
        parsed = urlsplit(urljoin("https://duckduckgo.com", normalized))
        query = parse_qs(parsed.query)
        values = query.get("uddg")
        if values:
            return unquote(values[0])

    parsed = urlsplit(normalized)
    if parsed.scheme in ("http", "https"):
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return None


def _canonical_seed_url_for_source(source: str, candidate_url: str) -> Optional[str]:
    try:
        descriptor = normalize_seed_url(candidate_url)
    except Exception:
        return None
    if descriptor.source != source:
        return None
    return descriptor.seed_url


def _normalize_anchor_text(text: str) -> str:
    normalized = re.sub(r"<[^>]+>", "", text or "")
    normalized = unescape(re.sub(r"\s+", " ", normalized)).strip()
    normalized = re.sub(r"^最新UP!?\s*", "", normalized)
    return normalized


_SEARCHERS: Dict[str, Callable[..., List[SearchResult]]] = {
    source: (lambda query, http_client, *, limit, _source=source: _search_with_duckduckgo(_source, query, http_client, limit=limit))
    for source in SUPPORTED_SEARCH_SOURCES
}
