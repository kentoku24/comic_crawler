# comic_crawler

Minimal manga update crawler used with OpenClaw.

## What it does
- Reads a list of manga/episode URLs from `manga_watch/urls.txt`
- Periodically checks the latest episode for each source
- Persists last-seen state in `manga_watch/state.json`

## Supported sources (current)
- ComicWalker (`comic-walker.com`)
- webアクション (`comic-action.com`)

## Run locally
```bash
python3 manga_watch/check.py manga_watch/urls.txt
```
Outputs JSON:
```json
{"updates": [...]}
```

## Notes
- This repo intentionally contains **no secrets** (tokens, cookies, credentials).
- `state.json` is just a sample/current state snapshot; you can delete it if you prefer.
