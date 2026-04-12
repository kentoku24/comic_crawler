from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Callable, Dict, List, Optional
from urllib.parse import quote_plus, urljoin, urlsplit, urlunsplit

from manga_watch.sources import REGISTERED_SOURCES, normalize_seed_url
from manga_watch.sources.base import HttpClient, RequestsHttpClient

DEFAULT_SEARCH_LIMIT = 10
SEARCH_RESULT_LIMIT = 25

_SOURCE_SEARCH_CONFIG: Dict[str, Dict[str, object]] = {
    "comic-walker": {
        "search_url": "https://comic-walker.com/search?q={query}",
        "allowed_domains": ("comic-walker.com", "www.comic-walker.com"),
    },
    "comic-action": {
        "search_url": "https://comic-action.com/search?keyword={query}",
        "allowed_domains": ("comic-action.com", "www.comic-action.com"),
    },
    "comic-earthstar": {
        "search_url": "https://comic-earthstar.com/search?keyword={query}",
        "allowed_domains": ("comic-earthstar.com", "www.comic-earthstar.com"),
    },
    "comicborder": {
        "search_url": "https://comicborder.com/search?keyword={query}",
        "allowed_domains": ("comicborder.com", "www.comicborder.com"),
    },
    "comic-trail": {
        "search_url": "https://comic-trail.com/search?keyword={query}",
        "allowed_domains": ("comic-trail.com", "www.comic-trail.com"),
    },
    "kuragebunch": {
        "search_url": "https://kuragebunch.com/search?keyword={query}",
        "allowed_domains": ("kuragebunch.com", "www.kuragebunch.com"),
    },
    "shonenjumpplus": {
        "search_url": "https://shonenjumpplus.com/search?query={query}",
        "allowed_domains": ("shonenjumpplus.com", "www.shonenjumpplus.com"),
    },
    "sunday-webry": {
        "search_url": "https://www.sunday-webry.com/search?query={query}",
        "allowed_domains": ("sunday-webry.com", "www.sunday-webry.com"),
    },
    "champion-cross": {
        "search_url": "https://championcross.jp/search?keyword={query}",
        "allowed_domains": ("championcross.jp", "www.championcross.jp"),
    },
    "magapoke": {
        "search_url": "https://pocket.shonenmagazine.com/search?query={query}",
        "allowed_domains": ("pocket.shonenmagazine.com",),
    },
    "firecross": {
        "search_url": "https://firecross.jp/search?keyword={query}",
        "allowed_domains": ("firecross.jp", "www.firecross.jp"),
    },
    "takecomic": {
        "search_url": "https://takecomic.jp/search?keyword={query}",
        "allowed_domains": ("takecomic.jp", "www.takecomic.jp"),
    },
    "nicovideo-manga": {
        "search_url": "https://manga.nicovideo.jp/search?keyword={query}",
        "allowed_domains": ("manga.nicovideo.jp", "sp.manga.nicovideo.jp"),
    },
    "kakuyomu": {
        "search_url": "https://kakuyomu.jp/search?q={query}",
        "allowed_domains": ("kakuyomu.jp", "www.kakuyomu.jp"),
    },
}

_CONFIGURED_SOURCE_NAMES = set(_SOURCE_SEARCH_CONFIG)

# Search capability is opt-in per source; keep registry order and expose only configured ones.
SUPPORTED_SEARCH_SOURCES: tuple[str, ...] = tuple(
    source for source in REGISTERED_SOURCES if source in _CONFIGURED_SOURCE_NAMES
)

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


def _search_via_public_site(
    source: str,
    query: str,
    http_client: HttpClient,
    *,
    limit: int,
) -> List[SearchResult]:
    config = _SOURCE_SEARCH_CONFIG.get(source)
    if not config:
        raise UnsupportedSourceSearchError(f"unsupported search source: {source}")

    search_url = str(config["search_url"]).format(query=quote_plus(query))
    allowed_domains = tuple(str(domain).lower() for domain in config["allowed_domains"])
    html_text = http_client.get_text(search_url)

    return _extract_anchor_results(
        html_text,
        source=source,
        search_url=search_url,
        allowed_domains=allowed_domains,
        limit=limit,
    )


def _extract_anchor_results(
    html_text: str,
    *,
    source: str,
    search_url: str,
    allowed_domains: tuple[str, ...],
    limit: int,
) -> List[SearchResult]:
    results: List[SearchResult] = []
    seen_seed_urls = set()

    for match in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html_text, re.I | re.S):
        resolved_url = _resolve_result_url(match.group(1), search_url=search_url)
        if not resolved_url:
            continue
        if not _is_allowed_domain(resolved_url, allowed_domains):
            continue

        canonical_seed_url = _canonical_seed_url_for_source(source, resolved_url)
        if not canonical_seed_url or canonical_seed_url in seen_seed_urls:
            continue

        title_attr_match = re.search(r'title="([^"]+)"', match.group(0), re.I | re.S)
        title = _normalize_anchor_text(title_attr_match.group(1) if title_attr_match else match.group(2))
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


def _resolve_result_url(href: str, *, search_url: str) -> Optional[str]:
    normalized = unescape(str(href or "")).strip().replace("\\/", "/")
    if not normalized:
        return None

    if normalized.startswith("/"):
        normalized = urljoin(search_url, normalized)

    parsed = urlsplit(normalized)
    if parsed.scheme not in ("http", "https"):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")).rstrip("/")


def _is_allowed_domain(url: str, allowed_domains: tuple[str, ...]) -> bool:
    host = (urlsplit(url).netloc or "").lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)


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
    source: (
        lambda query, http_client, *, limit, _source=source: _search_via_public_site(
            _source, query, http_client, limit=limit
        )
    )
    for source in SUPPORTED_SEARCH_SOURCES
}
