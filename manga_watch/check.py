#!/usr/bin/env python3
import json, os, re, sys, time
from urllib.parse import urlparse

import requests

UA = os.environ.get("MANGA_WATCH_UA", "Mozilla/5.0 (X11; Linux) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")
TIMEOUT = 25

STATE_PATH = os.environ.get("MANGA_WATCH_STATE", os.path.join(os.path.dirname(__file__), "state.json"))


def load_state():
    if not os.path.exists(STATE_PATH):
        return {"version": 1, "items": {}}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


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
    # episode style: 【第61話】作品名
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

    # episode codes look like: KC_0039130008900011_E
    prefix = series_code[:-2]  # e.g. KC_003913
    codes = set(re.findall(rf'{re.escape(prefix)}\d+_E', raw))
    if not codes:
        codes = set(re.findall(r'KC_\d+\d+_E', raw))
    if not codes:
        raise RuntimeError("comic-walker: no episode codes found")

    def key(code: str):
        # Extract the numeric part *after* the series prefix (e.g. KC_0039130008900011_E -> 0008900011)
        mm = re.search(rf'{re.escape(prefix)}(\d+)_E', code)
        return int(mm.group(1)) if mm else -1

    latest_code = max(codes, key=key)
    latest_url = f"https://comic-walker.com/detail/{series_code}/episodes/{latest_code}?episodeType=latest"

    # Titles: prefer episode page title (has 【第xx話】...), fallback to series page title.
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
    # Typical: "第39話 / ダンジョンの中のひと - 双見酔 | webアクション"
    main = page_title.split("|")[0].strip()  # drop site
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
            # sometimes HTML-escaped
            m = re.search(r'nextReadableProductUri&quot;\s*:\s*&quot;(https?://[^&]+)&quot;', html)
        if not m:
            # no next => assume this is the latest
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
        m = re.search(r'/detail/(KC_\d+_S)/episodes/', url)
        if not m:
            raise RuntimeError("comic-walker: could not parse series code")
        return {"kind": "comic-walker", "series": m.group(1), "seedUrl": f"https://comic-walker.com/detail/{m.group(1)}"}
    if "comic-action.com/episode/" in url:
        return {"kind": "comic-action", "seedUrl": url}
    if "kakuyomu.jp/works/" in url and "/episodes/" in url:
        m = re.search(r'kakuyomu\.jp/works/(\d+)/episodes/(\d+)', url)
        if not m:
            raise RuntimeError("kakuyomu: could not parse work/episode id")
        work_id, episode_id = m.group(1), m.group(2)
        return {"kind": "kakuyomu", "series": f"kakuyomu:{work_id}", "workId": work_id, "seedEpisodeId": episode_id, "seedUrl": url}
    raise RuntimeError(f"Unsupported URL: {url}")


def kakuyomu_latest(work_id: str):
    """Find latest episode for a Kakuyomu work.

    Kakuyomu work pages embed a Next.js JSON blob ("__NEXT_DATA__") that includes episode
    entries with title + publishedAt. We select the newest by publishedAt.
    """
    work_url = f"https://kakuyomu.jp/works/{work_id}"
    html = http_get(work_url)

    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
    if not m:
        raise RuntimeError("kakuyomu: __NEXT_DATA__ not found")

    raw = m.group(1)

    episodes = []
    # Example fragment:
    # "Episode:822139844009936710":{...,"id":"822139844009936710","title":"第67話...","publishedAt":"2026-01-27T08:00:03Z"}
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

    # newest by publishedAt (ISO8601 Z sorts lexicographically)
    published_at, latest_eid, latest_title = max(episodes, key=lambda x: x[0])
    latest_url = f"https://kakuyomu.jp/works/{work_id}/episodes/{latest_eid}"

    # Work title: easiest from the episode page <title>
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


def main():
    if len(sys.argv) < 2:
        print("usage: check.py <urls.txt>", file=sys.stderr)
        return 2

    urls_path = sys.argv[1]
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
            # Same episode, but we might have learned better metadata (titles). Update silently.
            # For title fields, prefer the freshly fetched values when present.
            merged = dict(prev_latest)
            for k2, v2 in latest.items():
                if v2 is None:
                    continue
                if k2 in ("seriesTitle", "episodeTitle", "pageTitle"):
                    # overwrite if we have a non-empty newer value
                    if v2 and v2 != merged.get(k2):
                        merged[k2] = v2
                    continue
                # for other fields, fill only if missing
                if not merged.get(k2):
                    merged[k2] = v2
            items_state[item_id] = {"latest": merged, "seenAt": now}

    state["lastRunAt"] = now
    save_state(state)

    print(json.dumps({"updates": updates}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
