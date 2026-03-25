#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, TextIO

from manga_watch.storage import (
    get_state_path,
    get_watchlist_path,
    load_state,
    load_watchlist,
    save_state,
    save_watchlist,
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Migrate watchlist/state JSON into the Firestore storage backend.",
    )
    parser.add_argument("--watchlist-json", "--watchlist", dest="watchlist_json", default=get_watchlist_path())
    parser.add_argument("--state-json", "--state", dest="state_json", default=get_state_path())
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser.parse_args(argv)


def migrate_storage(
    *,
    watchlist_json: str,
    state_json: str,
    repository: Optional[object] = None,
) -> dict[str, object]:
    watchlist = load_watchlist(watchlist_json, backend="json")
    state = load_state(state_json, backend="json")
    if repository is None:
        save_watchlist(watchlist, backend="firestore")
        save_state(state, backend="firestore")
    else:
        repository.save_watchlist(watchlist)
        repository.save_state(state)
    return {
        "ok": True,
        "watchlist_path": watchlist_json,
        "state_path": state_json,
        "work_count": len(watchlist.get("works") or []),
        "state_work_count": len((state.get("works") or {}).keys()),
    }


def main(
    argv=None,
    *,
    repository: Optional[object] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    args = parse_args(argv)
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    try:
        result = migrate_storage(
            watchlist_json=args.watchlist_json,
            state_json=args.state_json,
            repository=repository,
        )
    except Exception as exc:
        print(f"[migrate_storage] error: {exc}", file=err)
        return 1

    if args.json_output:
        print(json.dumps(result, ensure_ascii=False), file=out)
    else:
        print(
            "[migrate_storage] ok "
            f"watchlist={result['watchlist_path']} "
            f"state={result['state_path']} "
            f"works={result['work_count']} "
            f"stateWorks={result['state_work_count']}",
            file=out,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
