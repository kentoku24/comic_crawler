#!/usr/bin/env python3
import sys

from manga_watch.runner import RunnerConfig, replay_outbox_once


def main() -> int:
    try:
        config = RunnerConfig.from_env(require_discord=False)
    except Exception as exc:
        print(f"[replay_outbox] configuration error: {exc}", file=sys.stderr)
        return 2

    outcome = replay_outbox_once(config)
    print(f"[replay_outbox] result: {outcome}", flush=True)
    return 0 if outcome["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
