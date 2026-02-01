# comic_crawler

Manga update crawler + simple state store.

This was built to run under **OpenClaw** (cron job) but the core checker is just a Python script.

## Repository layout

- `manga_watch/urls.txt`
  - Input list (one URL per line)
- `manga_watch/check.py`
  - Fetches sources, detects latest episode, compares with saved state
- `manga_watch/state.json`
  - Local persisted state (last-seen latest episode per work)

## What it does

1. Read `urls.txt`
2. For each URL, determine a stable **work id**
3. Fetch the latest episode info
4. Compare with `state.json`
5. If changed, output updates and update `state.json`

The script prints JSON like:

```json
{
  "updates": [
    {
      "id": "KC_003913_S",
      "from": {"seriesTitle": "...", "episodeTitle": "..."},
      "to": {"seriesTitle": "...", "episodeTitle": "...", "url": "..."}
    }
  ]
}
```

If there are no changes:

```json
{"updates": []}
```

## Supported sources (current)

### ComicWalker (comic-walker.com)
- Seed URL format: any episode URL is OK
  - Example: `https://comic-walker.com/detail/KC_003913_S/episodes/..._E`
- How it works:
  - Derives `KC_XXXXXX_S` from the seed URL
  - Fetches `https://comic-walker.com/detail/<KC_XXXXXX_S>`
  - Parses `__NEXT_DATA__` to find the newest episode code
  - Fetches the latest episode page `<title>` to extract:
    - `seriesTitle` (work title)
    - `episodeTitle` (e.g. `第61話`)

### webアクション (comic-action.com)
- Seed URL format: an episode page
  - Example: `https://comic-action.com/episode/2550689798784879524`
- How it works:
  - Follows `nextReadableProductUri` repeatedly until it stops
  - Parses the final page `<title>` to extract:
    - `seriesTitle`
    - `episodeTitle` (e.g. `第50話`)

## Local run

Prereqs:
- Python 3
- `requests`

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

python3 manga_watch/check.py manga_watch/urls.txt
cat manga_watch/state.json
```

## Using with OpenClaw (cron)

OpenClaw integration docs live in `openclaw/` (no secrets):
- `openclaw/README.md`
- `openclaw/example-config.json5` (template)
- `openclaw/cron-job.md` (schedule + behavior)

The intended wiring is:
- Cron runs the checker (`check.py`)
- If updates exist: notify a Discord channel
- Always: post a run report channel message

Example schedule:
- Production: **daily at 19:00 JST**

## Security notes

- Do **not** commit secrets (GitHub tokens, cookies, passwords).
- `state.json` contains only “last seen” metadata (titles/episode ids/urls).
- If you need authenticated crawling for a site later, prefer:
  - a separate secrets store, or
  - OpenClaw secret/config injection mechanisms

## Maintenance tips

- If a site changes HTML structure and updates stop working:
  - run `python3 manga_watch/check.py ...` locally and inspect exceptions
  - adjust the parsing logic in `check.py`
- When adding new sites:
  - add a new normalizer in `normalize_item()`
  - implement a `compute_latest()` branch that returns:
    - `seriesTitle`
    - `episodeTitle`
    - and either `episodeCode` or `url` as the stable comparison key
