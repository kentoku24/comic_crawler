#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
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
DEFAULT_ROLLBACK_MANIFEST_NAME = "rollback-manifest.json"
DEFAULT_RUNTIME_SERVICE = "comic-crawler"


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
                "unread": {"event_ids": []},
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
            "unread": {"event_ids": []},
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


def backup_inputs(inputs: List[Tuple[str, str]], backup_dir: str) -> List[Dict[str, str]]:
    os.makedirs(backup_dir, exist_ok=True)
    written = []
    for kind, source in inputs:
        if not os.path.exists(source):
            continue
        destination = os.path.join(backup_dir, os.path.basename(source))
        shutil.copy2(source, destination)
        written.append(
            {
                "kind": kind,
                "source_path": source,
                "backup_path": destination,
                "restore_to_path": source,
            }
        )
    return written


def validate_pre_cutover_image_ref(ref: str) -> str:
    normalized = ref.strip()
    if not normalized:
        raise ValueError("pre-cutover image ref must not be empty")
    if normalized.endswith(":latest") or normalized.lower() == "latest":
        raise ValueError("pre-cutover image ref must be immutable; do not use :latest")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", normalized):
        return normalized
    if re.fullmatch(r".+@sha256:[0-9a-f]{64}", normalized):
        return normalized
    raise ValueError(
        "pre-cutover image ref must be an immutable repo@sha256:... digest or local image ID sha256:..."
    )


def classify_pre_cutover_image_ref(ref: str) -> str:
    if ref.startswith("sha256:"):
        return "image_id"
    return "image_digest"


def validate_git_commit_ref(ref: str) -> str:
    normalized = ref.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", normalized):
        raise ValueError("pre-cutover git commit must be a full 40-character SHA")
    return normalized


def resolve_pre_cutover_git_commit(explicit_ref: Optional[str]) -> Dict[str, object]:
    repo_root = os.path.dirname(os.path.dirname(__file__))
    if explicit_ref:
        ref = validate_git_commit_ref(explicit_ref)
        captured_via = "cli"
    else:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ValueError(
                "could not resolve pre-cutover git commit from git HEAD; "
                "pass --pre-cutover-git-commit with the exact v1 commit"
            ) from exc
        ref = validate_git_commit_ref(result.stdout)
        captured_via = "git_head"
    git_dirty = None
    try:
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        git_dirty = None
    else:
        git_dirty = bool(status.stdout.strip())
    return {
        "ref": ref,
        "captured_via": captured_via,
        "git_dirty": git_dirty,
    }


def write_rollback_manifest(
    backup_dir: str,
    *,
    backup_records: List[Mapping[str, str]],
    watchlist_v2_path: str,
    state_v2_path: str,
    pre_cutover_image_ref: str,
    pre_cutover_git_commit: Mapping[str, object],
) -> str:
    manifest_path = os.path.join(backup_dir, DEFAULT_ROLLBACK_MANIFEST_NAME)
    watchlist_backup = next((record for record in backup_records if record["kind"] == "watchlist_v1"), None)
    state_backup = next((record for record in backup_records if record["kind"] == "state_v1"), None)
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "backup_dir": backup_dir,
        "data_backups": list(backup_records),
        "cutover_outputs": [
            {"kind": "watchlist_v2", "path": watchlist_v2_path},
            {"kind": "state_v2", "path": state_v2_path},
        ],
        "pre_cutover_runtime": {
            "service": DEFAULT_RUNTIME_SERVICE,
            "image_ref": pre_cutover_image_ref,
            "image_ref_kind": classify_pre_cutover_image_ref(pre_cutover_image_ref),
            "git_commit": pre_cutover_git_commit["ref"],
            "git_commit_captured_via": pre_cutover_git_commit["captured_via"],
            "git_dirty": pre_cutover_git_commit["git_dirty"],
        },
        "rollback_prechecks": [
            "Confirm the rollback trigger matches the contract: migration validation failed, parser/state regression failed, or the first post-cutover run showed state corruption, unexpected source errors, or update spam.",
            "Open rollback-manifest.json and verify the data_backups paths and pre_cutover_runtime.image_ref/git_commit match the cutover you are undoing.",
            "Stop the v2 runner before restoring data or changing the runtime/image.",
        ],
        "rollback_steps": [
            f"Restore {watchlist_backup['backup_path'] if watchlist_backup else 'the backed-up urls.txt'} to {watchlist_backup['restore_to_path'] if watchlist_backup else DEFAULT_V1_URLS_PATH}.",
            (
                f"Restore {state_backup['backup_path']} to {state_backup['restore_to_path']}."
                if state_backup
                else "Restore the backed-up state.json if one existed at cutover."
            ),
            "Return to the pre-cutover runtime identified by pre_cutover_runtime.git_commit and pre_cutover_runtime.image_ref before restarting the service.",
            "Restart the pre-cutover runtime so it reads legacy v1 paths again.",
        ],
        "rollback_smoke_checks": [
            {
                "name": "checker",
                "command": f"python3 -m manga_watch.check {watchlist_backup['restore_to_path'] if watchlist_backup else DEFAULT_V1_URLS_PATH}",
                "expectation": "Command exits successfully, emits JSON, and shows no Traceback.",
            },
            {
                "name": "runner",
                "command": f"docker compose up -d {DEFAULT_RUNTIME_SERVICE}",
                "expectation": "The runner stays up and its logs show no unexpected parser/state errors or notification burst.",
            },
        ],
    }
    atomic_write_json(manifest_path, manifest)
    return manifest_path


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
    parser.add_argument(
        "--pre-cutover-image-ref",
        required=True,
        help="Immutable container image digest (repo@sha256:...) or local image ID (sha256:...) for the v1 runtime.",
    )
    parser.add_argument(
        "--pre-cutover-git-commit",
        default=None,
        help="Full 40-character git SHA for the v1 runtime. Defaults to the current git HEAD.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    urls = read_v1_urls(args.watchlist_v1)
    watchlist_v2 = migrate_watchlist_v1_to_v2(urls)
    state_v1 = load_v1_state(args.state_v1)
    state_v2, orphaned_state_ids = migrate_state_v1_to_v2(state_v1, watchlist_v2)
    pre_cutover_image_ref = validate_pre_cutover_image_ref(args.pre_cutover_image_ref)
    pre_cutover_git_commit = resolve_pre_cutover_git_commit(args.pre_cutover_git_commit)
    backup_records = backup_inputs(
        [("watchlist_v1", args.watchlist_v1), ("state_v1", args.state_v1)],
        args.backup_dir,
    )
    rollback_manifest_path = write_rollback_manifest(
        args.backup_dir,
        backup_records=backup_records,
        watchlist_v2_path=args.watchlist_v2,
        state_v2_path=args.state_v2,
        pre_cutover_image_ref=pre_cutover_image_ref,
        pre_cutover_git_commit=pre_cutover_git_commit,
    )
    atomic_write_json(args.watchlist_v2, watchlist_v2)
    atomic_write_json(args.state_v2, state_v2)
    print(
        json.dumps(
            {
                "watchlist_v2": args.watchlist_v2,
                "state_v2": args.state_v2,
                "backup_paths": [record["backup_path"] for record in backup_records],
                "rollback_manifest_path": rollback_manifest_path,
                "pre_cutover_runtime": {
                    "image_ref": pre_cutover_image_ref,
                    "image_ref_kind": classify_pre_cutover_image_ref(pre_cutover_image_ref),
                    "git_commit": pre_cutover_git_commit["ref"],
                    "git_commit_captured_via": pre_cutover_git_commit["captured_via"],
                },
                "migrated_work_count": len(watchlist_v2["works"]),
                "orphaned_state_ids": orphaned_state_ids,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
