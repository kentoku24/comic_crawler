#!/usr/bin/env python3
import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from typing import Dict, List, Mapping, Optional, Tuple

from manga_watch.check import build_watchlist_entry, latest_id_for_state
from manga_watch.sources import HttpClient
from manga_watch.storage import (
    DEFAULT_STATE_PATH,
    DEFAULT_WATCHLIST_PATH,
    atomic_write_json,
    latest_runtime_to_storage,
)

DEFAULT_V1_URLS_PATH = os.path.join(os.path.dirname(__file__), "urls.txt")
DEFAULT_BACKUP_ROOT = os.path.join(os.path.dirname(__file__), "migration-backups")


def read_v1_urls(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]


def load_v1_state(path: str) -> Dict[str, object]:
    if not os.path.exists(path):
        return {"version": 1, "items": {}, "lastRunAt": None}
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if payload.get("version") != 1:
        raise ValueError("expected a v1 state file")
    if not isinstance(payload.get("items"), Mapping):
        raise ValueError("v1 state.items must be an object")
    return payload


def migrate_watchlist_v1_to_v2(
    urls: List[str],
    *,
    http_client: Optional[HttpClient] = None,
) -> Dict[str, object]:
    works = []
    seen_ids = set()
    for url in urls:
        entry = build_watchlist_entry(url, http_client=http_client)
        work_id = entry["id"]
        if work_id in seen_ids:
            raise ValueError(f"duplicate work_id during migration: {work_id}")
        seen_ids.add(work_id)
        works.append(entry)
    return {"version": 2, "works": works}


def migrate_state_v1_to_v2(
    v1_state: Mapping[str, object],
    watchlist_v2: Mapping[str, object],
) -> Tuple[Dict[str, object], List[str]]:
    v1_items = v1_state.get("items", {}) or {}
    last_run_at = v1_state.get("lastRunAt")
    works_state: Dict[str, object] = {}
    migrated_ids = set()

    for work in watchlist_v2["works"]:
        work_id = str(work["id"])
        source = str(work["source"])
        v1_entry = v1_items.get(work_id)
        matched_v1_id = work_id
        if not isinstance(v1_entry, Mapping):
            matched_v1_id = str(work["seed_url"])
            v1_entry = v1_items.get(matched_v1_id)
        if not isinstance(v1_entry, Mapping):
            works_state[work_id] = {
                "latest": {},
                "history": [],
                "health": {
                    "last_checked_at": None,
                    "last_success_at": None,
                    "consecutive_failures": 0,
                },
            }
            continue

        migrated_ids.add(matched_v1_id)
        latest = migrate_v1_latest(v1_entry.get("latest"), work_id=work_id, source=source)
        seen_at = v1_entry.get("seenAt")
        if seen_at is None:
            seen_at = last_run_at
        works_state[work_id] = {
            "latest": latest_runtime_to_storage(latest),
            "history": [],
            "health": {
                "last_checked_at": int(seen_at) if seen_at is not None else None,
                "last_success_at": int(seen_at) if seen_at is not None else None,
                "consecutive_failures": 0,
            },
        }

    orphaned_state_ids = sorted(work_id for work_id in v1_items.keys() if work_id not in migrated_ids)
    return {
        "version": 2,
        "works": works_state,
        "last_run_at": int(last_run_at) if last_run_at is not None else None,
    }, orphaned_state_ids


def migrate_v1_latest(latest: object, *, work_id: str, source: str) -> Dict[str, object]:
    if not isinstance(latest, Mapping):
        raise ValueError(f"v1 state entry {work_id} is missing latest")
    migrated = dict(latest)
    migrated["workId"] = work_id
    migrated["source"] = source
    latest_key = latest_id_for_state(migrated)
    if not latest_key:
        raise ValueError(f"v1 state entry {work_id} is missing a latest key")
    migrated["latestKey"] = latest_key
    return migrated


def backup_inputs(paths: List[str], backup_dir: str) -> List[str]:
    os.makedirs(backup_dir, exist_ok=True)
    written = []
    for source in paths:
        if not os.path.exists(source):
            continue
        destination = os.path.join(backup_dir, os.path.basename(source))
        shutil.copy2(source, destination)
        written.append(destination)
    return written


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Migrate comic_crawler data files from v1 to v2.")
    parser.add_argument("--watchlist-v1", default=DEFAULT_V1_URLS_PATH)
    parser.add_argument("--state-v1", default=DEFAULT_STATE_PATH)
    parser.add_argument("--watchlist-v2", default=DEFAULT_WATCHLIST_PATH)
    parser.add_argument("--state-v2", default=DEFAULT_STATE_PATH)
    parser.add_argument(
        "--backup-dir",
        default=os.path.join(
            DEFAULT_BACKUP_ROOT,
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        ),
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    urls = read_v1_urls(args.watchlist_v1)
    watchlist_v2 = migrate_watchlist_v1_to_v2(urls)
    state_v1 = load_v1_state(args.state_v1)
    state_v2, orphaned_state_ids = migrate_state_v1_to_v2(state_v1, watchlist_v2)
    backup_paths = backup_inputs([args.watchlist_v1, args.state_v1], args.backup_dir)
    atomic_write_json(args.watchlist_v2, watchlist_v2)
    atomic_write_json(args.state_v2, state_v2)
    print(
        json.dumps(
            {
                "watchlist_v2": args.watchlist_v2,
                "state_v2": args.state_v2,
                "backup_paths": backup_paths,
                "migrated_work_count": len(watchlist_v2["works"]),
                "orphaned_state_ids": orphaned_state_ids,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
