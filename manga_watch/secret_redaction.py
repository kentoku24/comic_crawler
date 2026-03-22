from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

REDACTED_SECRET = "[REDACTED_SECRET]"
REDACTED_WEBHOOK_URL = "[REDACTED_WEBHOOK_URL]"
REDACTED_BOT_TOKEN = "[REDACTED_BOT_TOKEN]"

_BOT_TOKEN_RE = re.compile(r"(Bot\s+)([^\s'\"<>]+)")
_DISCORD_WEBHOOK_RE = re.compile(
    r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/[^\s'\"<>]+"
)


def _coerce_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _flatten_secret_values(values: Sequence[object]) -> Iterable[str]:
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set, frozenset)):
            yield from _flatten_secret_values(tuple(value))
            continue
        text = _coerce_text(value)
        if text:
            yield text


def collect_secret_values(*values: object) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for secret in _flatten_secret_values(values):
        if secret in seen:
            continue
        seen.add(secret)
        ordered.append(secret)
    ordered.sort(key=len, reverse=True)
    return tuple(ordered)


def _placeholder_for_secret(secret: str) -> str:
    if _DISCORD_WEBHOOK_RE.fullmatch(secret):
        return REDACTED_WEBHOOK_URL
    return REDACTED_SECRET


def redact_secret_text(value: object, *, secrets: Sequence[object] = ()) -> str:
    text = str(value)
    redacted = _DISCORD_WEBHOOK_RE.sub(REDACTED_WEBHOOK_URL, text)
    redacted = _BOT_TOKEN_RE.sub(rf"\1{REDACTED_BOT_TOKEN}", redacted)
    for secret in collect_secret_values(secrets):
        redacted = redacted.replace(secret, _placeholder_for_secret(secret))
    return redacted
