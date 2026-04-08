from typing import Optional, Sequence, Tuple

from .base import HttpClient, LatestEpisode, RequestsHttpClient, SourceAdapter, WorkDescriptor
from .champion_cross import ChampionCrossAdapter
from .comic_action import ComicActionAdapter
from .comic_earthstar import ComicEarthstarAdapter
from .comicborder import ComicBorderAdapter
from .comic_trail import ComicTrailAdapter
from .comic_walker import ComicWalkerAdapter
from .firecross import FirecrossAdapter
from .kakuyomu import KakuyomuAdapter
from .kuragebunch import KuragebunchAdapter
from .magapoke import MagapokeAdapter
from .nicovideo_manga import NicovideoMangaAdapter
from .shonenjumpplus import ShonenJumpPlusAdapter
from .takecomic import TakecomicAdapter

# Explicit runtime registration contract for every supported source adapter.
REGISTERED_ADAPTERS = (
    ComicWalkerAdapter(),
    ComicActionAdapter(),
    ComicEarthstarAdapter(),
    ComicBorderAdapter(),
    ComicTrailAdapter(),
    KuragebunchAdapter(),
    ShonenJumpPlusAdapter(),
    ChampionCrossAdapter(),
    MagapokeAdapter(),
    FirecrossAdapter(),
    TakecomicAdapter(),
    NicovideoMangaAdapter(),
    KakuyomuAdapter(),
)
REGISTERED_SOURCES = tuple(adapter.source for adapter in REGISTERED_ADAPTERS)

# Backward-compatible alias for existing call sites.
DEFAULT_ADAPTERS = REGISTERED_ADAPTERS


def registered_sources(adapters: Sequence[SourceAdapter] = REGISTERED_ADAPTERS) -> Tuple[str, ...]:
    return tuple(adapter.source for adapter in adapters)


def find_adapter_for_url(seed_url: str, adapters: Sequence[SourceAdapter] = REGISTERED_ADAPTERS) -> SourceAdapter:
    for adapter in adapters:
        if adapter.can_handle(seed_url):
            return adapter
    raise RuntimeError(f"Unsupported URL: {seed_url}")


def find_adapter_for_source(source: str, adapters: Sequence[SourceAdapter] = REGISTERED_ADAPTERS) -> SourceAdapter:
    for adapter in adapters:
        if adapter.source == source:
            return adapter
    raise RuntimeError(f"Unknown source: {source}")


def normalize_seed_url(seed_url: str, adapters: Sequence[SourceAdapter] = REGISTERED_ADAPTERS) -> WorkDescriptor:
    return find_adapter_for_url(seed_url, adapters=adapters).normalize(seed_url)


def fetch_latest_for_work(
    work: WorkDescriptor,
    *,
    adapters: Sequence[SourceAdapter] = REGISTERED_ADAPTERS,
    http_client: Optional[HttpClient] = None,
) -> LatestEpisode:
    adapter = find_adapter_for_source(work.source, adapters=adapters)
    client = http_client or RequestsHttpClient()
    return adapter.fetch_latest(work, client)
