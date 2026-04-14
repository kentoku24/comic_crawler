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
from .sources.comic_earthstar import (
    ComicEarthstarAdapter,
    extract_comic_earthstar_series_id,
    parse_comic_earthstar_feed_latest,
    parse_comic_earthstar_title,
)
from .sources.comicborder import (
    ComicBorderAdapter,
    extract_comicborder_series_id,
    parse_comicborder_feed_latest,
    parse_comicborder_title,
)
from .sources.comic_trail import (
    ComicTrailAdapter,
    extract_comic_trail_series_id,
    parse_comic_trail_feed_latest,
    parse_comic_trail_title,
)
from .sources.comic_walker import ComicWalkerAdapter, parse_comic_walker_title
from .sources.firecross import (
    FirecrossAdapter,
    extract_firecross_latest_reader_url,
    extract_firecross_series_id,
    parse_firecross_reader_title,
)
from .sources.gaugau import GaugauAdapter
from .sources.kakuyomu import KakuyomuAdapter
from .sources.kuragebunch import (
    KuragebunchAdapter,
    extract_kuragebunch_series_id,
    parse_kuragebunch_feed_latest,
    parse_kuragebunch_title,
)
from .sources.magapoke import (
    MagapokeAdapter,
    canonical_magapoke_rss_url,
    extract_magapoke_next_update_label,
    extract_magapoke_rss_url,
    parse_magapoke_rss_latest,
)
from .sources.nicovideo_manga import (
    NicovideoMangaAdapter,
    canonical_nicovideo_manga_latest_url,
)
from .sources.shonenjumpplus import (
    ShonenJumpPlusAdapter,
    extract_shonenjumpplus_series_id,
    parse_shonenjumpplus_title,
    parse_shonenjumpplus_feed_latest,
)
from .sources.sunday_webry import (
    SundayWebryAdapter,
    canonical_sunday_webry_series_feed_url,
    extract_sunday_webry_series_id,
    parse_sunday_webry_feed_latest,
    parse_sunday_webry_title,
)
from .sources.takecomic import (
    TakecomicAdapter,
    canonical_takecomic_series_rss_url,
    extract_takecomic_series_hash,
    parse_takecomic_rss_latest,
)
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
    "comic-earthstar": SourceCanaryContract(
        source="comic-earthstar",
        seed_url="https://comic-earthstar.com/episode/12207421983526541742",
        fixture_bundle="tests/fixtures/comic-earthstar/normal",
        monitored_signals=(
            "seed episode page exposes a stable series id",
            "series RSS feed keeps the latest episode URL",
            "latest episode page title still parses into series / episode labels",
        ),
    ),
    "comicborder": SourceCanaryContract(
        source="comicborder",
        seed_url="https://comicborder.com/episode/12207421983437812169",
        fixture_bundle="tests/fixtures/comicborder/normal",
        monitored_signals=(
            "seed episode page exposes a stable series id",
            "series RSS feed keeps the latest episode URL",
            "latest episode page title still parses into series / episode labels",
        ),
    ),
    "comic-trail": SourceCanaryContract(
        source="comic-trail",
        seed_url="https://comic-trail.com/episode/2550689798402927313",
        fixture_bundle="tests/fixtures/comic-trail/normal",
        monitored_signals=(
            "seed episode page exposes a stable series id",
            "series RSS feed keeps the latest episode URL",
            "latest episode page title still parses into series / episode labels",
        ),
    ),
    "kuragebunch": SourceCanaryContract(
        source="kuragebunch",
        seed_url="https://kuragebunch.com/episode/2550912964856491139",
        fixture_bundle="tests/fixtures/kuragebunch/normal",
        monitored_signals=(
            "seed episode page exposes a stable series id",
            "series RSS feed keeps the latest episode URL",
            "latest episode page title still parses into series / episode labels",
        ),
    ),
    "shonenjumpplus": SourceCanaryContract(
        source="shonenjumpplus",
        seed_url="https://shonenjumpplus.com/episode/17107419589191805801",
        fixture_bundle="tests/fixtures/shonenjumpplus/normal",
        monitored_signals=(
            "seed episode page exposes a stable series id",
            "series RSS feed keeps the latest episode URL",
            "latest episode page title still parses into series / episode labels",
        ),
    ),
    "sunday-webry": SourceCanaryContract(
        source="sunday-webry",
        seed_url="https://www.sunday-webry.com/episode/12207421983581042977",
        fixture_bundle="tests/fixtures/sunday-webry/normal",
        monitored_signals=(
            "seed episode page exposes a stable series id",
            "series RSS feed keeps the latest episode URL",
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
    "magapoke": SourceCanaryContract(
        source="magapoke",
        seed_url="https://pocket.shonenmagazine.com/title/03021",
        fixture_bundle="tests/fixtures/magapoke/normal",
        monitored_signals=(
            "title page exposes the series RSS feed URL",
            "title page exposes the next update label",
            "series RSS feed keeps the latest episode URL and title",
        ),
    ),
    "firecross": SourceCanaryContract(
        source="firecross",
        seed_url="https://firecross.jp/reader/19386",
        fixture_bundle="tests/fixtures/firecross/normal",
        monitored_signals=(
            "reader page exposes a stable series id",
            "series page keeps the latest reader URL",
            "latest reader page title is still readable",
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
    "nicovideo-manga": SourceCanaryContract(
        source="nicovideo-manga",
        seed_url="https://sp.manga.nicovideo.jp/comic/53764",
        fixture_bundle="tests/fixtures/nicovideo-manga/normal",
        monitored_signals=(
            "latest page keeps a watch/mg URL for the newest episode",
            "latest page title still parses into series / episode labels",
            "canonical comic URL remains stable for the same comic id",
        ),
    ),
    "gaugau": SourceCanaryContract(
        source="gaugau",
        seed_url="https://gaugau.futabanet.jp/list/work/600a5fd37765610d30010000",
        fixture_bundle="tests/fixtures/gaugau/normal",
        monitored_signals=(
            "canonical work URL remains stable for the same work token",
            "work page keeps a latest free episode URL",
            "latest episode page title still parses into series / episode labels",
        ),
    ),
    "takecomic": SourceCanaryContract(
        source="takecomic",
        seed_url="https://takecomic.jp/series/3f846451aff2d",
        fixture_bundle="tests/fixtures/takecomic/normal",
        monitored_signals=(
            "series page keeps a stable series hash",
            "series RSS feed keeps the latest episode URL",
            "series RSS feed keeps the latest episode title",
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


def _shonenjumpplus_canary(
    contract: SourceCanaryContract,
    http_client: HttpClient,
) -> Tuple[Tuple[str, ...], Tuple[CanaryObservation, ...]]:
    adapter = ShonenJumpPlusAdapter()
    work = adapter.normalize(contract.seed_url)

    checked_urls = []
    if work.seed_url.endswith("/rss") or "/rss/series/" in work.seed_url:
        rss_url = work.seed_url
        series_id = str(work.metadata.get("seriesId") or "") or rss_url.rstrip("/").rsplit("/", 1)[-1]
        feed_text = http_client.get_text(rss_url)
        checked_urls.append(rss_url)
        latest_url, latest_title, _ = parse_shonenjumpplus_feed_latest(feed_text)
        latest_html = http_client.get_text(latest_url)
        checked_urls.append(latest_url)
    else:
        episode_html = http_client.get_text(work.seed_url)
        checked_urls.append(work.seed_url)
        series_id = extract_shonenjumpplus_series_id(episode_html)
        if not series_id:
            raise SourceParseError("shonenjumpplus: series id not found")
        rss_url = f"https://shonenjumpplus.com/rss/series/{series_id}"
        feed_text = http_client.get_text(rss_url)
        checked_urls.append(rss_url)
        latest_url, latest_title, _ = parse_shonenjumpplus_feed_latest(feed_text)
        latest_html = http_client.get_text(latest_url)
        checked_urls.append(latest_url)

    page_title = html_title(latest_html) or ""
    if not series_id:
        raise SourceParseError("shonenjumpplus: series id not found")
    if not latest_title:
        raise SourceParseError("shonenjumpplus: latest episode title not found")
    if not page_title:
        raise SourceParseError("shonenjumpplus: latest episode page title not found")
    parsed_episode_title, parsed_series_title = parse_shonenjumpplus_title(page_title)
    if not parsed_episode_title:
        raise SourceParseError("shonenjumpplus: latest episode title could not be parsed from page title")
    if not parsed_series_title:
        raise SourceParseError("shonenjumpplus: series title could not be parsed from page title")

    return (
        tuple(checked_urls),
        (
            CanaryObservation("series_id", series_id),
            CanaryObservation("latest_episode_url", latest_url),
            CanaryObservation("latest_episode_title", parsed_episode_title),
            CanaryObservation("series_title", parsed_series_title),
        ),
    )


def _comicborder_canary(
    contract: SourceCanaryContract,
    http_client: HttpClient,
) -> Tuple[Tuple[str, ...], Tuple[CanaryObservation, ...]]:
    adapter = ComicBorderAdapter()
    work = adapter.normalize(contract.seed_url)

    checked_urls = []
    if work.seed_url.endswith("/rss") or "/rss/series/" in work.seed_url:
        rss_url = work.seed_url
        series_id = str(work.metadata.get("seriesId") or "") or rss_url.rstrip("/").rsplit("/", 1)[-1]
        feed_text = http_client.get_text(rss_url)
        checked_urls.append(rss_url)
        latest_url, latest_title, _ = parse_comicborder_feed_latest(feed_text)
        latest_html = http_client.get_text(latest_url)
        checked_urls.append(latest_url)
    else:
        episode_html = http_client.get_text(work.seed_url)
        checked_urls.append(work.seed_url)
        series_id = extract_comicborder_series_id(episode_html)
        if not series_id:
            raise SourceParseError("comicborder: series id not found")
        rss_url = f"https://comicborder.com/rss/series/{series_id}"
        feed_text = http_client.get_text(rss_url)
        checked_urls.append(rss_url)
        latest_url, latest_title, _ = parse_comicborder_feed_latest(feed_text)
        latest_html = http_client.get_text(latest_url)
        checked_urls.append(latest_url)

    page_title = html_title(latest_html) or ""
    if not latest_title:
        raise SourceParseError("comicborder: latest episode title not found")
    if not page_title:
        raise SourceParseError("comicborder: latest episode page title not found")
    parsed_episode_title, parsed_series_title = parse_comicborder_title(page_title)
    if not parsed_episode_title:
        raise SourceParseError("comicborder: latest episode title could not be parsed from page title")
    if not parsed_series_title:
        raise SourceParseError("comicborder: series title could not be parsed from page title")

    return (
        tuple(checked_urls),
        (
            CanaryObservation("series_id", series_id),
            CanaryObservation("latest_episode_url", latest_url),
            CanaryObservation("latest_episode_title", parsed_episode_title),
            CanaryObservation("series_title", parsed_series_title),
        ),
    )


def _comic_earthstar_canary(
    contract: SourceCanaryContract,
    http_client: HttpClient,
) -> Tuple[Tuple[str, ...], Tuple[CanaryObservation, ...]]:
    adapter = ComicEarthstarAdapter()
    work = adapter.normalize(contract.seed_url)

    checked_urls = []
    if work.seed_url.endswith("/rss") or "/rss/series/" in work.seed_url:
        rss_url = work.seed_url
        series_id = str(work.metadata.get("seriesId") or "") or rss_url.rstrip("/").rsplit("/", 1)[-1]
        feed_text = http_client.get_text(rss_url)
        checked_urls.append(rss_url)
        latest_url, latest_title, _ = parse_comic_earthstar_feed_latest(feed_text)
        latest_html = http_client.get_text(latest_url)
        checked_urls.append(latest_url)
    else:
        episode_html = http_client.get_text(work.seed_url)
        checked_urls.append(work.seed_url)
        series_id = extract_comic_earthstar_series_id(episode_html)
        if not series_id:
            raise SourceParseError("comic-earthstar: series id not found")
        rss_url = f"https://comic-earthstar.com/rss/series/{series_id}"
        feed_text = http_client.get_text(rss_url)
        checked_urls.append(rss_url)
        latest_url, latest_title, _ = parse_comic_earthstar_feed_latest(feed_text)
        latest_html = http_client.get_text(latest_url)
        checked_urls.append(latest_url)

    page_title = html_title(latest_html) or ""
    if not latest_title:
        raise SourceParseError("comic-earthstar: latest episode title not found")
    if not page_title:
        raise SourceParseError("comic-earthstar: latest episode page title not found")
    parsed_episode_title, parsed_series_title = parse_comic_earthstar_title(page_title)
    if not parsed_episode_title:
        raise SourceParseError("comic-earthstar: latest episode title could not be parsed from page title")
    if not parsed_series_title:
        raise SourceParseError("comic-earthstar: series title could not be parsed from page title")

    return (
        tuple(checked_urls),
        (
            CanaryObservation("series_id", series_id),
            CanaryObservation("latest_episode_url", latest_url),
            CanaryObservation("latest_episode_title", parsed_episode_title),
            CanaryObservation("series_title", parsed_series_title),
        ),
    )


def _sunday_webry_canary(
    contract: SourceCanaryContract,
    http_client: HttpClient,
) -> Tuple[Tuple[str, ...], Tuple[CanaryObservation, ...]]:
    adapter = SundayWebryAdapter()
    work = adapter.normalize(contract.seed_url)

    checked_urls = []
    if work.seed_url.endswith("/rss") or "/rss/series/" in work.seed_url:
        rss_url = work.seed_url
        series_id = str(work.metadata.get("seriesId") or "") or rss_url.rstrip("/").rsplit("/", 1)[-1]
        feed_text = http_client.get_text(rss_url)
        checked_urls.append(rss_url)
        latest_url, latest_title, _ = parse_sunday_webry_feed_latest(feed_text)
        latest_html = http_client.get_text(latest_url)
        checked_urls.append(latest_url)
    else:
        episode_html = http_client.get_text(work.seed_url)
        checked_urls.append(work.seed_url)
        series_id = extract_sunday_webry_series_id(episode_html)
        if not series_id:
            raise SourceParseError("sunday-webry: series id not found")
        rss_url = canonical_sunday_webry_series_feed_url(series_id)
        feed_text = http_client.get_text(rss_url)
        checked_urls.append(rss_url)
        latest_url, latest_title, _ = parse_sunday_webry_feed_latest(feed_text)
        latest_html = episode_html if latest_url == work.seed_url else http_client.get_text(latest_url)
        if latest_url != work.seed_url:
            checked_urls.append(latest_url)

    page_title = html_title(latest_html) or ""
    if not latest_title:
        raise SourceParseError("sunday-webry: latest episode title not found")
    if not page_title:
        raise SourceParseError("sunday-webry: latest episode page title not found")
    parsed_episode_title, parsed_series_title = parse_sunday_webry_title(page_title)
    if not parsed_episode_title:
        raise SourceParseError("sunday-webry: latest episode title could not be parsed from page title")
    if not parsed_series_title:
        raise SourceParseError("sunday-webry: series title could not be parsed from page title")

    return (
        tuple(checked_urls),
        (
            CanaryObservation("series_id", series_id),
            CanaryObservation("latest_episode_url", latest_url),
            CanaryObservation("latest_episode_title", parsed_episode_title),
            CanaryObservation("series_title", parsed_series_title),
        ),
    )


def _comic_trail_canary(
    contract: SourceCanaryContract,
    http_client: HttpClient,
) -> Tuple[Tuple[str, ...], Tuple[CanaryObservation, ...]]:
    adapter = ComicTrailAdapter()
    work = adapter.normalize(contract.seed_url)

    episode_html = http_client.get_text(contract.seed_url)
    series_id = extract_comic_trail_series_id(episode_html)
    if not series_id:
        raise SourceParseError("comic-trail: series id not found")

    rss_url = f"https://comic-trail.com/rss/series/{series_id}"
    feed_text = http_client.get_text(rss_url)
    latest_url, latest_title, _ = parse_comic_trail_feed_latest(feed_text)
    latest_html = http_client.get_text(latest_url)
    page_title = html_title(latest_html) or ""
    if not latest_title:
        raise SourceParseError("comic-trail: latest episode title not found")
    parsed_episode_title, parsed_series_title = parse_comic_trail_title(page_title)
    if not parsed_episode_title:
        raise SourceParseError("comic-trail: latest episode title could not be parsed from page title")
    if not parsed_series_title:
        raise SourceParseError("comic-trail: series title could not be parsed from page title")

    return (
        (work.seed_url, rss_url, latest_url),
        (
            CanaryObservation("series_id", series_id),
            CanaryObservation("latest_episode_url", latest_url),
            CanaryObservation("latest_episode_title", parsed_episode_title),
            CanaryObservation("series_title", parsed_series_title),
        ),
    )


def _kuragebunch_canary(
    contract: SourceCanaryContract,
    http_client: HttpClient,
) -> Tuple[Tuple[str, ...], Tuple[CanaryObservation, ...]]:
    adapter = KuragebunchAdapter()
    work = adapter.normalize(contract.seed_url)

    checked_urls = []
    if work.seed_url.endswith("/rss") or "/rss/series/" in work.seed_url:
        rss_url = work.seed_url
        series_id = str(work.metadata.get("seriesId") or "") or rss_url.rstrip("/").rsplit("/", 1)[-1]
        feed_text = http_client.get_text(rss_url)
        checked_urls.append(rss_url)
        latest_url, latest_title, _ = parse_kuragebunch_feed_latest(feed_text)
        latest_html = http_client.get_text(latest_url)
        checked_urls.append(latest_url)
    else:
        episode_html = http_client.get_text(work.seed_url)
        checked_urls.append(work.seed_url)
        series_id = extract_kuragebunch_series_id(episode_html)
        if not series_id:
            raise SourceParseError("kuragebunch: series id not found")
        rss_url = f"https://kuragebunch.com/rss/series/{series_id}"
        feed_text = http_client.get_text(rss_url)
        checked_urls.append(rss_url)
        latest_url, latest_title, _ = parse_kuragebunch_feed_latest(feed_text)
        latest_html = http_client.get_text(latest_url)
        checked_urls.append(latest_url)

    page_title = html_title(latest_html) or ""
    if not latest_title:
        raise SourceParseError("kuragebunch: latest episode title not found")
    if not page_title:
        raise SourceParseError("kuragebunch: latest episode page title not found")
    parsed_episode_title, parsed_series_title = parse_kuragebunch_title(page_title)
    if not parsed_episode_title:
        raise SourceParseError("kuragebunch: latest episode title could not be parsed from page title")
    if not parsed_series_title:
        raise SourceParseError("kuragebunch: series title could not be parsed from page title")

    return (
        tuple(checked_urls),
        (
            CanaryObservation("series_id", series_id),
            CanaryObservation("latest_episode_url", latest_url),
            CanaryObservation("latest_episode_title", parsed_episode_title),
            CanaryObservation("series_title", parsed_series_title),
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


def _magapoke_canary(
    contract: SourceCanaryContract,
    http_client: HttpClient,
) -> Tuple[Tuple[str, ...], Tuple[CanaryObservation, ...]]:
    adapter = MagapokeAdapter()
    work = adapter.normalize(contract.seed_url)

    title_html = http_client.get_text(work.seed_url)
    rss_url = extract_magapoke_rss_url(title_html)
    if not rss_url:
        title_id = str(work.metadata.get("titleId") or "")
        if not title_id:
            raise SourceParseError("magapoke: title id not found")
        rss_url = canonical_magapoke_rss_url(title_id)

    next_update_label = extract_magapoke_next_update_label(title_html)
    if not next_update_label:
        raise SourceParseError("magapoke: next update label not found")

    feed_text = http_client.get_text(rss_url)
    latest_url, latest_title, series_title = parse_magapoke_rss_latest(feed_text)
    if not latest_title:
        raise SourceParseError("magapoke: latest episode title not found")

    return (
        (work.seed_url, rss_url),
        (
            CanaryObservation("rss_url", rss_url),
            CanaryObservation("next_update_label", next_update_label),
            CanaryObservation("series_title", series_title or ""),
            CanaryObservation("latest_episode_url", latest_url),
            CanaryObservation("latest_episode_title", latest_title),
        ),
    )


def _takecomic_canary(
    contract: SourceCanaryContract,
    http_client: HttpClient,
) -> Tuple[Tuple[str, ...], Tuple[CanaryObservation, ...]]:
    adapter = TakecomicAdapter()
    work = adapter.normalize(contract.seed_url)

    series_hash = str(work.metadata.get("seriesHash") or "")
    if not series_hash:
        series_html = http_client.get_text(work.seed_url)
        series_hash = extract_takecomic_series_hash(series_html) or ""
    if not series_hash:
        raise SourceParseError("takecomic: series hash not found")

    rss_url = canonical_takecomic_series_rss_url(series_hash)
    feed_text = http_client.get_text(rss_url)
    latest_url, latest_title, series_title = parse_takecomic_rss_latest(feed_text)
    if not latest_title:
        raise SourceParseError("takecomic: latest episode title not found")

    return (
        (work.seed_url, rss_url),
        (
            CanaryObservation("series_hash", series_hash),
            CanaryObservation("series_title", series_title or ""),
            CanaryObservation("latest_episode_url", latest_url),
            CanaryObservation("latest_episode_title", latest_title),
        ),
    )


def _firecross_canary(
    contract: SourceCanaryContract,
    http_client: HttpClient,
) -> Tuple[Tuple[str, ...], Tuple[CanaryObservation, ...]]:
    adapter = FirecrossAdapter()
    work = adapter.normalize(contract.seed_url)

    reader_html = http_client.get_text(work.seed_url)
    series_id = extract_firecross_series_id(reader_html)
    if not series_id:
        raise SourceParseError("firecross: series id not found")

    series_url = f"https://firecross.jp/series/{series_id}"
    series_html = http_client.get_text(series_url)
    latest_url = extract_firecross_latest_reader_url(series_html)
    if not latest_url:
        raise SourceParseError("firecross: latest reader URL not found")

    latest_html = http_client.get_text(latest_url)
    latest_title, _ = parse_firecross_reader_title(html_title(latest_html) or "")
    if not latest_title:
        raise SourceParseError("firecross: latest episode title not found")

    return (
        (work.seed_url, series_url, latest_url),
        (
            CanaryObservation("series_id", series_id),
            CanaryObservation("latest_episode_url", latest_url),
            CanaryObservation("latest_episode_title", latest_title),
        ),
    )


def _nicovideo_manga_canary(
    contract: SourceCanaryContract,
    http_client: HttpClient,
) -> Tuple[Tuple[str, ...], Tuple[CanaryObservation, ...]]:
    adapter = NicovideoMangaAdapter()
    work = adapter.normalize(contract.seed_url)
    latest = adapter.fetch_latest(work, http_client)
    comic_id = str(work.metadata.get("comicId") or "")
    latest_page_url = canonical_nicovideo_manga_latest_url(comic_id)
    if not latest.episode_title:
        raise SourceParseError("nicovideo-manga: latest episode title not found")

    return (
        (latest_page_url, latest.url),
        (
            CanaryObservation("canonical_seed_url", work.seed_url),
            CanaryObservation("latest_episode_url", latest.url),
            CanaryObservation("latest_episode_title", latest.episode_title),
        ),
    )


def _gaugau_canary(
    contract: SourceCanaryContract,
    http_client: HttpClient,
) -> Tuple[Tuple[str, ...], Tuple[CanaryObservation, ...]]:
    adapter = GaugauAdapter()
    work = adapter.normalize(contract.seed_url)
    latest = adapter.fetch_latest(work, http_client)
    if not latest.episode_title:
        raise SourceParseError("gaugau: latest episode title not found")

    return (
        (work.seed_url, latest.url),
        (
            CanaryObservation("canonical_seed_url", work.seed_url),
            CanaryObservation("latest_episode_url", latest.url),
            CanaryObservation("latest_episode_title", latest.episode_title),
        ),
    )


CANARY_RUNNERS = {
    "comic-walker": _comic_walker_canary,
    "comic-action": _comic_action_canary,
    "comic-earthstar": _comic_earthstar_canary,
    "comicborder": _comicborder_canary,
    "comic-trail": _comic_trail_canary,
    "kuragebunch": _kuragebunch_canary,
    "shonenjumpplus": _shonenjumpplus_canary,
    "sunday-webry": _sunday_webry_canary,
    "champion-cross": _champion_cross_canary,
    "magapoke": _magapoke_canary,
    "firecross": _firecross_canary,
    "kakuyomu": _kakuyomu_canary,
    "nicovideo-manga": _nicovideo_manga_canary,
    "gaugau": _gaugau_canary,
    "takecomic": _takecomic_canary,
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
