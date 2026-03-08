from __future__ import annotations

import re
import unicodedata
from typing import Mapping

ELLIPSIS = "…"
SUBTITLE_LIMIT = 8
FALLBACK_LABEL_LIMIT = 20

_HEADER_WITH_SUBTITLE_RE = re.compile(
    r"^(?P<header>(?:"
    r"第[0-9０-９一二三四五六七八九十百千万〇零]+話(?:その[0-9０-９一二三四五六七八九十百千万〇零]+|[前中後]編|[①②③④⑤⑥⑦⑧⑨⑩])?"
    r"|Episode\s*\d+"
    r"|Ep\.\s*\d+"
    r"|#\d+"
    r"))(?P<separator>[ \t　:：/\-‐‑‒–—―|｜]+)(?P<subtitle>.+)$"
)


def _is_variation_selector(char: str) -> bool:
    codepoint = ord(char)
    return 0xFE00 <= codepoint <= 0xFE0F or 0xE0100 <= codepoint <= 0xE01EF


def _is_emoji_modifier(char: str) -> bool:
    codepoint = ord(char)
    return 0x1F3FB <= codepoint <= 0x1F3FF


def _is_grapheme_extend(char: str) -> bool:
    return (
        unicodedata.combining(char) != 0
        or _is_variation_selector(char)
        or _is_emoji_modifier(char)
    )


def split_graphemes(text: str) -> list[str]:
    clusters: list[str] = []
    current = ""
    join_next = False

    for char in text:
        if not current:
            current = char
            join_next = char == "\u200d"
            continue

        if join_next or current.endswith("\u200d") or _is_grapheme_extend(char):
            current += char
        else:
            clusters.append(current)
            current = char
        join_next = char == "\u200d"

    if current:
        clusters.append(current)
    return clusters


def truncate_graphemes(text: str, limit: int) -> str:
    clusters = split_graphemes(text)
    if len(clusters) <= limit:
        return text
    if limit <= 1:
        return ELLIPSIS
    return "".join(clusters[: limit - 1]) + ELLIPSIS


def truncate_episode_label(label: object) -> str:
    normalized = str(label or "")
    match = _HEADER_WITH_SUBTITLE_RE.match(normalized)
    if match:
        header = match.group("header")
        separator = match.group("separator")
        subtitle = match.group("subtitle")
        return f"{header}{separator}{truncate_graphemes(subtitle, SUBTITLE_LIMIT)}"
    return truncate_graphemes(normalized, FALLBACK_LABEL_LIMIT)


def series_label_for_snapshot(work_id: object, snapshot: Mapping[str, object]) -> str:
    return str(
        snapshot.get("series_title")
        or snapshot.get("seriesTitle")
        or snapshot.get("series")
        or work_id
    )


def episode_label_for_snapshot(
    snapshot: Mapping[str, object],
    *,
    fallback: str = "未取得",
) -> str:
    return str(
        snapshot.get("episode_title")
        or snapshot.get("episodeTitle")
        or snapshot.get("episode_code")
        or snapshot.get("episodeCode")
        or snapshot.get("url")
        or fallback
    )


def format_discord_link(label: object, url: object) -> str:
    rendered_label = truncate_episode_label(label)
    rendered_url = str(url or "").strip()
    if not rendered_url:
        return rendered_label
    return f"[{rendered_label}](<{rendered_url}>)"
