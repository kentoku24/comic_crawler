# comic_crawler / spec

## Glossary (project naming)
To avoid confusion, we use these fixed terms:

- **comic_crawler**: the whole project/repository
- **watchlist**: `manga_watch/urls.txt` (input list)
- **checker**: `manga_watch/check.py` (the script that checks latest episodes)
- **state / last_seen**: `manga_watch/state.json` (persisted last-seen snapshot)
- **run**: a single execution of the checker (scheduled by cron)
- **diff**: the `updates` array produced by the checker (detected changes)
- **alert**: notification posted to the main channel when diff is non-empty
- **run report**: message posted every run to the run-report channel

## Purpose
Monitor multiple manga sites, detect when a new episode appears for followed works, and notify via OpenClaw/Discord.

## Inputs

### Watch list
- File: `manga_watch/urls.txt`
- Format: one URL per line
- Lines starting with `#` are comments

Supported URL types:
- ComicWalker episode URL
  - Example: `https://comic-walker.com/detail/KC_003913_S/episodes/KC_0039130008900011_E?...`
- webアクション episode URL
  - Example: `https://comic-action.com/episode/2550689798784879524`

## State (persistence)

### State file
- Default path: `manga_watch/state.json`
- Override with env var: `MANGA_WATCH_STATE=/path/to/state.json`

### State schema (v1)
```json
{
  "version": 1,
  "items": {
    "<workId>": {
      "latest": {
        "seriesTitle": "...",
        "episodeTitle": "...",
        "episodeCode": "...",  // optional
        "url": "...",          // optional
        "pageTitle": "..."     // optional
      },
      "seenAt": 1700000000
    }
  },
  "lastRunAt": 1700000000
}
```

### WorkId rules
- ComicWalker: `KC_XXXXXX_S` (derived from the seed URL)
- webアクション: the seed URL itself (currently)

## Core behavior

### Execution
Command:
```bash
python3 manga_watch/check.py manga_watch/urls.txt
```

Output:
- Always prints JSON: `{ "updates": [...] }`

### Latest episode detection

#### ComicWalker
1. Derive series code (e.g. `KC_003913_S`) from seed URL.
2. Fetch series page: `https://comic-walker.com/detail/<series_code>`
3. Parse `__NEXT_DATA__` for episode codes matching the series prefix (e.g. `KC_003913..._E`).
4. Select the newest episode by comparing the numeric suffix after the prefix.
5. Build latest episode URL:
   `https://comic-walker.com/detail/<series_code>/episodes/<episodeCode>?episodeType=latest`
6. Fetch the latest episode page and parse `<title>` to fill:
   - `seriesTitle`
   - `episodeTitle` (usually `第xx話` but may be other formats)

#### webアクション
1. Start from a seed episode URL.
2. Fetch page HTML and read `nextReadableProductUri`.
3. Follow the chain until `nextReadableProductUri` is absent.
4. Parse the final page `<title>` to fill:
   - `seriesTitle`
   - `episodeTitle` (e.g. `第50話`)

### Update detection
- A work is considered updated when the stable id changes:
  - ComicWalker: `episodeCode`
  - webアクション: final resolved episode URL

### Metadata merge (no-notify)
If the stable id is unchanged but additional metadata becomes available (titles, etc.), the script updates `state.json` silently without reporting an update.

## Notification behavior (OpenClaw wiring)

This repo provides the checker only. In OpenClaw, cron jobs are configured to:

1. Run the checker
2. If updates exist:
   - Post a notification to the main channel (mentioning the user)
3. Always:
   - Post a run report to a separate channel containing:
     - that the crawl ran
     - current list (titles + latest episode)
     - whether a notification was sent

## Scheduling
- Production schedule requirement: **daily at 19:00 JST**
  - Cron expression: `0 19 * * *`
  - Timezone: `Asia/Tokyo`

## Non-goals (current)
- Authenticated crawling (cookies/login) is not implemented.
- Robust anti-bot / JS-rendered pages beyond the current techniques is not implemented.
- web_search-based discovery is not used.

## Security
- Do not store or commit secrets (tokens, passwords, cookies).
- If authentication is added later, use a separate secrets mechanism.
