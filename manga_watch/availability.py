from __future__ import annotations

import html
import re
import unicodedata
from typing import Dict, Optional
from urllib.parse import urljoin

from manga_watch.sources.base import HttpClient, RequestsHttpClient

AVAILABILITY_SOURCE_LABELS = {
    "comic-walker": "ComicWalker",
    "nicovideo-manga": "ニコニコ漫画",
}
AVAILABILITY_STATUS_LABELS = {
    "free_now": "今すぐ無料",
    "needs_check": "要確認",
    "not_found": "見つからない",
    "unsupported": "未対応",
}
SUPPORTED_AVAILABILITY_SOURCES = tuple(AVAILABILITY_SOURCE_LABELS)


def supported_availability_sources() -> tuple[str, ...]:
    return SUPPORTED_AVAILABILITY_SOURCES


def resolve_episode_availability(
    source: str,
    seed_url: str,
    episode: str,
    *,
    http_client: Optional[HttpClient] = None,
) -> Dict[str, object]:
    normalized_source = str(source or "").strip()
    if normalized_source not in SUPPORTED_AVAILABILITY_SOURCES:
        return _result(normalized_source, "unsupported", None)

    client = http_client or RequestsHttpClient()
    html_text = client.get_text(seed_url)
    if normalized_source == "comic-walker":
        url = _find_episode_url(
            html_text,
            episode,
            base_url=seed_url,
            url_pattern=r"(?:https?://(?:www\.)?comic-walker\.com)?/detail/[^\"'<>\s]+/episodes/[^\"'<>\s?]+(?:\?episodeType=[^\"'<>\s]+)?",
        )
        return _result(normalized_source, "free_now" if url else "not_found", url)

    if normalized_source == "nicovideo-manga":
        url = _find_episode_url(
            html_text,
            episode,
            base_url=seed_url,
            url_pattern=r"(?:https?://(?:sp\.)?manga\.nicovideo\.jp)?/watch/mg\d+",
        )
        return _result(normalized_source, "free_now" if url else "not_found", url)

    return _result(normalized_source, "unsupported", None)


def status_label(status: object) -> str:
    return AVAILABILITY_STATUS_LABELS.get(str(status or ""), "要確認")


def source_label(source: object) -> str:
    return AVAILABILITY_SOURCE_LABELS.get(str(source or ""), str(source or "unknown"))


def _result(source: str, status: str, url: Optional[str]) -> Dict[str, object]:
    return {"source": source, "status": status, "url": url}


def _episode_number(value: object) -> Optional[str]:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    match = re.search(r"(?:第\s*)?(\d+)\s*話?", normalized)
    if match:
        return str(int(match.group(1)))
    return None


def _contains_episode_label(text: str, episode: str) -> bool:
    target_number = _episode_number(episode)
    if target_number is None:
        return False
    normalized = unicodedata.normalize("NFKC", html.unescape(text or ""))
    patterns = (
        rf"第\s*0*{re.escape(target_number)}\s*話",
        rf"(?<!\d)0*{re.escape(target_number)}\s*話",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


def _normalize_html_text(html_text: str) -> str:
    return (
        html.unescape(str(html_text or ""))
        .replace("\\/", "/")
        .replace("\\u002F", "/")
        .replace("\\u003C", "<")
        .replace("\\u003E", ">")
    )


def _find_episode_url(
    html_text: str,
    episode: str,
    *,
    base_url: str,
    url_pattern: str,
) -> Optional[str]:
    normalized = _normalize_html_text(html_text)
    for match in re.finditer(url_pattern, normalized, re.I):
        start = max(0, match.start() - 500)
        end = min(len(normalized), match.end() + 500)
        context = normalized[start:end]
        if not _contains_episode_label(context, episode):
            continue
        return urljoin(base_url, match.group(0))
    return None
