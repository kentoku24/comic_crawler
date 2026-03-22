from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Callable, Dict, List, Mapping, Optional, Protocol, Sequence

from manga_watch.discord_latest import build_latest_query_response
from manga_watch.discord_outbound import (
    DEFAULT_TIMEZONE,
    DiscordChannelClient,
    DiscordOutboundConfig,
    build_daily_notification_message,
    build_run_report_message,
)

DEFAULT_E2E_TIMEOUT_SECONDS = 20.0
DEFAULT_E2E_POLL_INTERVAL_SECONDS = 1.0


class DiscordReadWriteTransport(Protocol):
    def get_current_user_id(self) -> str:
        ...

    def list_channel_messages(
        self,
        channel_id: str,
        *,
        after: Optional[str] = None,
        limit: int = 50,
    ) -> Sequence[Mapping[str, object]]:
        ...

    def send_message(self, channel_id: str, content: str) -> None:
        ...


@dataclass(frozen=True)
class DiscordE2ECase:
    name: str
    channel_id: str
    description: str
    content: str


@dataclass(frozen=True)
class DiscordE2EResult:
    name: str
    channel_id: str
    message_id: str
    content_matches: bool
    mentions_ok: bool


def _message_id(message: Mapping[str, object]) -> Optional[str]:
    value = str(message.get("id") or "").strip()
    return value or None


def _message_author_id(message: Mapping[str, object]) -> Optional[str]:
    author = message.get("author", {})
    if not isinstance(author, Mapping):
        return None
    value = str(author.get("id") or "").strip()
    return value or None


def _snowflake_sort_key(message_id: str) -> tuple[int, object]:
    if message_id.isdigit():
        return (0, int(message_id))
    return (1, message_id)


def _newest_message_id(messages: Sequence[Mapping[str, object]]) -> Optional[str]:
    newest: Optional[str] = None
    for message in messages:
        message_id = _message_id(message)
        if message_id is None:
            continue
        if newest is None or _snowflake_sort_key(message_id) > _snowflake_sort_key(newest):
            newest = message_id
    return newest


def build_representative_cases(
    config: DiscordOutboundConfig,
    *,
    timezone_name: Optional[str] = None,
) -> List[DiscordE2ECase]:
    timezone_name = timezone_name or os.environ.get("TZ", DEFAULT_TIMEZONE)
    return [
        DiscordE2ECase(
            name="latest",
            channel_id=config.main_channel_id,
            description="latest query rendered in the main test channel",
            content=build_latest_query_response(
                {
                    "version": 2,
                    "works": [
                        {
                            "id": "work-b",
                            "source": "comic-walker",
                            "seed_url": "https://example.com/work-b",
                            "enabled": True,
                            "notification_policy": {"mode": "all", "allowed_update_types": None},
                        },
                        {
                            "id": "work-a",
                            "source": "comic-walker",
                            "seed_url": "https://example.com/work-a",
                            "enabled": True,
                            "notification_policy": {"mode": "all", "allowed_update_types": None},
                        },
                    ],
                },
                {
                    "version": 2,
                    "works": {
                        "work-a": {
                            "latest": {
                                "series_title": "作品A",
                                "episode_title": "第71話 abcdefghijk",
                                "url": "https://example.com/a",
                            },
                            "history": [],
                            "health": {"last_checked_at": 1_700_000_000, "consecutive_failures": 1},
                        },
                        "work-b": {
                            "latest": {
                                "series_title": "作品B",
                                "episode_title": "第8話",
                                "url": "https://example.com/b",
                            },
                            "history": [],
                            "health": {"last_checked_at": 1_700_000_000, "consecutive_failures": 0},
                        },
                    },
                    "last_run_at": 1_700_000_000,
                    "notification_outbox": [],
                },
                timezone_name=timezone_name,
                now=1_700_000_600,
            ),
        ),
        DiscordE2ECase(
            name="daily",
            channel_id=config.main_channel_id,
            description="daily notification rendered in the main test channel",
            content=build_daily_notification_message(
                [
                    {
                        "id": "work-a",
                        "from": {
                            "seriesTitle": "作品A",
                            "episodeTitle": "第70話",
                            "latestKey": "episode-70",
                        },
                        "to": {
                            "series_title": "作品A",
                            "episode_title": "第71話 abcdefghijk",
                            "latest_key": "episode-71",
                            "url": "https://example.com/a",
                        },
                    },
                    {
                        "id": "work-b",
                        "from": {
                            "seriesTitle": "作品B",
                            "episodeTitle": "第7話",
                            "latestKey": "episode-7",
                        },
                        "to": {
                            "series_title": "作品B",
                            "episode_title": "第8話",
                            "latest_key": "episode-8",
                            "url": "https://example.com/b",
                        },
                    },
                ],
                now_ts=1_700_000_000,
                timezone_name=timezone_name,
            ),
        ),
        DiscordE2ECase(
            name="run-report",
            channel_id=config.run_report_channel_id,
            description="run report rendered in the run-report test channel",
            content=build_run_report_message(
                timestamp="2026-03-11 07:00:00 JST",
                trigger_source="discord_fetch",
                update_count=2,
                notified_update_count=2,
                suppressed_update_count=0,
                outbox_pending_count=0,
                daily_notification_sent=True,
                daily_notification_pending_count=0,
                errors={"sources": [], "run": []},
                delivery_failures=[],
                state_lines=[
                    "[第8話](<https://example.com/b>)　作品B",
                    "[第71話 abcdefg…](<https://example.com/a>)　作品A",
                ],
            ),
        ),
    ]


def select_cases(cases: Sequence[DiscordE2ECase], selection: str) -> List[DiscordE2ECase]:
    if selection == "all":
        return list(cases)
    for case in cases:
        if case.name == selection:
            return [case]
    raise ValueError(f"Unknown E2E case: {selection}")


def verify_message(case: DiscordE2ECase, message: Mapping[str, object]) -> DiscordE2EResult:
    actual_content = str(message.get("content") or "")
    if actual_content != case.content:
        raise RuntimeError(f"{case.name}: Discord returned unexpected content")

    if bool(message.get("mention_everyone")):
        raise RuntimeError(f"{case.name}: unexpected @everyone mention")

    mentions = message.get("mentions", [])
    if isinstance(mentions, Sequence) and not isinstance(mentions, (str, bytes)) and list(mentions):
        raise RuntimeError(f"{case.name}: unexpected user mention")

    mention_roles = message.get("mention_roles", [])
    if isinstance(mention_roles, Sequence) and not isinstance(mention_roles, (str, bytes)) and list(mention_roles):
        raise RuntimeError(f"{case.name}: unexpected role mention")

    message_id = _message_id(message)
    if message_id is None:
        raise RuntimeError(f"{case.name}: Discord message id was missing")

    return DiscordE2EResult(
        name=case.name,
        channel_id=case.channel_id,
        message_id=message_id,
        content_matches=True,
        mentions_ok=True,
    )


def _find_posted_message(
    client: DiscordReadWriteTransport,
    case: DiscordE2ECase,
    *,
    bot_user_id: str,
    newest_before_send: Optional[str],
) -> Optional[Mapping[str, object]]:
    messages = client.list_channel_messages(
        case.channel_id,
        after=newest_before_send,
        limit=50,
    )
    ordered = sorted(
        (message for message in messages if isinstance(message, Mapping)),
        key=lambda message: _snowflake_sort_key(_message_id(message) or ""),
    )
    for message in ordered:
        if _message_author_id(message) != bot_user_id:
            continue
        if str(message.get("content") or "") != case.content:
            continue
        return message
    return None


def run_case(
    client: DiscordReadWriteTransport,
    case: DiscordE2ECase,
    *,
    timeout_seconds: float = DEFAULT_E2E_TIMEOUT_SECONDS,
    poll_interval_seconds: float = DEFAULT_E2E_POLL_INTERVAL_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> DiscordE2EResult:
    bot_user_id = client.get_current_user_id()
    newest_before_send = _newest_message_id(client.list_channel_messages(case.channel_id, limit=10))
    client.send_message(case.channel_id, case.content)

    deadline = monotonic() + timeout_seconds
    while True:
        matched = _find_posted_message(
            client,
            case,
            bot_user_id=bot_user_id,
            newest_before_send=newest_before_send,
        )
        if matched is not None:
            return verify_message(case, matched)
        if monotonic() >= deadline:
            break
        sleep_fn(poll_interval_seconds)

    raise RuntimeError(f"{case.name}: timed out waiting for Discord echo in channel {case.channel_id}")


def run_cases(
    client: DiscordReadWriteTransport,
    cases: Sequence[DiscordE2ECase],
    *,
    timeout_seconds: float = DEFAULT_E2E_TIMEOUT_SECONDS,
    poll_interval_seconds: float = DEFAULT_E2E_POLL_INTERVAL_SECONDS,
) -> List[DiscordE2EResult]:
    return [
        run_case(
            client,
            case,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        for case in cases
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run auxiliary Discord real E2E checks against test channels.",
    )
    parser.add_argument(
        "--case",
        choices=("all", "latest", "daily", "run-report"),
        default="all",
        help="Which representative case to send and verify.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_E2E_TIMEOUT_SECONDS,
        help="Seconds to wait for Discord to echo the sent message.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_E2E_POLL_INTERVAL_SECONDS,
        help="Seconds between Discord read polls while waiting for the posted message.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print verification results as JSON.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = DiscordOutboundConfig.from_env()
    client = DiscordChannelClient(config)
    cases = select_cases(build_representative_cases(config), args.case)
    results = run_cases(
        client,
        cases,
        timeout_seconds=args.timeout,
        poll_interval_seconds=args.poll_interval,
    )

    if args.json:
        print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    else:
        for result in results:
            print(
                f"{result.name}: ok channel={result.channel_id} "
                f"message_id={result.message_id}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
