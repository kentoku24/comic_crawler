#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .sources import HttpClient, RequestsHttpClient, registered_sources
from .sources.base import SourceParseError
from .sources.champion_cross import (
    ChampionCrossAdapter,
    canonical_champion_cross_series_rss_url,
    extract_champion_cross_series_hash,
    parse_champion_cross_rss_latest,
)
from .sources.comic_action import ComicActionAdapter, extract_comic_action_series_id, parse_comic_action_title
from .sources.comic_walker import ComicWalkerAdapter, parse_comic_walker_title
from .sources.kakuyomu import KakuyomuAdapter
from .sources.util import html_title


@dataclass(frozen=True)
class SourceCanaryContract:
    source: str
    seed_url: str
    fixture_bundle: str
    monitored_signals: Tuple[str, ...]


@dataclass(frozen=True)
class CanaryObservation:
    name: str
    value: str

    def to_dict(self) -> Dict[str, str]:
        return {"name": self.name, "value": self.value}


@dataclass(frozen=True)
class SourceCanaryResult:
    source: str
    status: str
    seed_url: str
    checked_urls: Tuple[str, ...]
    fixture_bundle: str
    monitored_signals: Tuple[str, ...]
    observations: Tuple[CanaryObservation, ...]
    next_action: str
    error_type: Optional[str] = None
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "source": self.source,
            "status": self.status,
            "seedUrl": self.seed_url,
            "checkedUrls": list(self.checked_urls),
            "fixtureBundle": self.fixture_bundle,
            "monitoredSignals": list(self.monitored_signals),
            "observations": [observation.to_dict() for observation in self.observations],
            "nextAction": self.next_action,
        }
        if self.error_type:
            payload["errorType"] = self.error_type
        if self.message:
            payload["message"] = self.message
        return payload


DEFAULT_SOURCE_CANARY_CONTRACTS: Dict[str, SourceCanaryContract] = {
    "comic-walker": SourceCanaryContract(
        source="comic-walker",
        seed_url="https://comic-walker.com/detail/KC_003913_S",
        fixture_bundle="tests/fixtures/comic-walker/normal",
        monitored_signals=(
            "series page keeps __NEXT_DATA__",
            "latest episode code is discoverable for the same series",
            "latest episode page title still parses into series / episode labels",
        ),
    ),
    "comic-action": SourceCanaryContract(
        source="comic-action",
        seed_url="https://comic-action.com/episode/2550689798784879524",
        fixture_bundle="tests/fixtures/comic-action/normal",
        monitored_signals=(
            "seed episode page exposes series_id",
            "seed episode page exposes nextReadableProductUri",
            "latest episode page title still parses into series / episode labels",
        ),
    ),
    "champion-cross": SourceCanaryContract(
        source="champion-cross",
        seed_url="https://championcross.jp/episodes/f35108c56e75d",
        fixture_bundle="tests/fixtures/champion-cross/normal",
        monitored_signals=(
            "seed episode page exposes a stable series hash",
            "series RSS feed keeps the latest episode URL",
            "series RSS feed keeps the latest episode title",
        ),
    ),
    "kakuyomu": SourceCanaryContract(
        source="kakuyomu",
        seed_url="https://kakuyomu.jp/works/16818093092974667738/episodes/822139844009936710",
        fixture_bundle="tests/fixtures/kakuyomu/normal",
        monitored_signals=(
            "work page keeps __NEXT_DATA__",
            "latest episode id / title are discoverable from the work page payload",
            "latest episode page title is still readable",
        ),
    ),
}


def source_canary_contracts(
    selected_sources: Optional[Sequence[str]] = None,
) -> Tuple[SourceCanaryContract, ...]:
    sources = tuple(selected_sources) if selected_sources else registered_sources()
    missing = [source for source in sources if source not in DEFAULT_SOURCE_CANARY_CONTRACTS]
    if missing:
        raise RuntimeError(f"Missing source drift canary contract for: {', '.join(sorted(missing))}")
    return tuple(DEFAULT_SOURCE_CANARY_CONTRACTS[source] for source in sources)


def refresh_hint(contract: SourceCanaryContract) -> str:
    signals = "; ".join(contract.monitored_signals)
    return (
        f"Refresh {contract.fixture_bundle}, compare {signals}, and rerun "
        ".venv/bin/python -m unittest tests.test_source_drift tests.test_sources tests.test_check"
    )


def _comic_walker_canary(contract: SourceCanaryContract, http_client: HttpClient) -> Tuple[Tuple[str, ...], Tuple[CanaryObservation, ...]]:
    adapter = ComicWalkerAdapter()
    work = adapter.normalize(contract.seed_url)
    series_html = adapter._fetch_series_page(work, http_client)
    if "__NEXT_DATA__" not in series_html:
        raise SourceParseError("comic-walker: __NEXT_DATA__ not found")

    latest_code = adapter._parse_latest_episode_code(work, series_html)
    latest_url = f"{work.seed_url}/episodes/{latest_code}?episodeType=latest"
    latest_html = adapter._fetch_episode_page(latest_url, http_client)
    title = html_title(latest_html)
    _, episode_title = parse_comic_walker_title(title or "")
    if not episode_title:
        raise SourceParseError("comic-walker: latest episode title not found")

    return (
        (work.seed_url, latest_url),
        (
            CanaryObservation("series_page_signal", "__NEXT_DATA__"),
            CanaryObservation("latest_episode_code", latest_code),
            CanaryObservation("latest_episode_title", episode_title),
        ),
    )


def _comic_action_canary(contract: SourceCanaryContract, http_client: HttpClient) -> Tuple[Tuple[str, ...], Tuple[CanaryObservation, ...]]:
    adapter = ComicActionAdapter()
    work = adapter.normalize(contract.seed_url)

    seed_html = adapter._fetch_episode_page(work.seed_url, http_client)
    series_id = extract_comic_action_series_id(seed_html)
    if not series_id:
        raise SourceParseError("comic-action: series_id not found")

    next_url = adapter._parse_next_readable_url(seed_html)
    if not next_url:
        raise SourceParseError("comic-action: nextReadableProductUri not found")

    current_url = work.seed_url
    current_html = seed_html
    seen = {current_url}

    while True:
        candidate_url = adapter._parse_next_readable_url(current_html)
        if not candidate_url or candidate_url == current_url:
            break
        if candidate_url in seen:
            raise SourceParseError("comic-action: navigation loop detected")
        seen.add(candidate_url)
        current_url = candidate_url
        current_html = adapter._fetch_episode_page(current_url, http_client)

    page_title = html_title(current_html) or ""
    episode_title, _ = parse_comic_action_title(page_title)
    if not episode_title:
        raise SourceParseError("comic-action: latest episode title not found")

    return (
        (work.seed_url, current_url),
        (
            CanaryObservation("series_id", series_id),
            CanaryObservation("next_readable_url", next_url),
            CanaryObservation("latest_episode_title", episode_title),
        ),
    )


def _kakuyomu_canary(contract: SourceCanaryContract, http_client: HttpClient) -> Tuple[Tuple[str, ...], Tuple[CanaryObservation, ...]]:
    adapter = KakuyomuAdapter()
    work = adapter.normalize(contract.seed_url)
    numeric_work_id = work.metadata.get("numericWorkId")
    if not numeric_work_id:
        raise RuntimeError("kakuyomu: work descriptor missing numericWorkId")

    work_url = f"https://kakuyomu.jp/works/{numeric_work_id}"
    work_html = adapter._fetch_work_page(work_url, http_client)
    if "__NEXT_DATA__" not in work_html:
        raise SourceParseError("kakuyomu: __NEXT_DATA__ not found")

    latest_id, latest_title = adapter._parse_latest_episode(work_html)
    latest_url = f"{work_url}/episodes/{latest_id}"
    episode_html = adapter._fetch_episode_page(latest_url, http_client)
    page_title = html_title(episode_html)
    if not page_title:
        raise SourceParseError("kakuyomu: latest episode page title not found")

    return (
        (work_url, latest_url),
        (
            CanaryObservation("work_page_signal", "__NEXT_DATA__"),
            CanaryObservation("latest_episode_id", latest_id),
            CanaryObservation("latest_episode_title", latest_title),
        ),
    )


def _champion_cross_canary(
    contract: SourceCanaryContract,
    http_client: HttpClient,
) -> Tuple[Tuple[str, ...], Tuple[CanaryObservation, ...]]:
    adapter = ChampionCrossAdapter()
    work = adapter.normalize(contract.seed_url)

    episode_html = http_client.get_text(work.seed_url)
    series_hash = extract_champion_cross_series_hash(episode_html)
    if not series_hash:
        raise SourceParseError("champion-cross: series hash not found")

    rss_url = canonical_champion_cross_series_rss_url(series_hash)
    feed_text = http_client.get_text(rss_url)
    latest_url, latest_title, series_title = parse_champion_cross_rss_latest(feed_text)
    if not latest_title:
        raise SourceParseError("champion-cross: latest episode title not found")

    return (
        (work.seed_url, rss_url),
        (
            CanaryObservation("series_hash", series_hash),
            CanaryObservation("series_title", series_title or ""),
            CanaryObservation("latest_episode_url", latest_url),
            CanaryObservation("latest_episode_title", latest_title),
        ),
    )


CANARY_RUNNERS = {
    "comic-walker": _comic_walker_canary,
    "comic-action": _comic_action_canary,
    "champion-cross": _champion_cross_canary,
    "kakuyomu": _kakuyomu_canary,
}


def run_source_canary(
    contract: SourceCanaryContract,
    *,
    http_client: Optional[HttpClient] = None,
) -> SourceCanaryResult:
    runner = CANARY_RUNNERS.get(contract.source)
    if runner is None:
        raise RuntimeError(f"Unsupported canary source: {contract.source}")

    client = http_client or RequestsHttpClient()
    try:
        checked_urls, observations = runner(contract, client)
        return SourceCanaryResult(
            source=contract.source,
            status="ok",
            seed_url=contract.seed_url,
            checked_urls=checked_urls,
            fixture_bundle=contract.fixture_bundle,
            monitored_signals=contract.monitored_signals,
            observations=observations,
            next_action=refresh_hint(contract),
        )
    except Exception as exc:
        return SourceCanaryResult(
            source=contract.source,
            status="drift",
            seed_url=contract.seed_url,
            checked_urls=(),
            fixture_bundle=contract.fixture_bundle,
            monitored_signals=contract.monitored_signals,
            observations=(),
            next_action=refresh_hint(contract),
            error_type=exc.__class__.__name__,
            message=str(exc),
        )


def run_source_canaries(
    *,
    selected_sources: Optional[Sequence[str]] = None,
    http_client: Optional[HttpClient] = None,
) -> List[SourceCanaryResult]:
    client = http_client or RequestsHttpClient()
    return [
        run_source_canary(contract, http_client=client)
        for contract in source_canary_contracts(selected_sources)
    ]


def _format_text(results: Sequence[SourceCanaryResult]) -> str:
    passed = sum(1 for result in results if result.status == "ok")
    lines = [f"source drift canary: {passed}/{len(results)} passed"]
    for result in results:
        state = "OK" if result.status == "ok" else "DRIFT"
        lines.append(f"- {result.source}: {state}")
        lines.append(f"  seed_url: {result.seed_url}")
        if result.checked_urls:
            lines.append(f"  checked_urls: {', '.join(result.checked_urls)}")
        if result.message:
            lines.append(f"  error: {result.error_type}: {result.message}")
        for observation in result.observations:
            lines.append(f"  {observation.name}: {observation.value}")
        lines.append(f"  fixture_bundle: {result.fixture_bundle}")
        lines.append(f"  next_action: {result.next_action}")
    return "\n".join(lines)


def _json_payload(results: Sequence[SourceCanaryResult]) -> Dict[str, object]:
    return {
        "summary": {
            "total": len(results),
            "passed": sum(1 for result in results if result.status == "ok"),
            "failed": sum(1 for result in results if result.status != "ok"),
        },
        "results": [result.to_dict() for result in results],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run lightweight live source drift canaries.")
    parser.add_argument(
        "--source",
        action="append",
        choices=registered_sources(),
        dest="sources",
        help="Limit the canary run to a specific source. Repeat to select multiple sources.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    results = run_source_canaries(selected_sources=args.sources)
    if args.format == "json":
        json.dump(_json_payload(results), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(f"{_format_text(results)}\n")
    return 0 if all(result.status == "ok" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
