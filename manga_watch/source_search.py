from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from typing import Callable, Dict, List, Optional
from urllib.parse import quote, quote_plus, urljoin, urlsplit, urlunsplit

from manga_watch.sources import REGISTERED_SOURCES, normalize_seed_url
from manga_watch.sources.base import HttpClient, RequestsHttpClient
from manga_watch.sources.comic_action import canonical_comic_action_series_feed_url
from manga_watch.sources.comic_earthstar import ComicEarthstarAdapter
from manga_watch.sources.firecross import canonical_firecross_ebook_series_url
from manga_watch.sources.piccoma import canonical_piccoma_product_url

DEFAULT_SEARCH_LIMIT = 10
SEARCH_RESULT_LIMIT = 25

_SOURCE_SEARCH_CONFIG: Dict[str, Dict[str, object]] = {
    "comic-walker": {
        "search_url": "https://comic-walker.com/search?keyword={query}",
        "allowed_domains": ("comic-walker.com", "www.comic-walker.com"),
    },
    "comic-action": {
        "search_url": "https://comic-action.com/search?q={query}",
        "allowed_domains": ("comic-action.com", "www.comic-action.com"),
    },
    "comic-earthstar": {
        "search_url": "https://comic-earthstar.com/search?q={query}",
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
    "comic-days": {
        "search_url": "https://comic-days.com/search?q={query}",
        "allowed_domains": ("comic-days.com", "www.comic-days.com"),
    },
    "kuragebunch": {
        "search_url": "https://kuragebunch.com/search?q={query}",
        "allowed_domains": ("kuragebunch.com", "www.kuragebunch.com"),
    },
    "shonenjumpplus": {
        "search_url": "https://shonenjumpplus.com/search?query={query}",
        "allowed_domains": ("shonenjumpplus.com", "www.shonenjumpplus.com"),
    },
    "sunday-webry": {
        "search_url": "https://www.sunday-webry.com/search?q={query}",
        "allowed_domains": ("sunday-webry.com", "www.sunday-webry.com"),
    },
    "champion-cross": {
        "search_url": "https://championcross.jp/search?keyword={query}",
        "allowed_domains": ("championcross.jp", "www.championcross.jp"),
    },
    "magapoke": {
        "search_url": "https://pocket.shonenmagazine.com/search/{query}",
        "allowed_domains": ("pocket.shonenmagazine.com",),
    },
    "firecross": {
        "search_url": "https://firecross.jp/search?q={query}&t=1",
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
    "piccoma": {
        "search_url": "https://piccoma.com/web/search/result_ajax/list?tab_type=T&word={query}&page=1",
        "allowed_domains": ("piccoma.com", "www.piccoma.com"),
    },
    "bookwalker": {
        "search_url": "https://bookwalker.jp/search/?word={query}&order=score",
        "allowed_domains": ("bookwalker.jp", "www.bookwalker.jp"),
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

    search_url = str(config["search_url"]).format(query=_encode_search_query(source, query))
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


def _search_comic_earthstar(
    query: str,
    http_client: HttpClient,
    *,
    limit: int,
) -> List[SearchResult]:
    search_url = str(_SOURCE_SEARCH_CONFIG["comic-earthstar"]["search_url"]).format(query=quote_plus(query))
    html_text = http_client.get_text(search_url)
    results: List[SearchResult] = []
    seen_seed_urls = set()
    adapter = ComicEarthstarAdapter()

    for match in re.finditer(r'<li\b[^>]*SearchResultItem_li[^>]*>(.*?)</li>', html_text, re.I | re.S):
        block = match.group(1)
        title_match = re.search(r'<p\b[^>]*SearchResultItem_series_title[^>]*>(.*?)</p>', block, re.I | re.S)
        title = _normalize_anchor_text(title_match.group(1) if title_match else "")
        if not title:
            image_alt_match = re.search(r'<img\b[^>]*alt\s*=\s*(["\'])(.*?)\1', block, re.I | re.S)
            title = _normalize_anchor_text(image_alt_match.group(2) if image_alt_match else "")
        if not title:
            continue

        candidate_url = ""
        for anchor_match in re.finditer(r'(<a\b[^>]*>.*?</a>)', block, re.I | re.S):
            anchor_markup = anchor_match.group(1)
            if "SearchResultItem_main_link" not in anchor_markup:
                continue
            href_match = re.search(r'href="([^"]+)"', anchor_markup, re.I | re.S)
            if href_match:
                candidate_url = href_match.group(1)
                break
        if not candidate_url:
            href_match = re.search(r'href="([^"]+/episode/\d+[^"]*)"', block, re.I | re.S)
            if href_match:
                candidate_url = href_match.group(1)
        if not candidate_url:
            continue

        resolved_url = _resolve_result_url(candidate_url, search_url=search_url)
        if not resolved_url or not _is_allowed_domain(resolved_url, ("comic-earthstar.com", "www.comic-earthstar.com")):
            continue

        try:
            canonical_seed_url = adapter.canonicalize_item({"seedUrl": resolved_url}, http_client).seed_url
        except Exception:
            canonical_seed_url = None
        if not canonical_seed_url or canonical_seed_url in seen_seed_urls:
            continue

        seen_seed_urls.add(canonical_seed_url)
        results.append(
            SearchResult(
                source="comic-earthstar",
                title=title,
                seed_url=canonical_seed_url,
                subtitle="comic-earthstar",
            )
        )
        if len(results) >= limit:
            break

    return results


def _search_kuragebunch(
    query: str,
    http_client: HttpClient,
    *,
    limit: int,
) -> List[SearchResult]:
    search_url = str(_SOURCE_SEARCH_CONFIG["kuragebunch"]["search_url"]).format(query=quote_plus(query))
    html_text = http_client.get_text(search_url)
    results: List[SearchResult] = []
    seen_seed_urls = set()

    for match in re.finditer(r'<li\b[^>]*test-result-readable-product[^>]*>(.*?)</li>', html_text, re.I | re.S):
        block = match.group(1)
        title = _extract_kuragebunch_title(block)
        if not title:
            continue

        candidate_url = _extract_kuragebunch_result_url(block)
        if not candidate_url:
            continue

        resolved_url = _resolve_result_url(candidate_url, search_url=search_url)
        if not resolved_url:
            continue

        canonical_seed_url = _canonical_seed_url_for_source("kuragebunch", resolved_url)
        if not canonical_seed_url or canonical_seed_url in seen_seed_urls:
            continue

        seen_seed_urls.add(canonical_seed_url)
        results.append(
            SearchResult(
                source="kuragebunch",
                title=title,
                seed_url=canonical_seed_url,
                subtitle="kuragebunch",
            )
        )
        if len(results) >= limit:
            break

    return results


def _search_sunday_webry(
    query: str,
    http_client: HttpClient,
    *,
    limit: int,
) -> List[SearchResult]:
    search_url = str(_SOURCE_SEARCH_CONFIG["sunday-webry"]["search_url"]).format(query=quote_plus(query))
    html_text = http_client.get_text(search_url)
    results: List[SearchResult] = []
    seen_seed_urls = set()

    for match in re.finditer(r'<li\b[^>]*>(.*?)</li>', html_text, re.I | re.S):
        block = match.group(0)
        data_title_match = re.search(r'data-title="([^"]*)"', block, re.I | re.S)
        title = _normalize_anchor_text(data_title_match.group(1) if data_title_match else "")
        if not title:
            title_match = re.search(r'<p\b[^>]*class="[^"]*\bseries-title\b[^"]*"[^>]*>(.*?)</p>', block, re.I | re.S)
            title = _normalize_anchor_text(title_match.group(1) if title_match else "")
        if not title:
            continue

        candidate_url = ""
        for pattern in (
            r'<a\b[^>]*class="[^"]*\bmain-link\b[^"]*"[^>]*href="([^"]+)"',
            r'<a\b[^>]*href="([^"]+)"[^>]*class="[^"]*\bmain-link\b[^"]*"',
            r'<div\b[^>]*class="[^"]*\bthmb-container\b[^"]*"[^>]*>.*?<a\b[^>]*href="([^"]+)"',
        ):
            pattern_match = re.search(pattern, block, re.I | re.S)
            if pattern_match:
                candidate_url = pattern_match.group(1)
                break

        if not candidate_url:
            continue

        resolved_url = _resolve_result_url(candidate_url, search_url=search_url)
        if not resolved_url:
            continue

        canonical_seed_url = _canonical_seed_url_for_source("sunday-webry", resolved_url)
        if not canonical_seed_url or canonical_seed_url in seen_seed_urls:
            continue

        seen_seed_urls.add(canonical_seed_url)
        results.append(
            SearchResult(
                source="sunday-webry",
                title=title,
                seed_url=canonical_seed_url,
                subtitle="sunday-webry",
            )
        )
        if len(results) >= limit:
            break

    return results


def _encode_search_query(source: str, query: str) -> str:
    if source == "magapoke":
        return quote(query, safe="")
    return quote_plus(query)

def _extract_comic_action_latest_link(block: str) -> str:
    for match in re.finditer(r'(<a\b[^>]*>.*?</a>)', block, re.I | re.S):
        anchor_markup = match.group(1)
        if "SearchResultItem_sub_link" not in anchor_markup:
            continue
        href_match = re.search(r'href="([^"]+/episode/\d+[^"]*)"', anchor_markup, re.I | re.S)
        if href_match:
            return href_match.group(1)
    return ""


def _extract_kuragebunch_title(block: str) -> str:
    for pattern in (
        r'<p\b[^>]*test-title[^>]*>(.*?)</p>',
        r'data-title="([^"]+)"',
        r'<img\b[^>]*alt="([^"]+)"',
    ):
        match = re.search(pattern, block, re.I | re.S)
        if match:
            title = _normalize_anchor_text(match.group(1))
            if title:
                return title
    return ""


def _extract_kuragebunch_result_url(block: str) -> str:
    for marker in ("test-first-url", "test-thumbnail-permalink"):
        match = re.search(rf'<a\b(?=[^>]*{marker})[^>]*href="([^"]+)"', block, re.I | re.S)
        if match:
            return match.group(1)

    match = re.search(r'<a\b[^>]*class="[^"]*\bmain-link\b[^"]*"[^>]*href="([^"]+)"', block, re.I | re.S)
    if match:
        return match.group(1)

    match = re.search(r'<a\b[^>]*href="([^"]+)"[^>]*class="[^"]*\bmain-link\b[^"]*"', block, re.I | re.S)
    if match:
        return match.group(1)

    return ""


def _search_champion_cross(
    query: str,
    http_client: HttpClient,
    *,
    limit: int,
) -> List[SearchResult]:
    search_url = str(_SOURCE_SEARCH_CONFIG["champion-cross"]["search_url"]).format(query=quote_plus(query))
    html_text = http_client.get_text(search_url)
    results: List[SearchResult] = []
    seen_seed_urls = set()

    for match in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html_text, re.I | re.S):
        anchor_markup = match.group(0)
        if "c-ms-mode-series" not in anchor_markup:
            continue

        resolved_url = _resolve_result_url(match.group(1), search_url=search_url)
        if not resolved_url:
            continue

        canonical_seed_url = _canonical_seed_url_for_source("champion-cross", resolved_url)
        if not canonical_seed_url or canonical_seed_url in seen_seed_urls:
            continue

        title = _champion_cross_title(anchor_markup, match.group(2))
        if not title:
            continue

        seen_seed_urls.add(canonical_seed_url)
        results.append(
            SearchResult(
                source="champion-cross",
                title=title,
                seed_url=canonical_seed_url,
                subtitle="champion-cross",
            )
        )
        if len(results) >= limit:
            break

    if results:
        return results

    return _extract_anchor_results(
        html_text,
        source="champion-cross",
        search_url=search_url,
        allowed_domains=("championcross.jp", "www.championcross.jp"),
        limit=limit,
    )


def _champion_cross_title(anchor_markup: str, anchor_html: str) -> str:
    title_match = re.search(r'<h2\b[^>]*class="[^"]*\bmanga-title\b[^"]*"[^>]*>(.*?)</h2>', anchor_html, re.I | re.S)
    if title_match:
        title = _normalize_anchor_text(title_match.group(1))
        if title:
            return title

    image_alt_match = re.search(r'<img\b[^>]*alt\s*=\s*(["\'])(.*?)\1', anchor_html, re.I | re.S)
    if image_alt_match:
        title = _normalize_anchor_text(image_alt_match.group(2))
        if title:
            return title

    return _extract_anchor_title(anchor_markup, anchor_html)


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


def _search_piccoma(
    query: str,
    http_client: HttpClient,
    *,
    limit: int,
) -> List[SearchResult]:
    config = _SOURCE_SEARCH_CONFIG["piccoma"]
    search_url = str(config["search_url"]).format(query=quote_plus(query))
    try:
        payload = json.loads(http_client.get_text(search_url))
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict) or payload.get("status") != 0:
        return []

    products = payload.get("products")
    if not isinstance(products, list):
        return []

    results: List[SearchResult] = []
    seen_seed_urls = set()
    for product in products:
        if not isinstance(product, dict):
            continue

        product_id = str(product.get("id") or "").strip()
        title = str(product.get("title") or "").strip()
        if not product_id.isdigit() or not title:
            continue

        seed_url = canonical_piccoma_product_url(product_id)
        if seed_url in seen_seed_urls:
            continue

        seen_seed_urls.add(seed_url)
        results.append(
            SearchResult(
                source="piccoma",
                title=title,
                seed_url=seed_url,
                subtitle="piccoma",
            )
        )
        if len(results) >= limit:
            break

    return results


def _search_bookwalker(
    query: str,
    http_client: HttpClient,
    *,
    limit: int,
) -> List[SearchResult]:
    config = _SOURCE_SEARCH_CONFIG["bookwalker"]
    search_url = str(config["search_url"]).format(query=quote_plus(query))
    html_text = http_client.get_text(search_url)
    results: List[SearchResult] = []
    seen_seed_urls = set()

    for block in re.findall(
        r'<(?:li|div)\b[^>]*class="[^"]*\bm-(?:tile|book-item)\b[^"]*"[^>]*>.*?(?=<(?:li|div)\b[^>]*class="[^"]*\bm-(?:tile|book-item)\b|</ul>|</section>|$)',
        html_text,
        re.I | re.S,
    ):
        candidate = _extract_bookwalker_search_candidate(block, search_url=search_url)
        if not candidate:
            continue
        title, seed_url = candidate
        if seed_url in seen_seed_urls:
            continue

        seen_seed_urls.add(seed_url)
        results.append(SearchResult("bookwalker", title, seed_url, "bookwalker"))
        if len(results) >= limit:
            break

    return results


def _extract_bookwalker_search_candidate(block: str, *, search_url: str) -> Optional[tuple[str, str]]:
    title_link_match = re.search(
        r'<a\b(?=[^>]*class="[^"]*\bm-book-item__title\b)[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        block,
        re.I | re.S,
    )
    thumb_link_match = re.search(
        r'<a\b(?=[^>]*class="[^"]*\bm-thumb__image\b)[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        block,
        re.I | re.S,
    )
    link_match = title_link_match or thumb_link_match
    if not link_match:
        return None

    resolved_url = _resolve_result_url(link_match.group(1), search_url=search_url)
    if not resolved_url or not _is_allowed_domain(resolved_url, ("bookwalker.jp", "www.bookwalker.jp")):
        return None

    canonical_seed_url = _canonical_seed_url_for_source("bookwalker", resolved_url)
    if not canonical_seed_url:
        return None

    title = _extract_anchor_title(link_match.group(0), link_match.group(2))
    if not title:
        image_match = re.search(r"<img\b[^>]*>", block, re.I | re.S)
        title = _extract_anchor_title("", image_match.group(0)) if image_match else ""
    return (title or canonical_seed_url, canonical_seed_url)


def _search_firecross(
    query: str,
    http_client: HttpClient,
    *,
    limit: int,
) -> List[SearchResult]:
    config = _SOURCE_SEARCH_CONFIG["firecross"]
    search_url = str(config["search_url"]).format(query=quote_plus(query))
    html_text = http_client.get_text(search_url)
    results: List[SearchResult] = []
    seen_seed_urls = set()

    for match in re.finditer(r'<li\b[^>]*class="[^"]*\bseriesList_item\b[^"]*"[^>]*>(.*?)</li>', html_text, re.I | re.S):
        block = match.group(1)
        title = _extract_firecross_search_title(block)
        if not title:
            continue

        candidate_url = _extract_firecross_search_seed_url(block, search_url=search_url)
        if not candidate_url:
            continue

        canonical_seed_url = _canonical_seed_url_for_source("firecross", candidate_url)
        if not canonical_seed_url or canonical_seed_url in seen_seed_urls:
            continue

        seen_seed_urls.add(canonical_seed_url)
        results.append(
            SearchResult(
                source="firecross",
                title=title,
                seed_url=canonical_seed_url,
                subtitle="firecross",
            )
        )
        if len(results) >= limit:
            break

    return results


def _extract_firecross_search_title(block: str) -> str:
    title_match = re.search(r'<a\b[^>]*class="[^"]*\bseriesList_itemTitle\b[^"]*"[^>]*>(.*?)</a>', block, re.I | re.S)
    if title_match:
        title = _normalize_anchor_text(title_match.group(1))
        if title:
            return title

    image_alt_match = re.search(r'<img\b[^>]*alt\s*=\s*(["\'])(.*?)\1', block, re.I | re.S)
    if image_alt_match:
        title = _normalize_anchor_text(image_alt_match.group(2))
        if title:
            return title

    return ""


def _extract_firecross_search_seed_url(block: str, *, search_url: str) -> Optional[str]:
    web_read_match = re.search(
        r'<a\b[^>]*href="([^"]+)"[^>]*>\s*WEB読み\s*</a>',
        block,
        re.I | re.S,
    )
    if web_read_match:
        resolved_url = _resolve_result_url(web_read_match.group(1), search_url=search_url)
        if resolved_url:
            return resolved_url

    series_page_match = re.search(
        r'<a\b[^>]*class="[^"]*\bseriesList_itemTitle\b[^"]*"[^>]*href="([^"]+)"',
        block,
        re.I | re.S,
    )
    if series_page_match:
        resolved_url = _resolve_result_url(series_page_match.group(1), search_url=search_url)
        if not resolved_url:
            return None
        parsed = urlsplit(resolved_url)
        match = re.match(r"^/(?:comic|hjbunko|hjnovels)/series/([0-9A-Za-z_-]+)$", parsed.path)
        if not match:
            return None
        return canonical_firecross_ebook_series_url(match.group(1))

    return None


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
        if source == "takecomic":
            title = _normalize_takecomic_search_title(title)
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
        block_pattern=r'<a\b[^>]*href="([^"]*?/episode/[^"]+)"[^>]*>(.*?)</a>',
        title_patterns=(r'alt="([^"|]+)(?:\||｜)[^"]*"', r'<h4[^>]*>(.*?)</h4>'),
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
        block_pattern=r'<a\b[^>]*href="([^"]*?/episode/[^"]+)"[^>]*>(.*?)</a>',
        title_patterns=(r'daily-series-title[^>]*>(.*?)</h2>', r'gtm-daily-series-thumb-horizontal-([^"\s]+)'),
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
    normalized = re.sub(r"^(?:最新UP!?|NEW!)\s*", "", normalized)
    return normalized


def _normalize_takecomic_search_title(title: str) -> str:
    return re.sub(r"^更新\s*", "", title or "").strip()


def _query_matches_title(query: str, title: str) -> bool:
    normalized_query = re.sub(r"\s+", "", query or "").casefold()
    normalized_title = re.sub(r"\s+", "", title or "").casefold()
    if not normalized_query or not normalized_title:
        return False
    return normalized_query == normalized_title or normalized_query in normalized_title or normalized_title in normalized_query


def _filter_results_by_query(query: str, results: List[SearchResult], *, limit: int) -> List[SearchResult]:
    filtered = [result for result in results if _query_matches_title(query, result.title)]
    return filtered[:limit]


_HOMEPAGE_URLS: Dict[str, str] = {
    "comicborder": "https://comicborder.com/",
    "comic-trail": "https://comic-trail.com/",
    "shonenjumpplus": "https://shonenjumpplus.com/",
}

_HOMEPAGE_EXTRACTORS: Dict[str, Callable[..., List[SearchResult]]] = {
    "comicborder": _extract_comicborder_homepage_results,
    "comic-trail": _extract_comic_trail_homepage_results,
    "shonenjumpplus": _extract_shonenjumpplus_homepage_results,
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
_SEARCHERS["comic-earthstar"] = _search_comic_earthstar
_SEARCHERS["kuragebunch"] = _search_kuragebunch
_SEARCHERS["firecross"] = _search_firecross
_SEARCHERS["champion-cross"] = _search_champion_cross
_SEARCHERS["sunday-webry"] = _search_sunday_webry
_SEARCHERS["gaugau"] = _search_gaugau
_SEARCHERS["piccoma"] = _search_piccoma
_SEARCHERS["bookwalker"] = _search_bookwalker
