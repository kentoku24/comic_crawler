from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from manga_watch.availability import (
    chapter_number_from_text,
    derive_latest_availability,
    format_target_chapter,
    latest_free_episode_label,
)
from manga_watch.storage import load_canonical_works, load_state, load_watchlist

AVAILABILITY_COMMAND = "where"
USAGE_MESSAGE = "usage: where <作品名 or canonical_work_id> / <第N話 or N>"
UNKNOWN_WORK_MESSAGE = "結論: 指定された作品は canonical work に見つかりません"
SOURCE_LABELS = {
    "comic-action": "comic-action",
    "comic-walker": "comic-walker",
    "champion-cross": "champion-cross",
    "kakuyomu": "kakuyomu",
}


@dataclass(frozen=True)
class ResolvedQuery:
    work_query: str
    target_number: int


@dataclass(frozen=True)
class ProviderAvailability:
    work_id: str
    source_label: str
    display_url: Optional[str]
    latest_label: str
    latest_free_episode_number: Optional[int]
    next_free_label: Optional[str]
    status: str
    shortage: Optional[int]
    reason: str
    order: int


def parse_availability_query(message_content: object) -> Optional[ResolvedQuery]:
    normalized = str(message_content or "").strip()
    if normalized != AVAILABILITY_COMMAND and not normalized.startswith(f"{AVAILABILITY_COMMAND} "):
        return None

    remainder = normalized[len(AVAILABILITY_COMMAND) :].strip()
    if not remainder or "/" not in remainder:
        raise ValueError(USAGE_MESSAGE)

    work_query, target_text = (part.strip() for part in remainder.split("/", 1))
    if not work_query or not target_text:
        raise ValueError(USAGE_MESSAGE)

    target_number = chapter_number_from_text(target_text)
    if target_number is None:
        raise ValueError(USAGE_MESSAGE)
    return ResolvedQuery(work_query=work_query, target_number=target_number)


def handle_availability_query(
    message_content: object,
    *,
    watchlist_path: Optional[str] = None,
    state_path: Optional[str] = None,
    catalog_path: Optional[str] = None,
    watchlist_loader: Callable[[Optional[str]], Dict[str, object]] = load_watchlist,
    state_loader: Callable[[Optional[str]], Dict[str, object]] = load_state,
    catalog_loader: Callable[[Optional[str]], Dict[str, object]] = load_canonical_works,
) -> Optional[str]:
    try:
        query = parse_availability_query(message_content)
    except ValueError as exc:
        return str(exc)
    if query is None:
        return None

    watchlist = watchlist_loader(watchlist_path)
    state = state_loader(state_path)
    catalog = catalog_loader(catalog_path)
    return build_availability_query_response(
        query,
        watchlist=watchlist,
        state=state,
        catalog=catalog,
    )


def build_availability_query_response(
    query: ResolvedQuery,
    *,
    watchlist: Mapping[str, object],
    state: Mapping[str, object],
    catalog: Mapping[str, object],
) -> str:
    canonical_work = resolve_canonical_work(catalog, query.work_query)
    lines = [
        f"作品: {query.work_query}",
        f"目標話: {format_target_chapter(query.target_number)}",
    ]

    if canonical_work is None:
        lines.append(UNKNOWN_WORK_MESSAGE)
        return "\n".join(lines)

    lines[0] = f"作品: {canonical_work['title']}"

    evaluations = evaluate_confirmed_providers(
        watchlist=watchlist,
        state=state,
        provider_work_ids=canonical_work.get("provider_work_ids", []),
        target_number=query.target_number,
    )
    if not evaluations:
        lines.append("結論: confirmed provider がありません")
        return "\n".join(lines)

    immediate = [item for item in evaluations if item.status == "immediate"]
    waitable = [item for item in evaluations if item.status == "wait"]
    lagging = [item for item in evaluations if item.status == "lagging"]
    unknown = [item for item in evaluations if item.status == "unknown"]

    if immediate:
        lines.append("結論: 今すぐ無料で読める候補があります")
        lines.append("今すぐ無料で読める候補:")
        for item in immediate:
            lines.append(f"- {item.source_label} 無料最新: {item.latest_label}")
    elif waitable:
        best = min(waitable, key=lambda item: (item.shortage or 10**9, item.order))
        lines.append("結論: 今すぐ無料で読める候補はありません")
        lines.append(
            f"最短候補: {best.source_label} あと{best.shortage}話不足 / 次回更新: {best.next_free_label}"
        )
    else:
        lines.append("結論: 目標話にはまだ届いていません")
        if lagging:
            best = min(lagging, key=lambda item: (item.shortage or 10**9, item.order))
            lines.append(f"最短でもあと{best.shortage}話不足です")

    if unknown:
        lines.append("注記: 不明なサイトがあります")

    lines.append("判定詳細:")
    for item in evaluations:
        lines.append(f"- {item.source_label}: {item.reason}")
    return "\n".join(lines)


def resolve_canonical_work(catalog: Mapping[str, object], query: str) -> Optional[Mapping[str, object]]:
    works = catalog.get("works", [])
    if not isinstance(works, list):
        return None

    normalized_query = str(query).strip()
    if not normalized_query:
        return None

    for work in works:
        if not isinstance(work, Mapping):
            continue
        if normalized_query == str(work.get("id") or "").strip():
            return work
        if normalized_query == str(work.get("title") or "").strip():
            return work
        aliases = work.get("aliases", [])
        if isinstance(aliases, list) and normalized_query in {str(alias).strip() for alias in aliases}:
            return work
    return None


def evaluate_confirmed_providers(
    *,
    watchlist: Mapping[str, object],
    state: Mapping[str, object],
    provider_work_ids: Sequence[object],
    target_number: int,
) -> List[ProviderAvailability]:
    works = watchlist.get("works", [])
    state_works = state.get("works", {})
    if not isinstance(works, list) or not isinstance(state_works, Mapping):
        return []

    order_lookup: Dict[str, Tuple[int, Mapping[str, object]]] = {}
    for index, raw_entry in enumerate(works):
        if not isinstance(raw_entry, Mapping) or not bool(raw_entry.get("enabled")):
            continue
        work_id = str(raw_entry.get("id") or "").strip()
        if work_id:
            order_lookup[work_id] = (index, raw_entry)

    evaluations: List[ProviderAvailability] = []
    for raw_work_id in provider_work_ids:
        work_id = str(raw_work_id).strip()
        if not work_id or work_id not in order_lookup:
            continue
        order, watch_entry = order_lookup[work_id]
        state_entry = state_works.get(work_id, {})
        if not isinstance(state_entry, Mapping):
            state_entry = {}
        latest = state_entry.get("latest", {})
        if not isinstance(latest, Mapping):
            latest = {}
        evaluations.append(
            evaluate_provider(
                work_id=work_id,
                watch_entry=watch_entry,
                latest=latest,
                target_number=target_number,
                order=order,
            )
        )
    return evaluations


def evaluate_provider(
    *,
    work_id: str,
    watch_entry: Mapping[str, object],
    latest: Mapping[str, object],
    target_number: int,
    order: int,
) -> ProviderAvailability:
    source = str(latest.get("source") or watch_entry.get("source") or work_id).strip()
    source_label = SOURCE_LABELS.get(source, source)
    display_url = str(latest.get("url") or watch_entry.get("seed_url") or "").strip() or None

    if not latest:
        return ProviderAvailability(
            work_id=work_id,
            source_label=source_label,
            display_url=display_url,
            latest_label="未取得",
            latest_free_episode_number=None,
            next_free_label=None,
            status="unknown",
            shortage=None,
            reason="判定不能（保存済み最新話が未取得です）",
            order=order,
        )

    availability = derive_latest_availability(latest)
    latest_number = availability.get("latest_free_episode_number")
    if latest_number is not None:
        latest_number = int(latest_number)
    next_free_label = availability.get("next_free_label")
    if next_free_label is not None:
        next_free_label = str(next_free_label)
    latest_label = latest_free_episode_label(latest)

    if latest_number is None:
        return ProviderAvailability(
            work_id=work_id,
            source_label=source_label,
            display_url=display_url,
            latest_label=latest_label,
            latest_free_episode_number=None,
            next_free_label=next_free_label,
            status="unknown",
            shortage=None,
            reason="判定不能（話番号を抽出できません）",
            order=order,
        )

    shortage = max(0, target_number - latest_number)
    if latest_number >= target_number:
        return ProviderAvailability(
            work_id=work_id,
            source_label=source_label,
            display_url=display_url,
            latest_label=latest_label,
            latest_free_episode_number=latest_number,
            next_free_label=next_free_label,
            status="immediate",
            shortage=0,
            reason=f"今すぐ読める（無料最新: {latest_label}）",
            order=order,
        )

    if next_free_label:
        return ProviderAvailability(
            work_id=work_id,
            source_label=source_label,
            display_url=display_url,
            latest_label=latest_label,
            latest_free_episode_number=latest_number,
            next_free_label=next_free_label,
            status="wait",
            shortage=shortage,
            reason=f"あと{shortage}話不足（無料最新: {latest_label} / 次回更新: {next_free_label}）",
            order=order,
        )

    return ProviderAvailability(
        work_id=work_id,
        source_label=source_label,
        display_url=display_url,
        latest_label=latest_label,
        latest_free_episode_number=latest_number,
        next_free_label=None,
        status="lagging",
        shortage=shortage,
        reason=f"あと{shortage}話不足（無料最新: {latest_label}）",
        order=order,
    )
