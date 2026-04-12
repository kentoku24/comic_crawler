from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Callable, Dict, List, Optional
from urllib.parse import quote_plus, urljoin, urlsplit, urlunsplit

from manga_watch.sources import REGISTERED_SOURCES, normalize_seed_url
from manga_watch.sources.base import HttpClient, RequestsHttpClient
from manga_watch.sources.comic_action import canonical_comic_action_series_feed_url

DEFAULT_SEARCH_LIMIT = 10
SEARCH_RESULT_LIMIT = 25

_SOURCE_SEARCH_CONFIG: Dict[str, Dict[str, object]] = {
    "comic-walker": {
        "search_url": "https://comic-walker.com/search?q={query}",
        "allowed_domains": ("comic-walker.com", "www.comic-walker.com"),
    },
    "comic-action": {
        "search_url": "https://comic-action.com/search?q={query}",
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
        "search_url": "https://manga.nicovideo.jp/search?q={query}",
        "allowed_domains": ("manga.nicovideo.jp", "sp.manga.nicovideo.jp"),
    },
    "kakuyomu": {
        "search_url": "https://kakuyomu.jp/search?q={query}",
        "allowed_domains": ("kakuyomu.jp", "www.kakuyomu.jp"),
    },
    "gaugau": {
        "search_url": "https://gaugau.futabanet.jp/list/search-result?word={query}",
        "allowed_domains": ("gaugau.futabanet.jp",),
    },
}

_CONFIGURED_SOURCE_NAMES = set(_SOURCE_SEARCH_CONFIG)
_UNKNOWN_CONFIGURED_SOURCES = _CONFIGURED_SOURCE_NAMES - set(REGISTERED_SOURCES)
if _UNKNOWN_CONFIGURED_SOURCES:
    unknown_sources = ", ".join(sorted(_UNKNOWN_CONFIGURED_SOURCES))
    raise RuntimeError(f"search config contains unknown sources: {unknown_sources}")

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
    fallback_searcher = _FALLBACK_SEARCHERS.get(source)
    try:
        html_text = http_client.get_text(search_url)
    except Exception:
        if fallback_searcher is None:
            raise
        return fallback_searcher(query, http_client, limit=limit)

    results = _extract_anchor_results(
        html_text,
        source=source,
        search_url=search_url,
        allowed_domains=allowed_domains,
        limit=limit,
    )
    if results or fallback_searcher is None:
        return results
    return fallback_searcher(query, http_client, limit=limit)


def _search_comic_action(
    query: str,
    http_client: HttpClient,
    *,
    limit: int,
) -> List[SearchResult]:
    search_url = str(_SOURCE_SEARCH_CONFIG["comic-action"]["search_url"]).format(query=quote_plus(query))
    html_text = http_client.get_text(search_url)
    results: List[SearchResult] = []
    seen_seed_urls = set()

    for match in re.finditer(r'<li\b[^>]*SearchResultItem_li[^>]*>(.*?)</li>', html_text, re.I | re.S):
        block = match.group(1)
        title_match = re.search(r'<p\b[^>]*SearchResultItem_series_title[^>]*>(.*?)</p>', block, re.I | re.S)
        title = _normalize_anchor_text(title_match.group(1) if title_match else "")
        if not title:
            image_alt_match = re.search(r'alt="([^"]+)"', block, re.I | re.S)
            title = _normalize_anchor_text(image_alt_match.group(1) if image_alt_match else "")
        if not title:
            continue

        series_id_match = re.search(r"/series-thumbnail/(\d+)", block, re.I)
        candidate_url = ""
        if series_id_match:
            candidate_url = canonical_comic_action_series_feed_url("rss", series_id_match.group(1))
        else:
            latest_match = _extract_comic_action_latest_link(block)
            if latest_match:
                candidate_url = latest_match
            else:
                href_match = re.search(r'href="([^"]+/episode/\d+[^"]*)"', block, re.I | re.S)
                if href_match:
                    candidate_url = href_match.group(1)

        if not candidate_url:
            continue

        resolved_url = _resolve_result_url(candidate_url, search_url=search_url)
        if not resolved_url:
            continue

        canonical_seed_url = _canonical_seed_url_for_source("comic-action", resolved_url)
        if not canonical_seed_url or canonical_seed_url in seen_seed_urls:
            continue

        seen_seed_urls.add(canonical_seed_url)
        results.append(
            SearchResult(
                source="comic-action",
                title=title,
                seed_url=canonical_seed_url,
                subtitle="comic-action",
            )
        )
        if len(results) >= limit:
            break

    return results


def _extract_comic_action_latest_link(block: str) -> str:
    for match in re.finditer(r'(<a\b[^>]*>.*?</a>)', block, re.I | re.S):
        anchor_markup = match.group(1)
        if "SearchResultItem_sub_link" not in anchor_markup:
            continue
        href_match = re.search(r'href="([^"]+/episode/\d+[^"]*)"', anchor_markup, re.I | re.S)
        if href_match:
            return href_match.group(1)
    return ""


def _search_gaugau(
    query: str,
    http_client: HttpClient,
    *,
    limit: int,
) -> List[SearchResult]:
    config = _SOURCE_SEARCH_CONFIG["gaugau"]
    search_url = str(config["search_url"]).format(query=quote_plus(query))
    html_text = http_client.get_text(search_url)
    section = html_text
    section_start = html_text.find('<div class="works__list">')
    if section_start >= 0:
        section = html_text[section_start:]
        section_end = section.find('<div class="ranking">')
        if section_end > 0:
            section = section[:section_end]

    return _extract_gaugau_results(
        section,
        source="gaugau",
        search_url=search_url,
        allowed_domains=("gaugau.futabanet.jp",),
        limit=limit,
    )


def _search_kakuyomu(
    query: str,
    http_client: HttpClient,
    *,
    limit: int,
) -> List[SearchResult]:
    config = _SOURCE_SEARCH_CONFIG["kakuyomu"]
    search_url = str(config["search_url"]).format(query=quote_plus(query))
    html_text = http_client.get_text(search_url)
    results = _extract_work_results(
        html_text,
        source="kakuyomu",
        search_url=search_url,
        allowed_domains=("kakuyomu.jp", "www.kakuyomu.jp"),
        limit=limit,
    )
    if results:
        return _filter_results_by_query(query, results, limit=limit)
    return _extract_anchor_results(
        html_text,
        source="kakuyomu",
        search_url=search_url,
        allowed_domains=("kakuyomu.jp", "www.kakuyomu.jp"),
        limit=limit,
    )


def _search_takecomic(
    query: str,
    http_client: HttpClient,
    *,
    limit: int,
) -> List[SearchResult]:
    search_url = str(_SOURCE_SEARCH_CONFIG["takecomic"]["search_url"]).format(query=quote_plus(query))
    html_text = http_client.get_text(search_url)
    results: List[SearchResult] = []
    seen_seed_urls = set()

    for match in re.finditer(
        r'<a\b[^>]*class="[^"]*series-list-item-link[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        html_text,
        re.I | re.S,
    ):
        resolved_url = _resolve_result_url(match.group(1), search_url=search_url)
        if not resolved_url:
            continue

        canonical_seed_url = _canonical_seed_url_for_source("takecomic", resolved_url)
        if not canonical_seed_url or canonical_seed_url in seen_seed_urls:
            continue

        title_match = re.search(r'data-e2e="sliTitle"[^>]*>(.*?)</', match.group(2), re.I | re.S)
        title = _normalize_anchor_text(title_match.group(1) if title_match else "")
        if not title:
            continue

        seen_seed_urls.add(canonical_seed_url)
        results.append(
            SearchResult(
                source="takecomic",
                title=title,
                seed_url=canonical_seed_url,
                subtitle="takecomic",
            )
        )
        if len(results) >= limit:
            break

    return _filter_results_by_query(query, results, limit=limit)


def _search_champion_cross(
    query: str,
    http_client: HttpClient,
    *,
    limit: int,
) -> List[SearchResult]:
    search_url = str(_SOURCE_SEARCH_CONFIG["champion-cross"]["search_url"]).format(query=quote_plus(query))
    html_text = http_client.get_text(search_url)
    results = _extract_anchor_results(
        html_text,
        source="champion-cross",
        search_url=search_url,
        allowed_domains=("championcross.jp", "www.championcross.jp"),
        limit=SEARCH_RESULT_LIMIT,
    )
    normalized_results = [
        SearchResult(
            source=result.source,
            title=_clean_champion_cross_title(result.title, query),
            seed_url=result.seed_url,
            subtitle=result.subtitle,
        )
        for result in results
    ]
    return _filter_results_by_query(query, normalized_results, limit=limit)


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

        title = _extract_anchor_title(match.group(0), match.group(2))
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


def _extract_work_results(
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
        if not resolved_url or "/episodes/" in resolved_url:
            continue
        if not _is_allowed_domain(resolved_url, allowed_domains):
            continue

        canonical_seed_url = _canonical_seed_url_for_source(source, resolved_url)
        if not canonical_seed_url or canonical_seed_url in seen_seed_urls:
            continue

        title = _extract_anchor_title(match.group(0), match.group(2))
        if not title:
            continue

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


def _extract_gaugau_results(
    html_text: str,
    *,
    source: str,
    search_url: str,
    allowed_domains: tuple[str, ...],
    limit: int,
) -> List[SearchResult]:
    results: List[SearchResult] = []
    seen_seed_urls = set()

    for title_match in re.finditer(r'<h4>\s*<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*</h4>', html_text, re.I | re.S):
        resolved_url = _resolve_result_url(title_match.group(1), search_url=search_url)
        if not resolved_url or "/episodes/" in resolved_url:
            continue
        if not _is_allowed_domain(resolved_url, allowed_domains):
            continue

        canonical_seed_url = _canonical_seed_url_for_source(source, resolved_url)
        if not canonical_seed_url or canonical_seed_url in seen_seed_urls:
            continue

        title = _normalize_anchor_text(title_match.group(2))
        if not title:
            continue

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


def _search_from_homepage(
    source: str,
    query: str,
    http_client: HttpClient,
    *,
    limit: int,
) -> List[SearchResult]:
    homepage_url = _HOMEPAGE_URLS[source]
    extractor = _HOMEPAGE_EXTRACTORS[source]
    html_text = http_client.get_text(homepage_url)
    return extractor(query, html_text, homepage_url=homepage_url, limit=limit)


def _extract_comic_walker_homepage_results(
    query: str,
    html_text: str,
    *,
    homepage_url: str,
    limit: int,
) -> List[SearchResult]:
    results: List[SearchResult] = []
    seen_seed_urls = set()
    for match in re.finditer(
        r'<a\b[^>]*href="([^"]*?/detail/[^"]+/episodes/[^"]+)"[^>]*>(.*?)</a>',
        html_text,
        re.I | re.S,
    ):
        title_match = re.search(r'RichWorkItem_titleText[^>]*>(.*?)</', match.group(2), re.I | re.S)
        title = _normalize_anchor_text(title_match.group(1) if title_match else "")
        if not _query_matches_title(query, title):
            continue
        canonical_seed_url = _canonical_seed_url_for_source(
            "comic-walker",
            _resolve_result_url(match.group(1), search_url=homepage_url) or "",
        )
        if not canonical_seed_url or canonical_seed_url in seen_seed_urls:
            continue
        seen_seed_urls.add(canonical_seed_url)
        results.append(SearchResult("comic-walker", title, canonical_seed_url, "comic-walker"))
        if len(results) >= limit:
            break
    return results


def _extract_comic_earthstar_homepage_results(
    query: str,
    html_text: str,
    *,
    homepage_url: str,
    limit: int,
) -> List[SearchResult]:
    return _extract_title_block_results(
        query,
        html_text,
        source="comic-earthstar",
        homepage_url=homepage_url,
        limit=limit,
        block_pattern=r'<a\b[^>]*href="([^"]+/episode/[^"]+)"[^>]*>(.*?)</a>',
        title_patterns=(r'UpdatedSeriesListItem_description[^>]*>(.*?)</', r'alt="([^"]+)"'),
    )


def _extract_comicborder_homepage_results(
    query: str,
    html_text: str,
    *,
    homepage_url: str,
    limit: int,
) -> List[SearchResult]:
    return _filter_results_by_query(
        query,
        _extract_anchor_results(
            html_text,
            source="comicborder",
            search_url=homepage_url,
            allowed_domains=("comicborder.com", "www.comicborder.com"),
            limit=SEARCH_RESULT_LIMIT,
        ),
        limit=limit,
    )


def _extract_comic_trail_homepage_results(
    query: str,
    html_text: str,
    *,
    homepage_url: str,
    limit: int,
) -> List[SearchResult]:
    return _extract_title_block_results(
        query,
        html_text,
        source="comic-trail",
        homepage_url=homepage_url,
        limit=limit,
        block_pattern=r'<a\b[^>]*href="([^"]+/episode/[^"]+)"[^>]*>(.*?)</a>',
        title_patterns=(r'alt="([^"|]+)(?:\||｜)[^"]*"', r'<h4[^>]*>(.*?)</h4>'),
    )


def _extract_kuragebunch_homepage_results(
    query: str,
    html_text: str,
    *,
    homepage_url: str,
    limit: int,
) -> List[SearchResult]:
    return _extract_title_block_results(
        query,
        html_text,
        source="kuragebunch",
        homepage_url=homepage_url,
        limit=limit,
        block_pattern=r'<a\b[^>]*href="([^"]+/episode/[^"]+)"[^>]*>(.*?)</a>',
        title_patterns=(r'<h4[^>]*>(.*?)</h4>', r'alt="([^"]+)"'),
    )


def _extract_shonenjumpplus_homepage_results(
    query: str,
    html_text: str,
    *,
    homepage_url: str,
    limit: int,
) -> List[SearchResult]:
    return _extract_title_block_results(
        query,
        html_text,
        source="shonenjumpplus",
        homepage_url=homepage_url,
        limit=limit,
        block_pattern=r'<a\b[^>]*href="([^"]+/episode/[^"]+)"[^>]*>(.*?)</a>',
        title_patterns=(r'daily-series-title[^>]*>(.*?)</h2>', r'gtm-daily-series-thumb-horizontal-([^"\s]+)'),
    )


def _extract_sunday_webry_homepage_results(
    query: str,
    html_text: str,
    *,
    homepage_url: str,
    limit: int,
) -> List[SearchResult]:
    return _extract_title_block_results(
        query,
        html_text,
        source="sunday-webry",
        homepage_url=homepage_url,
        limit=limit,
        block_pattern=r'<a\b[^>]*href="([^"]+/episode/[^"]+)"[^>]*>(.*?)</a>',
        title_patterns=(r'<h4[^>]*>(.*?)</h4>', r'alt="([^"]+)"'),
    )


def _extract_magapoke_homepage_results(
    query: str,
    html_text: str,
    *,
    homepage_url: str,
    limit: int,
) -> List[SearchResult]:
    return _extract_title_block_results(
        query,
        html_text,
        source="magapoke",
        homepage_url=homepage_url,
        limit=limit,
        block_pattern=r'<a\b[^>]*href="([^"]*?/title/[^"]+/episode/[^"]+)"[^>]*>(.*?)</a>',
        title_patterns=(r'c-ranking-item__ttl[^>]*>(.*?)</h3>', r'alt="([^"]+)"'),
    )


def _extract_title_block_results(
    query: str,
    html_text: str,
    *,
    source: str,
    homepage_url: str,
    limit: int,
    block_pattern: str,
    title_patterns: tuple[str, ...],
) -> List[SearchResult]:
    results: List[SearchResult] = []
    seen_seed_urls = set()
    for match in re.finditer(block_pattern, html_text, re.I | re.S):
        title = ""
        for title_pattern in title_patterns:
            title_match = re.search(title_pattern, match.group(2), re.I | re.S)
            title = _normalize_anchor_text(title_match.group(1) if title_match else "")
            if title:
                title = re.split(r"[|｜]", title, maxsplit=1)[0].strip()
                break
        if not _query_matches_title(query, title):
            continue
        resolved_url = _resolve_result_url(match.group(1), search_url=homepage_url)
        if not resolved_url:
            continue
        canonical_seed_url = _canonical_seed_url_for_source(source, resolved_url)
        if not canonical_seed_url or canonical_seed_url in seen_seed_urls:
            continue
        seen_seed_urls.add(canonical_seed_url)
        results.append(SearchResult(source, title, canonical_seed_url, source))
        if len(results) >= limit:
            break
    return results


def _extract_anchor_title(anchor_markup: str, anchor_html: str) -> str:
    title_attr_match = re.search(r'title\s*=\s*(["\'])(.*?)\1', anchor_markup, re.I | re.S)
    if title_attr_match:
        title = _normalize_anchor_text(title_attr_match.group(2))
        if title:
            return title

    title = _normalize_anchor_text(anchor_html)
    if title:
        return title

    image_alt_match = re.search(r'<img\b[^>]*alt\s*=\s*(["\'])(.*?)\1', anchor_html, re.I | re.S)
    if not image_alt_match:
        return ""

    alt_title = _normalize_anchor_text(image_alt_match.group(2))
    if not alt_title:
        return ""
    stripped_alt_title = re.sub(r"【.*$", "", alt_title).strip()
    return stripped_alt_title or alt_title


def _resolve_result_url(href: str, *, search_url: str) -> Optional[str]:
    normalized = unescape(str(href or "")).strip().replace("\\/", "/")
    if not normalized:
        return None

    parsed = urlsplit(normalized)
    if not parsed.scheme:
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


def _clean_champion_cross_title(title: str, query: str) -> str:
    normalized = _normalize_anchor_text(title)
    normalized = re.sub(r"【.*?】", "", normalized).strip()
    normalized = re.sub(r"\s+[^\s]+(?:/[^\s]+)?$", "", normalized).strip()
    return normalized or _normalize_anchor_text(title)


def _query_matches_title(query: str, title: str) -> bool:
    normalized_query = re.sub(r"\s+", "", query or "")
    normalized_title = re.sub(r"\s+", "", title or "")
    if not normalized_query or not normalized_title:
        return False
    return normalized_query == normalized_title or normalized_query in normalized_title or normalized_title in normalized_query


def _filter_results_by_query(query: str, results: List[SearchResult], *, limit: int) -> List[SearchResult]:
    filtered = [result for result in results if _query_matches_title(query, result.title)]
    return filtered[:limit]


_HOMEPAGE_URLS: Dict[str, str] = {
    "comic-walker": "https://comic-walker.com/",
    "comic-earthstar": "https://comic-earthstar.com/",
    "comicborder": "https://comicborder.com/",
    "comic-trail": "https://comic-trail.com/",
    "kuragebunch": "https://kuragebunch.com/",
    "shonenjumpplus": "https://shonenjumpplus.com/",
    "sunday-webry": "https://www.sunday-webry.com/",
    "magapoke": "https://pocket.shonenmagazine.com/",
}

_HOMEPAGE_EXTRACTORS: Dict[str, Callable[..., List[SearchResult]]] = {
    "comic-walker": _extract_comic_walker_homepage_results,
    "comic-earthstar": _extract_comic_earthstar_homepage_results,
    "comicborder": _extract_comicborder_homepage_results,
    "comic-trail": _extract_comic_trail_homepage_results,
    "kuragebunch": _extract_kuragebunch_homepage_results,
    "shonenjumpplus": _extract_shonenjumpplus_homepage_results,
    "sunday-webry": _extract_sunday_webry_homepage_results,
    "magapoke": _extract_magapoke_homepage_results,
}

_FALLBACK_SEARCHERS: Dict[str, Callable[..., List[SearchResult]]] = {
    source: (
        lambda query, http_client, *, limit, _source=source: _search_from_homepage(
            _source, query, http_client, limit=limit
        )
    )
    for source in _HOMEPAGE_EXTRACTORS
}


_SEARCHERS: Dict[str, Callable[..., List[SearchResult]]] = {
    source: (
        lambda query, http_client, *, limit, _source=source: _search_via_public_site(
            _source, query, http_client, limit=limit
        )
    )
    for source in SUPPORTED_SEARCH_SOURCES
}
_SEARCHERS["comic-action"] = _search_comic_action
_SEARCHERS["champion-cross"] = _search_champion_cross
_SEARCHERS["gaugau"] = _search_gaugau
_SEARCHERS["kakuyomu"] = _search_kakuyomu
_SEARCHERS["takecomic"] = _search_takecomic
