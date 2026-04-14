from .base import HttpClient, LatestEpisode, RequestsHttpClient, SourceAdapter, WorkDescriptor
from .nicovideo_manga import NicovideoMangaAdapter
from .registry import (
    DEFAULT_ADAPTERS,
    REGISTERED_ADAPTERS,
    REGISTERED_SOURCES,
    fetch_latest_for_work,
    normalize_seed_url,
    registered_sources,
)

__all__ = [
    "DEFAULT_ADAPTERS",
    "HttpClient",
    "LatestEpisode",
    "REGISTERED_ADAPTERS",
    "REGISTERED_SOURCES",
    "RequestsHttpClient",
    "NicovideoMangaAdapter",
    "SourceAdapter",
    "WorkDescriptor",
    "fetch_latest_for_work",
    "normalize_seed_url",
    "registered_sources",
]
