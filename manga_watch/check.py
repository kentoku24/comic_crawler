#!/usr/bin/env python3
import json
import os
import re
import sys
import time

import requests

UA = os.environ.get(
    "MANGA_WATCH_UA",
    "Mozilla/5.0 (X11; Linux) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
)
TIMEOUT = 25
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


def http_get(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def html_title(html: str):
    m = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    t = re.sub(r"\s+", " ", m.group(1)).strip()
    return t or None


def _find_first(obj, keys):
    """Depth-first search for the first string value whose key is in keys."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, str) and v.strip():
                return v.strip()
        for v in obj.values():
            hit = _find_first(v, keys)
            if hit:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_first(v, keys)
            if hit:
                return hit
    return None


def parse_comic_walker_title(page_title: str):
    """Parse ComicWalker title into (seriesTitle, episodeTitle) best-effort.

    Examples:
      - "【第61話】航宙軍士官、冒険者になる｜カドコミ (コミックウォーカー)"
      - "蜘蛛ですが、なにか？｜カドコミ (コミックウォーカー)"
    """
    if not page_title:
        return None, None
    left = page_title.split("｜")[0].strip()
    m = re.match(r"^【([^】]+)】\s*(.+)$", left)
    if m:
        return m.group(2).strip() or None, m.group(1).strip() or None
    return left or None, None


def comic_walker_latest(series_code: str):
    """Return dict with episodeCode + url (+ titles) for latest episode."""
    url = f"https://comic-walker.com/detail/{series_code}"
    html = http_get(url)
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
    if not m:
        raise RuntimeError("comic-walker: __NEXT_DATA__ not found")

    raw = m.group(1)
    prefix = series_code[:-2]
    codes = set(re.findall(rf"{re.escape(prefix)}\d+_E", raw))
    if not codes:
        codes = set(re.findall(r"KC_\d+\d+_E", raw))
    if not codes:
        raise RuntimeError("comic-walker: no episode codes found")

    def key(code: str):
        mm = re.search(rf"{re.escape(prefix)}(\d+)_E", code)
        return int(mm.group(1)) if mm else -1

    latest_code = max(codes, key=key)
    latest_url = f"https://comic-walker.com/detail/{series_code}/episodes/{latest_code}?episodeType=latest"

    series_title = None
    episode_title = None

    try:
        ep_html = http_get(latest_url)
        t = html_title(ep_html)
        series_title, episode_title = parse_comic_walker_title(t)
    except Exception:
        t = html_title(html)
        series_title, _ = parse_comic_walker_title(t)

    return {
        "series": series_code,
        "seriesTitle": series_title,
        "episodeCode": latest_code,
        "episodeTitle": episode_title,
        "url": latest_url,
    }


def parse_comic_action_title(page_title: str):
    """Try to extract (episodeLabel, seriesTitle) from a webアクション <title>."""
    if not page_title:
        return None, None
    main = page_title.split("|")[0].strip()
    parts = [p.strip() for p in main.split("/")]
    if len(parts) >= 2:
        ep = parts[0]
        rest = parts[1]
        series = rest.split("-")[0].strip()
        return ep or None, series or None
    return None, None


def comic_action_latest_from_episode(start_episode_url: str, max_hops: int = 30):
    """Follow nextReadableProductUri chain to reach the newest readable episode."""
    cur = start_episode_url
    seen = set()
    last_html = None
    for _ in range(max_hops):
        if cur in seen:
            break
        seen.add(cur)
        html = http_get(cur)
        last_html = html
        m = re.search(r'nextReadableProductUri\"\s*:\s*\"(https?://[^\"]+)\"', html)
        if not m:
            m = re.search(r'nextReadableProductUri&quot;\s*:\s*&quot;(https?://[^&]+)&quot;', html)
        if not m:
            t = html_title(html)
            ep, series = parse_comic_action_title(t)
            return {"url": cur, "pageTitle": t, "seriesTitle": series, "episodeTitle": ep}
        nxt = m.group(1)
        if not nxt or nxt == cur:
            t = html_title(html)
            ep, series = parse_comic_action_title(t)
            return {"url": cur, "pageTitle": t, "seriesTitle": series, "episodeTitle": ep}
        cur = nxt

    t = html_title(last_html or "")
    ep, series = parse_comic_action_title(t)
    return {"url": cur, "pageTitle": t, "seriesTitle": series, "episodeTitle": ep}


def normalize_item(url: str):
    if "comic-walker.com/detail/" in url and "/episodes/" in url:
        m = re.search(r"/detail/(KC_\d+_S)/episodes/", url)
        if not m:
            raise RuntimeError("comic-walker: could not parse series code")
        return {"kind": "comic-walker", "series": m.group(1), "seedUrl": f"https://comic-walker.com/detail/{m.group(1)}"}
    if "comic-action.com/episode/" in url:
        return {"kind": "comic-action", "seedUrl": url}
    if "kakuyomu.jp/works/" in url and "/episodes/" in url:
        m = re.search(r"kakuyomu\.jp/works/(\d+)/episodes/(\d+)", url)
        if not m:
            raise RuntimeError("kakuyomu: could not parse work/episode id")
        work_id, episode_id = m.group(1), m.group(2)
        return {
            "kind": "kakuyomu",
            "series": f"kakuyomu:{work_id}",
            "workId": work_id,
            "seedEpisodeId": episode_id,
            "seedUrl": url,
        }
    raise RuntimeError(f"Unsupported URL: {url}")


def kakuyomu_latest(work_id: str):
    """Find latest episode for a Kakuyomu work."""
    work_url = f"https://kakuyomu.jp/works/{work_id}"
    html = http_get(work_url)

    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
    if not m:
        raise RuntimeError("kakuyomu: __NEXT_DATA__ not found")

    raw = m.group(1)

    episodes = []
    for mm in re.finditer(
        r'"Episode:(\d+)"\s*:\s*\{[^\}]*?"id"\s*:\s*"(\d+)"[^\}]*?"title"\s*:\s*"([^"]+)"[^\}]*?"publishedAt"\s*:\s*"([^"]+)"',
        raw,
    ):
        eid = mm.group(2)
        title = mm.group(3)
        published_at = mm.group(4)
        episodes.append((published_at, eid, title))

    if not episodes:
        raise RuntimeError("kakuyomu: no episodes found in __NEXT_DATA__")

    _, latest_eid, latest_title = max(episodes, key=lambda x: x[0])
    latest_url = f"https://kakuyomu.jp/works/{work_id}/episodes/{latest_eid}"

    ep_html = http_get(latest_url)
    t = html_title(ep_html)

    series_title = None
    episode_title = latest_title
    if t and " - " in t:
        parts = [p.strip() for p in t.split(" - ")]
        if len(parts) >= 2:
            episode_title = parts[0] or episode_title
            series_title = parts[1]

    return {
        "series": f"kakuyomu:{work_id}",
        "seriesTitle": series_title,
        "episodeCode": str(latest_eid),
        "episodeTitle": episode_title,
        "url": latest_url,
    }


def compute_latest(item):
    if item["kind"] == "comic-walker":
        return comic_walker_latest(item["series"])
    if item["kind"] == "comic-action":
        return comic_action_latest_from_episode(item["seedUrl"])
    if item["kind"] == "kakuyomu":
        return kakuyomu_latest(item["workId"])
    raise RuntimeError(f"Unknown kind: {item['kind']}")


def run_check(urls_path: str):
    with open(urls_path, "r", encoding="utf-8") as f:
        urls = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]

    state = load_state()
    items_state = state.setdefault("items", {})

    updates = []
    now = int(time.time())

    for url in urls:
        item = normalize_item(url)
        item_id = item.get("series") or item["seedUrl"]
        latest = compute_latest(item)
        latest_id = latest.get("episodeCode") or latest.get("url")

        prev = items_state.get(item_id)
        if not prev:
            items_state[item_id] = {"latest": latest, "seenAt": now}
            continue

        prev_latest = prev.get("latest", {})
        prev_id = prev_latest.get("episodeCode") or prev_latest.get("url")
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
