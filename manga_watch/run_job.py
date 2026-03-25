#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from typing import Mapping, Optional

from manga_watch.discord_outbound import DiscordChannelClient
from manga_watch.notifier import build_named_notifiers
from manga_watch.runner import (
    TRIGGER_SOURCE_DISCORD_FETCH,
    TRIGGER_SOURCE_SCHEDULED,
    RunnerConfig,
    report_to_stderr,
    run_once,
)

JOB_TRIGGER_SOURCE_ALIASES = {
    "discord_fetch": TRIGGER_SOURCE_DISCORD_FETCH,
    "fetch": TRIGGER_SOURCE_DISCORD_FETCH,
    "manual": TRIGGER_SOURCE_DISCORD_FETCH,
    "scheduled": TRIGGER_SOURCE_SCHEDULED,
}


def job_trigger_source_from_env(
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    env = os.environ if environ is None else environ
    raw_value = str(env.get("MANGA_WATCH_TRIGGER_SOURCE") or "").strip().lower()
    if not raw_value:
        return TRIGGER_SOURCE_SCHEDULED
    return JOB_TRIGGER_SOURCE_ALIASES.get(raw_value, raw_value)


def main() -> int:
    try:
        config = RunnerConfig.from_env()
    except Exception as exc:
        print(f"[run_job] configuration error: {exc}", file=sys.stderr)
        return 2

    named_notifiers = build_named_notifiers(config.notifier_config)
    discord_client = (
        DiscordChannelClient(config.discord_outbound_config)
        if config.discord_outbound_config is not None
        else None
    )
    outcome = run_once(
        config,
        named_notifiers=named_notifiers,
        discord_client=discord_client,
        trigger_source=job_trigger_source_from_env(),
    )
    if outcome.get("ok"):
        print(f"[run_job] outcome: {outcome}", flush=True)
        return 0

    report_to_stderr(f"[run_job] failed: {outcome}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
