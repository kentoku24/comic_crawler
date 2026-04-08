#!/usr/bin/env python3
import json
from dataclasses import dataclass
from typing import Dict, Optional, Sequence
from urllib.parse import urlparse

from manga_watch.check import build_watchlist_entry
from manga_watch.sources import HttpClient, SourceAdapter
from manga_watch.storage import get_watchlist_path, load_watchlist, save_watchlist


@dataclass(frozen=True)
class SourceCapability:
    source: str
    domains: Sequence[str]
    input_labels: Sequence[str]
    examples: Sequence[str]


SOURCE_CAPABILITIES = (
    SourceCapability(
        source="comic-walker",
        domains=("comic-walker.com",),
        input_labels=("canonical series URL", "episode URL"),
        examples=(
            "https://comic-walker.com/detail/KC_123456_S",
            "https://comic-walker.com/detail/KC_123456_S/episodes/KC_123456001_E",
        ),
    ),
    SourceCapability(
        source="comic-action",
        domains=("comic-action.com",),
        input_labels=("episode URL", "series feed URL"),
        examples=(
            "https://comic-action.com/episode/123456",
            "https://comic-action.com/rss/series/123456",
        ),
    ),
    SourceCapability(
        source="comicborder",
        domains=("comicborder.com",),
        input_labels=("episode URL", "series RSS URL", "series Atom URL"),
        examples=(
            "https://comicborder.com/episode/12207421983437812169",
            "https://comicborder.com/rss/series/12207421983437805229",
            "https://comicborder.com/atom/series/12207421983437805229",
        ),
    ),
    SourceCapability(
        source="kuragebunch",
        domains=("kuragebunch.com",),
        input_labels=("episode URL", "series RSS URL", "series Atom URL"),
        examples=(
            "https://kuragebunch.com/episode/2550912964856491139",
            "https://kuragebunch.com/rss/series/2550912964856487532",
            "https://kuragebunch.com/atom/series/2550912964856487532",
        ),
    ),
    SourceCapability(
        source="shonenjumpplus",
        domains=("shonenjumpplus.com",),
        input_labels=("episode URL", "series RSS URL", "series Atom URL"),
        examples=(
            "https://shonenjumpplus.com/episode/17107419589191805801",
            "https://shonenjumpplus.com/rss/series/3269754496881854342",
            "https://shonenjumpplus.com/atom/series/3269754496881854342",
        ),
    ),
    SourceCapability(
        source="sunday-webry",
        domains=("sunday-webry.com", "www.sunday-webry.com"),
        input_labels=("episode URL", "series RSS URL", "series Atom URL"),
        examples=(
            "https://www.sunday-webry.com/episode/12207421983581042977",
            "https://www.sunday-webry.com/rss/series/12207421983580960894",
            "https://www.sunday-webry.com/atom/series/12207421983580960894",
        ),
    ),
    SourceCapability(
        source="champion-cross",
        domains=("championcross.jp",),
        input_labels=("episode URL", "series URL", "series RSS URL"),
        examples=(
            "https://championcross.jp/episodes/0123456789ab",
            "https://championcross.jp/series/0123456789ab",
            "https://championcross.jp/series/0123456789ab/rss",
        ),
    ),
    SourceCapability(
        source="magapoke",
        domains=("pocket.shonenmagazine.com",),
        input_labels=("title URL", "episode URL"),
        examples=(
            "https://pocket.shonenmagazine.com/title/03021",
            "https://pocket.shonenmagazine.com/title/03021/episode/427856",
        ),
    ),
    SourceCapability(
        source="firecross",
        domains=("firecross.jp",),
        input_labels=("reader URL", "ebook series URL"),
        examples=(
            "https://firecross.jp/reader/19386",
            "https://firecross.jp/ebook/series/358",
        ),
    ),
    SourceCapability(
        source="takecomic",
        domains=("takecomic.jp",),
        input_labels=("episode URL", "series URL", "series RSS URL"),
        examples=(
            "https://takecomic.jp/episodes/0123456789ab",
            "https://takecomic.jp/series/0123456789ab",
            "https://takecomic.jp/series/0123456789ab/rss",
        ),
    ),
    SourceCapability(
        source="kakuyomu",
        domains=("kakuyomu.jp",),
        input_labels=("work URL", "episode URL"),
        examples=(
            "https://kakuyomu.jp/works/12345678901234567890",
            "https://kakuyomu.jp/works/12345678901234567890/episodes/12345678901234567891",
        ),
    ),
    SourceCapability(
        source="nicovideo-manga",
        domains=("manga.nicovideo.jp",),
        input_labels=("comic URL",),
        examples=(
            "https://manga.nicovideo.jp/comic/53764",
            "https://sp.manga.nicovideo.jp/comic/53764",
        ),
    ),
)


class WatchlistAddError(RuntimeError):
    def __init__(self, kind: str, message: str, next_action: str):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.next_action = next_action

    def to_dict(self) -> Dict[str, str]:
        return {
            "kind": self.kind,
            "message": self.message,
            "next_action": self.next_action,
        }


def add_watchlist_url(
    url: str,
    *,
    watchlist_path: Optional[str] = None,
    adapters: Optional[Sequence[SourceAdapter]] = None,
    http_client: Optional[HttpClient] = None,
) -> Dict[str, object]:
    target_path = watchlist_path or get_watchlist_path()
    normalized_input = normalize_input_url(url)
    entry = build_watchlist_preview(
        normalized_input,
        adapters=adapters,
        http_client=http_client,
    )
    try:
        watchlist = load_watchlist(target_path)
    except Exception as exc:
        raise WatchlistAddError(
            "load_watchlist",
            f"Failed to load watchlist: {exc}",
            "Fix the watchlist path or JSON payload, then retry the work registration flow.",
        ) from exc

    existing = find_duplicate_entry(watchlist["works"], str(entry["id"]))
    if existing is not None:
        return {
            "action": "duplicate",
            "input_url": normalized_input,
            "watchlist_path": target_path,
            "entry": entry,
            "existing": existing,
            "work_count": len(watchlist["works"]),
        }

    works = list(watchlist["works"])
    works.append(entry)
    updated_watchlist = {"version": watchlist["version"], "works": works}
    try:
        save_watchlist(updated_watchlist, path=target_path)
    except Exception as exc:
        raise WatchlistAddError(
            "save_watchlist",
            f"Failed to save watchlist: {exc}",
            "Check write permissions and disk state, then retry the work registration flow.",
        ) from exc

    return {
        "action": "added",
        "input_url": normalized_input,
        "watchlist_path": target_path,
        "entry": entry,
        "work_count": len(works),
    }


def build_watchlist_preview(
    url: str,
    *,
    adapters: Optional[Sequence[SourceAdapter]] = None,
    http_client: Optional[HttpClient] = None,
) -> Dict[str, object]:
    capability = capability_for_url(url)
    if capability is None:
        host = urlparse(url).netloc
        raise WatchlistAddError(
            "unsupported_source",
            f"Unsupported source host: {host}",
            (
                "Use one of the supported sources: "
                + ", ".join(sorted(capability.source for capability in SOURCE_CAPABILITIES))
                + "."
            ),
        )

    try:
        return build_watchlist_entry(url, adapters=adapters, http_client=http_client)
    except Exception as exc:
        message = str(exc)
        if message.startswith("Unsupported URL:") or "could not parse" in message:
            raise WatchlistAddError(
                "unsupported_url_type",
                f"{capability.source} does not support this URL type for work registration: {url}",
                capability_hint(capability),
            ) from exc
        raise WatchlistAddError(
            "normalize_failed",
            f"Failed to normalize {capability.source} URL: {message}",
            capability_hint(capability),
        ) from exc


def normalize_input_url(url: str) -> str:
    normalized = str(url or "").strip()
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WatchlistAddError(
            "invalid_url",
            f"Input must be an absolute http(s) URL: {url!r}",
            "Pass a full URL such as `https://kakuyomu.jp/works/<work_id>`.",
        )
    return normalized


def capability_for_url(url: str) -> Optional[SourceCapability]:
    host = urlparse(url).netloc.lower()
    for capability in SOURCE_CAPABILITIES:
        for domain in capability.domains:
            if host == domain or host.endswith(f".{domain}"):
                return capability
    return None


def capability_hint(capability: SourceCapability) -> str:
    labels = ", ".join(capability.input_labels)
    examples = " / ".join(capability.examples)
    return f"Supported input types for {capability.source}: {labels}. Examples: {examples}"


def find_duplicate_entry(works, work_id: str) -> Optional[Dict[str, object]]:
    for entry in works:
        if str(entry.get("id")) == work_id:
            return dict(entry)
    return None


def retired_cli_payload() -> Dict[str, object]:
    error = WatchlistAddError(
        "deprecated_cli",
        "`python -m manga_watch.watchlist add ...` has been retired.",
        "Use Discord `/add url:<作品URL>` for work registration.",
    )
    return {
        "action": "error",
        "input_url": "",
        "watchlist_path": get_watchlist_path(),
        "error": error.to_dict(),
    }


def main(argv=None) -> int:
    del argv
    print(json.dumps(retired_cli_payload(), ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
