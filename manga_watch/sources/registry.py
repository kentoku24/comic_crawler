from typing import Optional, Sequence, Tuple, Type

from .base import HttpClient, LatestEpisode, RequestsHttpClient, SourceAdapter, WorkDescriptor
from .comic_action import ComicActionAdapter
from .comic_walker import ComicWalkerAdapter
from .kakuyomu import KakuyomuAdapter

# Single source of truth for supported adapters. Add new adapter classes here.
REGISTERED_ADAPTER_TYPES: Tuple[Type[SourceAdapter], ...] = (
    ComicWalkerAdapter,
    ComicActionAdapter,
    KakuyomuAdapter,
)

DEFAULT_ADAPTERS: Tuple[SourceAdapter, ...] = tuple(
    adapter_type() for adapter_type in REGISTERED_ADAPTER_TYPES
)


def find_adapter_for_url(seed_url: str, adapters: Sequence[SourceAdapter] = DEFAULT_ADAPTERS) -> SourceAdapter:
    for adapter in adapters:
        if adapter.can_handle(seed_url):
            return adapter
    raise RuntimeError(f"Unsupported URL: {seed_url}")


def find_adapter_for_source(source: str, adapters: Sequence[SourceAdapter] = DEFAULT_ADAPTERS) -> SourceAdapter:
    for adapter in adapters:
        if adapter.source == source:
            return adapter
    raise RuntimeError(f"Unknown source: {source}")


def normalize_seed_url(seed_url: str, adapters: Sequence[SourceAdapter] = DEFAULT_ADAPTERS) -> WorkDescriptor:
    return find_adapter_for_url(seed_url, adapters=adapters).normalize(seed_url)


def fetch_latest_for_work(
    work: WorkDescriptor,
    *,
    adapters: Sequence[SourceAdapter] = DEFAULT_ADAPTERS,
    http_client: Optional[HttpClient] = None,
) -> LatestEpisode:
    adapter = find_adapter_for_source(work.source, adapters=adapters)
    client = http_client or RequestsHttpClient()
    return adapter.fetch_latest(work, client)
