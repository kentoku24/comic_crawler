from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Protocol, Sequence

from manga_watch.discord_fetch import handle_fetch_trigger
from manga_watch.discord_latest import handle_latest_query

DEFAULT_COMMAND_POLL_INTERVAL = 5.0
DISCORD_MESSAGE_LIMIT = 2000
COMMAND_LISTENER_THREAD_NAME = "manga-watch-discord-inbound"


class DiscordCommandTransport(Protocol):
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


def parse_poll_interval(value: Optional[str], *, default: float = DEFAULT_COMMAND_POLL_INTERVAL) -> float:
    if value is None:
        return default
    interval = float(str(value).strip())
    if interval <= 0:
        raise ValueError("DISCORD_COMMAND_POLL_INTERVAL must be a positive number (seconds)")
    return interval


def _snowflake_sort_key(message_id: str) -> tuple[int, object]:
    if message_id.isdigit():
        return (0, int(message_id))
    return (1, message_id)


def _message_id(message: Mapping[str, object]) -> Optional[str]:
    message_id = str(message.get("id") or "").strip()
    return message_id or None


def _message_content(message: Mapping[str, object]) -> str:
    return str(message.get("content") or "")


def _message_author_id(message: Mapping[str, object]) -> Optional[str]:
    author = message.get("author", {})
    if not isinstance(author, Mapping):
        return None
    author_id = str(author.get("id") or "").strip()
    return author_id or None


def _message_from_bot(message: Mapping[str, object]) -> bool:
    author = message.get("author", {})
    if not isinstance(author, Mapping):
        return False
    return bool(author.get("bot"))


def split_discord_message(content: object, *, limit: int = DISCORD_MESSAGE_LIMIT) -> List[str]:
    text = str(content or "")
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    current = ""
    for line in text.splitlines():
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        remaining = line
        while len(remaining) > limit:
            chunks.append(remaining[:limit])
            remaining = remaining[limit:]
        current = remaining

    if current:
        chunks.append(current)
    return chunks or [text[:limit]]


@dataclass
class DiscordCommandListener:
    client: DiscordCommandTransport
    channel_id: str
    coordinator: object
    timezone_name: str
    watchlist_path: Optional[str] = None
    state_path: Optional[str] = None
    poll_interval_seconds: float = DEFAULT_COMMAND_POLL_INTERVAL
    latest_handler: Callable[..., Optional[str]] = handle_latest_query
    fetch_handler: Callable[..., Optional[Dict[str, object]]] = handle_fetch_trigger
    report_logger: Callable[[str], None] = print
    error_logger: Callable[[str], None] = print
    sleep_fn: Callable[[float], None] = time.sleep
    thread_factory: Callable[..., threading.Thread] = threading.Thread
    _bot_user_id: Optional[str] = field(default=None, init=False, repr=False)
    _last_seen_message_id: Optional[str] = field(default=None, init=False, repr=False)
    _cursor_primed: bool = field(default=False, init=False, repr=False)

    def _prime_cursor(self) -> None:
        if self._bot_user_id is None:
            self._bot_user_id = self.client.get_current_user_id()

        if self._cursor_primed:
            return

        messages = self.client.list_channel_messages(self.channel_id, limit=1)
        newest = None
        for message in messages:
            if not isinstance(message, Mapping):
                continue
            message_id = _message_id(message)
            if message_id is None:
                continue
            if newest is None or _snowflake_sort_key(message_id) > _snowflake_sort_key(newest):
                newest = message_id
        self._last_seen_message_id = newest
        self._cursor_primed = True

    def _should_ignore_message(self, message: Mapping[str, object]) -> bool:
        author_id = _message_author_id(message)
        if author_id is None:
            return True
        if author_id == self._bot_user_id:
            return True
        return _message_from_bot(message)

    def _send_response(self, content: str) -> None:
        for chunk in split_discord_message(content):
            if chunk:
                self.client.send_message(self.channel_id, chunk)

    def _handle_message(self, message: Mapping[str, object]) -> Optional[str]:
        if self._should_ignore_message(message):
            return None

        content = _message_content(message)
        latest_response = self.latest_handler(
            content,
            watchlist_path=self.watchlist_path,
            state_path=self.state_path,
            timezone_name=self.timezone_name,
        )
        if latest_response is not None:
            self._send_response(latest_response)
            return latest_response

        fetch_response = self.fetch_handler(content, coordinator=self.coordinator)
        if fetch_response is None:
            return None

        response_message = str(fetch_response.get("message") or "").strip()
        if response_message:
            self._send_response(response_message)
        return response_message or ""

    def poll_once(self) -> List[str]:
        if not self._cursor_primed:
            self._prime_cursor()
            return []
        messages = self.client.list_channel_messages(
            self.channel_id,
            after=self._last_seen_message_id,
            limit=100,
        )
        ordered_messages: List[Mapping[str, object]] = []
        for message in messages:
            if not isinstance(message, Mapping):
                continue
            message_id = _message_id(message)
            if message_id is None:
                continue
            ordered_messages.append(message)

        ordered_messages.sort(key=lambda message: _snowflake_sort_key(_message_id(message) or ""))

        responses: List[str] = []
        for message in ordered_messages:
            message_id = _message_id(message)
            if message_id is not None:
                self._last_seen_message_id = message_id
            response = self._handle_message(message)
            if response:
                responses.append(response)
        return responses

    def poll_forever(self) -> None:
        self.report_logger(
            f"[discord] command listener started: channel={self.channel_id} "
            f"interval={self.poll_interval_seconds:g}s"
        )
        while True:
            try:
                self.poll_once()
            except Exception as exc:
                self.error_logger(f"[discord] command listener error: {exc}")
            self.sleep_fn(self.poll_interval_seconds)

    def start_background(self) -> threading.Thread:
        thread = self.thread_factory(
            target=self.poll_forever,
            daemon=True,
            name=COMMAND_LISTENER_THREAD_NAME,
        )
        thread.start()
        return thread


def inbound_enabled_from_env() -> bool:
    return str(os.environ.get("DISCORD_INBOUND_ENABLED", "true")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
