"""Shared base adapter for Hatena GigaViewer manga sites.

A large family of Japanese manga sites (Shonen Jump+, Kurage Bunch, Comic
Border, Comic Earthstar, Comic Trail, Sunday Webry, ... and Comic Days) run on
Hatena's GigaViewer platform. They expose the same processing shape:

* episode URLs look like ``/episode/{numeric-id}``,
* a per-series RSS/Atom feed lives at ``/rss|atom/series/{id}``,
* the series id is embedded in episode HTML as a ``"series_id"`` JSON key.

Historically every adapter re-implemented the identical ``can_handle`` /
``normalize`` / ``canonicalize_item`` / ``fetch_latest`` orchestration, differing
only by host name, title-cleanup rules and a couple of feed quirks. This base
class owns that orchestration once; concrete adapters supply the per-site pieces
as wired hooks (the module-level ``parse_*`` / ``extract_*`` functions that other
subsystems such as ``source_drift`` still import directly) plus two small config
flags.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import FrozenSet, Optional, Tuple

from .base import HttpClient, LatestEpisode, SourceAdapter, SourceParseError, WorkDescriptor
from .util import html_title


class GigaViewerAdapter(SourceAdapter):
    """Behaviour shared by every GigaViewer-family source adapter.

    Subclasses wire the per-site hooks below (declared abstract so a subclass
    that forgets one fails fast, and so this base stays abstract and is skipped
    by the registry-coverage discovery test). The hooks are normally the
    existing module-level functions, attached as ``staticmethod``::

        class ShonenJumpPlusAdapter(GigaViewerAdapter):
            source = "shonenjumpplus"
            parse_episode_url = staticmethod(parse_shonenjumpplus_episode_url)
            ...
    """

    #: Series titles that should be treated as missing and replaced by the
    #: title parsed from the episode page (e.g. a bare site name). Empty for
    #: most sites.
    generic_series_titles: FrozenSet[str] = frozenset()

    #: When True (Sunday Webry), reuse the page title already fetched from the
    #: seed episode page instead of re-fetching it, unless the feed's latest
    #: episode differs from the seed. Preserves the exact request sequence.
    reuse_episode_page_title: bool = False

    # --- per-site hooks (wired by subclasses) -------------------------------
    @staticmethod
    @abstractmethod
    def parse_episode_url(seed_url: str) -> Optional[str]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def parse_series_feed_url(seed_url: str) -> Optional[Tuple[str, str]]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def canonical_series_feed_url(series_id: str) -> str:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def extract_series_id_from_seed_url(seed_url: str) -> Optional[str]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def extract_series_id(html_text: str) -> Optional[str]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def extract_series_feed_url(html_text: str) -> Optional[str]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def parse_feed_latest(feed_text: str) -> Tuple[str, Optional[str], Optional[str]]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def parse_page_title(page_title: str) -> Tuple[Optional[str], Optional[str]]:
        raise NotImplementedError

    # --- shared orchestration ----------------------------------------------
    def can_handle(self, seed_url: str) -> bool:
        return bool(
            self.parse_episode_url(seed_url)
            or self.parse_series_feed_url(seed_url)
        )

    def normalize(self, seed_url: str) -> WorkDescriptor:
        normalized_episode_url = self.parse_episode_url(seed_url)
        if normalized_episode_url:
            return WorkDescriptor(
                source=self.source,
                work_id=normalized_episode_url,
                seed_url=normalized_episode_url,
            )

        feed_match = self.parse_series_feed_url(seed_url)
        if not feed_match:
            raise RuntimeError(f"{self.source}: unsupported seed URL: {seed_url}")

        _, series_id = feed_match
        stable_work_id = f"{self.source}:{series_id}"
        return WorkDescriptor(
            source=self.source,
            work_id=stable_work_id,
            seed_url=self.canonical_series_feed_url(series_id),
            metadata={
                "series": stable_work_id,
                "seriesId": series_id,
                "feedKind": "rss",
            },
        )

    def canonicalize_item(
        self,
        item,
        http_client: HttpClient,
    ) -> WorkDescriptor:
        seed_url = str(item.get("seedUrl") or "")
        series_id = str(item.get("seriesId") or "") or self.extract_series_id_from_seed_url(seed_url)
        if series_id:
            return self.normalize(self.canonical_series_feed_url(series_id))

        episode_url = self.parse_episode_url(seed_url)
        if not episode_url:
            raise RuntimeError(f"{self.source}: unsupported seed URL")

        episode_html = http_client.get_text(episode_url)
        feed_url = self.extract_series_feed_url(episode_html)
        if feed_url:
            return self.normalize(feed_url)

        series_id = self.extract_series_id(episode_html)
        if not series_id:
            raise RuntimeError(f"{self.source}: series id not found")
        return self.normalize(self.canonical_series_feed_url(series_id))

    def fetch_latest(self, work: WorkDescriptor, http_client: HttpClient) -> LatestEpisode:
        series = str(work.metadata.get("series") or work.work_id)
        series_id = str(work.metadata.get("seriesId") or "")
        episode_seed_url = None
        episode_page_title = None

        feed_match = self.parse_series_feed_url(work.seed_url)
        if feed_match:
            feed_url = self.canonical_series_feed_url(feed_match[1])
            series_id = series_id or feed_match[1]
        else:
            episode_url = self.parse_episode_url(work.seed_url)
            if not episode_url:
                raise RuntimeError(f"{self.source}: unsupported seed URL")
            episode_seed_url = episode_url
            episode_html = http_client.get_text(episode_url)
            if self.reuse_episode_page_title:
                episode_page_title = html_title(episode_html)
            feed_url = self.extract_series_feed_url(episode_html)
            series_id = series_id or self.extract_series_id(episode_html) or ""
            if not series_id:
                raise SourceParseError(f"{self.source}: series id not found")
            if not feed_url:
                raise SourceParseError(f"{self.source}: series feed URL not found")
            series = f"{self.source}:{series_id}"

        feed_text = http_client.get_text(feed_url)
        latest_url, episode_title, series_title = self.parse_feed_latest(feed_text)

        if self.reuse_episode_page_title:
            page_title = episode_page_title
            if episode_seed_url is not None and latest_url != episode_seed_url:
                page_title = html_title(http_client.get_text(latest_url))
            elif not page_title:
                page_title = html_title(http_client.get_text(latest_url))
        else:
            page_title = html_title(http_client.get_text(latest_url))

        parsed_episode_title, parsed_series_title = self.parse_page_title(page_title or "")
        if not episode_title:
            episode_title = parsed_episode_title
        if (not series_title or series_title in self.generic_series_titles) and parsed_series_title:
            series_title = parsed_series_title

        return LatestEpisode(
            source=self.source,
            work_id=work.work_id if work.work_id.startswith(f"{self.source}:") else series,
            latest_key=latest_url,
            url=latest_url,
            series=series,
            series_title=series_title,
            episode_title=episode_title,
            page_title=page_title,
        )
