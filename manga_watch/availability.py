from __future__ import annotations

import re
from typing import Dict, List, Mapping, Optional

from manga_watch.discord_text import episode_label_for_snapshot, next_update_label_for_snapshot

EPISODE_NUMBER_PATTERNS = (
    re.compile(r"第\s*(\d+)\s*話"),
    re.compile(r"\bEpisode\s+(\d+)\b", re.IGNORECASE),
    re.compile(r"\bEp\.?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"#\s*(\d+)"),
)


def episode_label_candidates(snapshot: Mapping[str, object]) -> List[str]:
    candidates: List[str] = []
    for key in ("episodeTitle", "pageTitle", "episode_title", "page_title"):
        value = snapshot.get(key)
        if not isinstance(value, str):
            continue
        label = value.strip()
        if label and label not in candidates:
            candidates.append(label)
    return candidates


def chapter_number_from_text(value: object) -> Optional[int]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    for pattern in EPISODE_NUMBER_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group(1))
    return None


def episode_number_for_snapshot(snapshot: Mapping[str, object]) -> Optional[int]:
    for label in episode_label_candidates(snapshot):
        number = chapter_number_from_text(label)
        if number is not None:
            return number
    return None


def format_target_chapter(number: int) -> str:
    return f"第{int(number)}話"


def derive_latest_availability(snapshot: Mapping[str, object]) -> Dict[str, object]:
    existing = snapshot.get("availability")
    if isinstance(existing, Mapping):
        normalized = {
            "status": str(existing.get("status") or "unknown"),
        }
        latest_free_episode_number = existing.get(
            "latest_free_episode_number",
            existing.get("latestFreeEpisodeNumber"),
        )
        if latest_free_episode_number is not None:
            normalized["latest_free_episode_number"] = int(latest_free_episode_number)
        next_free_label = existing.get("next_free_label", existing.get("nextFreeLabel"))
        if next_free_label:
            normalized["next_free_label"] = str(next_free_label).strip()
        return normalized

    latest_free_episode_number = episode_number_for_snapshot(snapshot)
    next_free_label = next_update_label_for_snapshot(snapshot)
    availability: Dict[str, object] = {
        "status": "supported" if latest_free_episode_number is not None else "unknown",
    }
    if latest_free_episode_number is not None:
        availability["latest_free_episode_number"] = latest_free_episode_number
    if next_free_label:
        availability["next_free_label"] = next_free_label
    return availability


def latest_free_episode_label(snapshot: Mapping[str, object]) -> str:
    number = episode_number_for_snapshot(snapshot)
    if number is not None:
        return format_target_chapter(number)
    return episode_label_for_snapshot(snapshot)
