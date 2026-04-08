from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

MAIN_STORY = "main_story"
BONUS = "bonus"
ANNOUNCEMENT = "announcement"
UNKNOWN = "unknown"
SUPPORTED_UPDATE_TYPES = (
    MAIN_STORY,
    BONUS,
    ANNOUNCEMENT,
    UNKNOWN,
)

DEFAULT_NOTIFY_UPDATE_TYPES = {MAIN_STORY, UNKNOWN}
SUPPRESSED_UPDATE_TYPES = {BONUS, ANNOUNCEMENT}

MAIN_STORY_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"第\s*\d+\s*(?:話|回|限目|章|幕)"),
    re.compile(r"\[\s*\d+\s*話\s*\]"),
    re.compile(r"\b(?:episode|ep\.?)\s*\d+\b", re.IGNORECASE),
    re.compile(r"#\s*\d+\b"),
)
BONUS_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"番外編"),
    re.compile(r"おまけ"),
    re.compile(r"特別編"),
    re.compile(r"\bextra\b", re.IGNORECASE),
    re.compile(r"幕間"),
    re.compile(r"ショート"),
    re.compile(r"4コマ"),
)
ANNOUNCEMENT_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"お知らせ"),
    re.compile(r"告知"),
    re.compile(r"休載"),
    re.compile(r"更新延期"),
    re.compile(r"次回更新"),
    re.compile(r"キャンペーン"),
    re.compile(r"メンテナンス"),
    re.compile(r"単行本"),
    re.compile(r"コミックス"),
)


@dataclass(frozen=True)
class UpdateClassification:
    update_type: str
    classification_reason: str
    default_notify: bool


def default_notify_for_update_type(update_type: str) -> bool:
    return update_type in DEFAULT_NOTIFY_UPDATE_TYPES


def classify_update(
    *,
    episode_title: Optional[str] = None,
    page_title: Optional[str] = None,
) -> UpdateClassification:
    field_matches = []
    for field_name, text in (("episode_title", episode_title), ("page_title", page_title)):
        matches = _matched_update_types(text)
        if matches:
            field_matches.append((field_name, matches))

    all_matches = {match for _, matches in field_matches for match in matches}
    if len(all_matches) > 1:
        if all_matches.issubset(SUPPRESSED_UPDATE_TYPES):
            suppressed_type = _suppressed_conflict_update_type(all_matches)
            return UpdateClassification(
                update_type=suppressed_type,
                classification_reason=_suppressed_conflict_reason(field_matches, suppressed_type),
                default_notify=False,
            )
        return UpdateClassification(
            update_type=UNKNOWN,
            classification_reason=_conflict_reason(field_matches),
            default_notify=True,
        )

    if len(all_matches) == 1:
        update_type = next(iter(all_matches))
        field_name = next(field_name for field_name, matches in field_matches if update_type in matches)
        return UpdateClassification(
            update_type=update_type,
            classification_reason=_single_match_reason(field_name, update_type),
            default_notify=default_notify_for_update_type(update_type),
        )

    return UpdateClassification(
        update_type=UNKNOWN,
        classification_reason="no classification markers matched",
        default_notify=True,
    )


def _matched_update_types(text: Optional[str]) -> set[str]:
    if not text:
        return set()

    normalized = _normalize_text(text)
    matches = set()
    if any(pattern.search(normalized) for pattern in MAIN_STORY_PATTERNS):
        matches.add(MAIN_STORY)
    if any(pattern.search(normalized) for pattern in BONUS_PATTERNS):
        matches.add(BONUS)
    if any(pattern.search(normalized) for pattern in ANNOUNCEMENT_PATTERNS):
        matches.add(ANNOUNCEMENT)
    return matches


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _single_match_reason(field_name: str, update_type: str) -> str:
    if update_type == MAIN_STORY:
        return f"{field_name} matched main-story numbering"
    if update_type == BONUS:
        return f"{field_name} matched bonus marker"
    if update_type == ANNOUNCEMENT:
        return f"{field_name} matched announcement marker"
    return f"{field_name} matched unknown marker"


def _conflict_reason(field_matches: Sequence[tuple[str, set[str]]]) -> str:
    for field_name, matches in field_matches:
        if len(matches) > 1:
            joined = " and ".join(_reason_label(match) for match in sorted(matches))
            return f"{field_name} matched both {joined}"

    joined = " and ".join(
        _reason_label(match) for match in sorted({match for _, matches in field_matches for match in matches})
    )
    return f"conflicting classification markers across fields: {joined}"


def _suppressed_conflict_update_type(matches: set[str]) -> str:
    if ANNOUNCEMENT in matches:
        return ANNOUNCEMENT
    return BONUS


def _suppressed_conflict_reason(
    field_matches: Sequence[tuple[str, set[str]]],
    update_type: str,
) -> str:
    return f"{_conflict_reason(field_matches)}; kept suppressed as {update_type}"


def _reason_label(update_type: str) -> str:
    if update_type == MAIN_STORY:
        return "main-story markers"
    if update_type == BONUS:
        return "bonus markers"
    if update_type == ANNOUNCEMENT:
        return "announcement markers"
    return "unknown markers"
