#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

import requests

from manga_watch.discord_fetch import FETCH_COMMAND
from manga_watch.discord_latest import LATEST_COMMAND
from manga_watch.secret_redaction import redact_secret_text
from manga_watch.secret_resolver import resolve_env_value

ADD_COMMAND = "add"
DEFAULT_INTERACTION_COMMANDS: List[Dict[str, Any]] = [
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
]
DEFAULT_API_BASE_URL = "https://discord.com/api/v10"


def _coerce_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def resolve_bot_config(*, environ: Optional[Dict[str, str]] = None) -> tuple[str, str]:
    resolved_environ = os.environ if environ is None else environ
    bot_token = resolve_env_value("DISCORD_BOT_TOKEN", environ=resolved_environ)
    if not bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN or DISCORD_BOT_TOKEN_SECRET_VERSION is required")

    application_id = _coerce_text(resolved_environ.get("DISCORD_APPLICATION_ID"))
    if application_id:
        return bot_token, application_id

    response = requests.get(
        f"{DEFAULT_API_BASE_URL}/oauth2/applications/@me",
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
    commands: List[Dict[str, Any]],
    guild_id: Optional[str] = None,
    api_base_url: str = DEFAULT_API_BASE_URL,
    dry_run: bool = False,
) -> List[Dict[str, object]]:
    target = f"{api_base_url}/applications/{application_id}/commands"
    if guild_id:
        target = f"{api_base_url}/applications/{application_id}/guilds/{guild_id}/commands"

    if dry_run:
        return commands

    response = requests.put(
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register Discord slash commands for manga_crawler.")
    parser.add_argument("--guild-id", default=None, help="Guild id for guild-scoped commands (faster propagation)")
    parser.add_argument(
        "--application-id",
        default=None,
        help="Discord application id. When omitted, resolves from bot token via /oauth2/applications/@me",
    )
    parser.add_argument(
        "--api-base-url",
        default=DEFAULT_API_BASE_URL,
        help="Discord API base URL",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show planned registration payload only")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        resolved_guild_id = (
            _coerce_text(args.guild_id) or _coerce_text(os.environ.get("DISCORD_GUILD_ID"))
        )
        api_base_url = args.api_base_url.rstrip("/")
        bot_token, application_id = resolve_bot_config(environ=os.environ.copy())
        if args.application_id:
            application_id = args.application_id.strip()
            if not application_id:
                raise ValueError("application-id is required when provided")

        response = register_commands(
            bot_token=bot_token,
            application_id=application_id,
            commands=DEFAULT_INTERACTION_COMMANDS,
            guild_id=resolved_guild_id,
            api_base_url=api_base_url,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"[register-discord-commands] error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
