#!/usr/bin/env python3
import argparse
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
        source="kakuyomu",
        domains=("kakuyomu.jp",),
        input_labels=("work URL", "episode URL"),
        examples=(
            "https://kakuyomu.jp/works/12345678901234567890",
            "https://kakuyomu.jp/works/12345678901234567890/episodes/12345678901234567891",
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


class WatchlistArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise WatchlistAddError(
            "usage",
            message,
            "Run `python3 -m manga_watch.watchlist add <url> [--watchlist <path>]`.",
        )


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
            "Fix the watchlist path or JSON payload, then rerun `watchlist add`.",
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
            "Check write permissions and disk state, then rerun `watchlist add`.",
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
                f"{capability.source} does not support this URL type for `watchlist add`: {url}",
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


def parse_args(argv=None):
    parser = WatchlistArgumentParser(description="Manage comic_crawler watchlist v2.")
    subparsers = parser.add_subparsers(dest="command")

    add_parser = subparsers.add_parser("add", help="Normalize a URL and add it to watchlist v2.")
    add_parser.add_argument("url")
    add_parser.add_argument("--watchlist", dest="watchlist_path")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = None
    try:
        args = parse_args(argv)
        if args.command != "add":
            raise WatchlistAddError(
                "usage",
                "missing command",
                "Run `python3 -m manga_watch.watchlist add <url> [--watchlist <path>]`.",
            )
        payload = add_watchlist_url(args.url, watchlist_path=args.watchlist_path)
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except WatchlistAddError as exc:
        payload = {
            "action": "error",
            "input_url": str(getattr(args, "url", "") or "").strip(),
            "watchlist_path": getattr(args, "watchlist_path", None) or get_watchlist_path(),
            "error": exc.to_dict(),
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
