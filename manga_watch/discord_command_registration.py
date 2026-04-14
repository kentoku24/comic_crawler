from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Protocol

import requests

from manga_watch.discord_add import ADD_COMMAND
from manga_watch.discord_fetch import FETCH_COMMAND
from manga_watch.discord_latest import LATEST_COMMAND
from manga_watch.discord_search import SEARCH_COMMAND
from manga_watch.source_search import searchable_source_choices
from manga_watch.discord_remove import REMOVE_COMMAND
from manga_watch.discord_supertwins_manage import SUPERTWINS_MANAGE_COMMAND
from manga_watch.discord_supertwins_search import SUPERTWINS_SEARCH_COMMAND
from manga_watch.secret_redaction import redact_secret_text
from manga_watch.secret_resolver import resolve_env_value

DEFAULT_API_BASE_URL = "https://discord.com/api/v10"


class RequestsSession(Protocol):
    def get(self, url: str, **kwargs): ...

    def put(self, url: str, **kwargs): ...


def _coerce_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def default_interaction_commands() -> List[Dict[str, object]]:
    return [
        {
            "name": LATEST_COMMAND,
            "description": "保存済みの最新話一覧を表示します。",
        },
        {
            "name": FETCH_COMMAND,
            "description": "手動で巡回を開始します。",
        },
        {
            "name": ADD_COMMAND,
            "description": "作品URLを追加してクロール対象に登録します。",
            "options": [
                {
                    "type": 3,
                    "name": "url",
                    "description": "追加したい作品URL",
                    "required": True,
                }
            ],
        },
        {
            "name": SEARCH_COMMAND,
            "description": "媒体ごとに作品名で検索します。",
            "options": [
                {
                    "type": 3,
                    "name": "source",
                    "description": "検索したい媒体",
                    "required": True,
                    "choices": searchable_source_choices(),
                },
                {
                    "type": 3,
                    "name": "query",
                    "description": "検索したい文字列",
                    "required": True,
                },
                {
                    "type": 3,
                    "name": "visibility",
                    "description": "watchlist に追加するときの表示状態",
                    "required": False,
                    "choices": [
                        {"name": "visible", "value": "visible"},
                        {"name": "hidden", "value": "hidden"},
                    ],
                },
            ],
        },
        {
            "name": REMOVE_COMMAND,
            "description": "購読中の作品を削除します。",
        },
        {
            "name": SUPERTWINS_SEARCH_COMMAND,
            "description": "既存作品を起点に他媒体候補を探して supertwins を作成します。",
        },
        {
            "name": SUPERTWINS_MANAGE_COMMAND,
            "description": "既存の supertwins を確認して誤登録を解除します。",
        },
    ]


def resolve_bot_config(
    *,
    environ: Optional[Dict[str, str]] = None,
    api_base_url: str = DEFAULT_API_BASE_URL,
    session: RequestsSession = requests,
) -> tuple[str, str]:
    resolved_environ = os.environ.copy() if environ is None else environ
    bot_token = resolve_env_value("DISCORD_BOT_TOKEN", environ=resolved_environ)
    if not bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN or DISCORD_BOT_TOKEN_SECRET_VERSION is required")

    application_id = _coerce_text(resolved_environ.get("DISCORD_APPLICATION_ID"))
    if application_id:
        return bot_token, application_id

    response = session.get(
        f"{api_base_url}/oauth2/applications/@me",
        headers={"Authorization": f"Bot {bot_token}"},
        timeout=10,
        allow_redirects=False,
    )
    if not 200 <= response.status_code < 300:
        raise RuntimeError(
            f"failed to resolve application_id: HTTP {response.status_code}: "
            f"{redact_secret_text(response.text.strip(), secrets=(bot_token,))[:300]}"
        )

    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Discord application response format is invalid")

    resolved_application_id = _coerce_text(payload.get("id"))
    if not resolved_application_id:
        raise RuntimeError("Discord application response does not contain id")
    return bot_token, resolved_application_id


def register_commands(
    *,
    bot_token: str,
    application_id: str,
    commands: List[Dict[str, str]],
    guild_id: Optional[str] = None,
    api_base_url: str = DEFAULT_API_BASE_URL,
    dry_run: bool = False,
    session: RequestsSession = requests,
) -> List[Dict[str, object]]:
    target = f"{api_base_url}/applications/{application_id}/commands"
    if guild_id:
        target = f"{api_base_url}/applications/{application_id}/guilds/{guild_id}/commands"

    if dry_run:
        return list(commands)

    response = session.put(
        target,
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
        },
        json=commands,
        timeout=15,
        allow_redirects=False,
    )
    if not 200 <= response.status_code < 300:
        detail = redact_secret_text(response.text.strip().replace("\n", " "), secrets=(bot_token,))
        raise RuntimeError(f"Discord command registration failed ({response.status_code}): {detail[:300]}")

    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("Discord returned unexpected command registration response")
    return payload


def ensure_commands_registered_from_env(
    *,
    environ: Optional[Dict[str, str]] = None,
    session: RequestsSession = requests,
    dry_run: bool = False,
) -> List[Dict[str, object]]:
    resolved_environ = os.environ.copy() if environ is None else environ
    resolved_guild_id = _coerce_text(resolved_environ.get("DISCORD_GUILD_ID"))
    api_base_url = (_coerce_text(resolved_environ.get("DISCORD_API_BASE_URL")) or DEFAULT_API_BASE_URL).rstrip("/")
    bot_token, application_id = resolve_bot_config(
        environ=resolved_environ,
        api_base_url=api_base_url,
        session=session,
    )
    return register_commands(
        bot_token=bot_token,
        application_id=application_id,
        commands=default_interaction_commands(),
        guild_id=resolved_guild_id,
        api_base_url=api_base_url,
        dry_run=dry_run,
        session=session,
    )
