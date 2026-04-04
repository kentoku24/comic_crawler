#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from manga_watch.discord_command_registration import DEFAULT_API_BASE_URL, ensure_commands_registered_from_env


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register Discord slash commands for manga_crawler.")
    parser.add_argument("--dry-run", action="store_true", help="Show planned registration payload only")
    parser.add_argument(
        "--api-base-url",
        default=DEFAULT_API_BASE_URL,
        help="Discord API base URL",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        response = ensure_commands_registered_from_env(
            environ={**os.environ, "DISCORD_API_BASE_URL": args.api_base_url},
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"[register-discord-commands] error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
