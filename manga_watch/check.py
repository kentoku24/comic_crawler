#!/usr/bin/env python3
import json
import os
import sys
import time
from typing import Optional, Sequence

from manga_watch.sources import (
    DEFAULT_ADAPTERS,
    HttpClient,
    SourceAdapter,
    WorkDescriptor,
    fetch_latest_for_work,
    normalize_seed_url,
)

DEFAULT_STATE_PATH = os.path.join(os.path.dirname(__file__), "state.json")


def get_state_path():
    return os.environ.get("MANGA_WATCH_STATE", DEFAULT_STATE_PATH)


def load_state():
    state_path = get_state_path()
    if not os.path.exists(state_path):
        return {"version": 1, "items": {}}
    with open(state_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    state_path = get_state_path()
    tmp = state_path + ".tmp"
    state_dir = os.path.dirname(state_path) or "."
    os.makedirs(state_dir, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, state_path)


def _selected_adapters(adapters: Optional[Sequence[SourceAdapter]]) -> Sequence[SourceAdapter]:
    return DEFAULT_ADAPTERS if adapters is None else adapters


def normalize_item(url: str, adapters: Optional[Sequence[SourceAdapter]] = None):
    work = normalize_seed_url(url, adapters=_selected_adapters(adapters))
    return work.to_dict()


def compute_latest(
    item,
    adapters: Optional[Sequence[SourceAdapter]] = None,
    http_client: Optional[HttpClient] = None,
):
    work = WorkDescriptor.from_dict(item)
    latest = fetch_latest_for_work(
        work,
        adapters=_selected_adapters(adapters),
        http_client=http_client,
    )
    return latest.to_dict()


def run_check(
    urls_path: str,
    *,
    adapters: Optional[Sequence[SourceAdapter]] = None,
    http_client: Optional[HttpClient] = None,
):
    with open(urls_path, "r", encoding="utf-8") as f:
        urls = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]

    state = load_state()
    items_state = state.setdefault("items", {})

    updates = []
    now = int(time.time())

    for url in urls:
        item = normalize_item(url, adapters=adapters)
        item_id = item.get("workId") or item.get("series") or item["seedUrl"]
        latest = compute_latest(item, adapters=adapters, http_client=http_client)
        latest_id = latest.get("latestKey") or latest.get("episodeCode") or latest.get("url")

        prev = items_state.get(item_id)
        if not prev:
            items_state[item_id] = {"latest": latest, "seenAt": now}
            continue

        prev_latest = prev.get("latest", {})
        prev_id = prev_latest.get("latestKey") or prev_latest.get("episodeCode") or prev_latest.get("url")
        if prev_id != latest_id:
            updates.append({"id": item_id, "from": prev_latest, "to": latest})
            items_state[item_id] = {"latest": latest, "seenAt": now}
        else:
            merged = dict(prev_latest)
            for k2, v2 in latest.items():
                if v2 is None:
                    continue
                if k2 in ("seriesTitle", "episodeTitle", "pageTitle"):
                    if v2 and v2 != merged.get(k2):
                        merged[k2] = v2
                    continue
                if not merged.get(k2):
                    merged[k2] = v2
            items_state[item_id] = {"latest": merged, "seenAt": now}

    state["lastRunAt"] = now
    save_state(state)

    return {"updates": updates}


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: check.py <urls.txt>", file=sys.stderr)
        return 2

    result = run_check(argv[0])
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
