from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser
from typing import Dict, Optional
from urllib.parse import urljoin

from manga_watch.sources.base import HttpClient, RequestsHttpClient

AVAILABILITY_SOURCE_LABELS = {
    "comic-walker": "ComicWalker",
    "comic-action": "webアクション",
    "comic-earthstar": "コミック アース・スター",
    "comicborder": "コミックボーダー",
    "comic-trail": "コミックトレイル",
    "kuragebunch": "くらげバンチ",
    "shonenjumpplus": "少年ジャンプ＋",
    "sunday-webry": "サンデーうぇぶり",
    "champion-cross": "Champion Cross",
    "magapoke": "マガポケ",
    "firecross": "ファイアCROSS",
    "takecomic": "タケコミ",
    "nicovideo-manga": "ニコニコ漫画",
    "gaugau": "がうがうモンスター",
    "piccoma": "ピッコマ",
    "bookwalker": "BOOK☆WALKER",
}
AVAILABILITY_STATUS_LABELS = {
    "free_now": "今すぐ無料",
    "needs_check": "要確認",
    "not_found": "見つからない",
    "unsupported": "未対応",
}
SUPPORTED_AVAILABILITY_SOURCES = tuple(AVAILABILITY_SOURCE_LABELS)
EPISODE_RESOLVABLE_SOURCES = frozenset({"comic-walker", "nicovideo-manga"})
AVAILABILITY_SOURCE_CAPABILITIES = {
    source: {
        "searchable": True,
        "episode_resolvable": source in EPISODE_RESOLVABLE_SOURCES,
        "free_status_resolvable": source in EPISODE_RESOLVABLE_SOURCES,
        "needs_check_reason": None
        if source in EPISODE_RESOLVABLE_SOURCES
        else "availability resolver is not implemented for this source",
    }
    for source in SUPPORTED_AVAILABILITY_SOURCES
}


def supported_availability_sources() -> tuple[str, ...]:
    return SUPPORTED_AVAILABILITY_SOURCES


def availability_capability(source: str) -> Dict[str, object]:
    normalized_source = str(source or "").strip()
    capability = AVAILABILITY_SOURCE_CAPABILITIES.get(normalized_source)
    if capability is None:
        return {
            "searchable": False,
            "episode_resolvable": False,
            "free_status_resolvable": False,
            "needs_check_reason": "unsupported availability source",
        }
    return dict(capability)


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
    if normalized_source not in EPISODE_RESOLVABLE_SOURCES:
        return _result(normalized_source, "needs_check", seed_url)

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


class _EpisodeAnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._current_href: Optional[str] = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a" or self._current_href is not None:
            return
        href = dict(attrs).get("href")
        if not href:
            return
        self._current_href = href
        self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._current_href is None:
            return
        self.links.append((self._current_href, "".join(self._current_text)))
        self._current_href = None
        self._current_text = []


def _matching_url(value: str, url_pattern: str) -> Optional[str]:
    match = re.search(url_pattern, value, re.I)
    if match is None:
        return None
    if match.group(0) != value.strip():
        return None
    return match.group(0)


def _anchor_episode_url(
    html_text: str,
    episode: str,
    *,
    base_url: str,
    url_pattern: str,
) -> Optional[str]:
    parser = _EpisodeAnchorParser()
    parser.feed(html_text)
    for href, label in parser.links:
        candidate_url = _matching_url(href.strip(), url_pattern)
        if candidate_url is None:
            continue
        if not _contains_episode_label(label, episode):
            continue
        return urljoin(base_url, candidate_url)
    return None


def _bounded_candidate_context(text: str, start: int, end: int) -> str:
    left_boundaries = (text.rfind("{", 0, start), text.rfind("[", 0, start), text.rfind("\n", 0, start))
    right_candidates = [pos for pos in (text.find("}", end), text.find("]", end), text.find("\n", end)) if pos != -1]
    left = max(left_boundaries)
    right = min(right_candidates) if right_candidates else min(len(text), end + 200)
    return text[max(0, left): min(len(text), right + 1)]


def _find_episode_url(
    html_text: str,
    episode: str,
    *,
    base_url: str,
    url_pattern: str,
) -> Optional[str]:
    normalized = _normalize_html_text(html_text)
    anchor_url = _anchor_episode_url(
        normalized,
        episode,
        base_url=base_url,
        url_pattern=url_pattern,
    )
    if anchor_url:
        return anchor_url

    for match in re.finditer(url_pattern, normalized, re.I):
        context = _bounded_candidate_context(normalized, match.start(), match.end())
        if not _contains_episode_label(context, episode):
            continue
        return urljoin(base_url, match.group(0))
    return None
