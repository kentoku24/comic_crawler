# Cron job spec (OpenClaw)

## Schedule (production)
- Daily at **19:00 JST**
- Cron:
  - `expr`: `0 19 * * *`
  - `tz`: `Asia/Tokyo`

## Behavior

Each run should:

1. Execute the checker:

```bash
python3 /path/to/comic_crawler/manga_watch/check.py /path/to/comic_crawler/manga_watch/urls.txt
```

2. Parse stdout JSON:
- `{ "updates": [...] }`

3. Load current state:
- `manga_watch/state.json`
- Build a human-readable list:
  - `作品名：最新話`

4. Notifications

- If `updates` is non-empty:
  - Post to the **main channel**
  - Mention the user (optional if channel is private)
  - Format per update:
    - `<作品名>：<前> → <後>`
      `<新URL>`

5. Run report (always)

- Post to the **run-report channel** every time:
  - `巡回実行しました` + timestamp
  - `現在のリスト` (bullets)
  - `通知`: `送信した` / `送信なし`
  - If updates exist: `更新検知: <count>`

## Notes
- Do not spam the main channel when there are no updates.
- Failures should ideally post an error summary to the run-report channel.
