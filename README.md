# comic_crawler

Docker コンテナ 1 つで定期クロールし、Discord に新着通知と run report を送る漫画更新監視アプリです。Issue #7 の cutover 以降、runtime は `watchlist/state v2` のみを読み書きします。

## What it does

1. `manga_watch/watchlist.json` の watchlist v2 を読む
2. source adapter が `seed_url` を work descriptor に正規化する
3. source adapter が最新エピソードを取得する
4. `manga_watch/state.json` の state v2 と比較する
5. 更新があれば Discord main channel に通知する
6. 毎回 Discord run-report channel に実行結果を送る

checker の出力契約は JSON のままです。

```json
{
  "updates": [
    {
      "id": "KC_003913_S",
      "from": {"seriesTitle": "...", "episodeTitle": "..."},
      "to": {"seriesTitle": "...", "episodeTitle": "...", "url": "..."}
    }
  ],
  "errors": {
    "sources": [
      {
        "url": "https://example.com/work",
        "phase": "fetch_latest",
        "kind": "parse",
        "errorType": "SourceParseError",
        "message": "..."
      }
    ],
    "run": []
  }
}
```

## Data files

### watchlist v2

- path: `manga_watch/watchlist.json`
- env: `MANGA_WATCH_WATCHLIST`
- legacy env fallback: `MANGA_WATCH_URLS`

```json
{
  "version": 2,
  "works": [
    {
      "id": "KC_003913_S",
      "source": "comic-walker",
      "seed_url": "https://comic-walker.com/detail/KC_003913_S",
      "enabled": true,
      "notification_policy": {
        "mode": "all",
        "allowed_update_types": null
      }
    }
  ]
}
```

### state v2

- path: `manga_watch/state.json`
- env: `MANGA_WATCH_STATE`

各作品は `latest`, `history`, `health` を持ち、`health` には `last_checked_at`, `last_success_at`, `consecutive_failures` を保持します。詳細な schema と migration contract は [spec.md](spec.md) を source of truth とします。

### legacy v1 input

`manga_watch/urls.txt` は migration 入力と rollback 用の参考データです。runtime はこのファイルを読みません。

## Supported sources

### ComicWalker

- 入力: `https://comic-walker.com/detail/<series>/episodes/<episode>`
- `work_id`: `KC_XXXXXX_S`
- `latest_key`: `episodeCode`

### webアクション

- 入力: `https://comic-action.com/episode/<id>`
- `work_id`: seed episode URL
- `latest_key`: 最終到達 episode URL

### Kakuyomu

- 入力: `https://kakuyomu.jp/works/<work>/episodes/<episode>`
- `work_id`: `kakuyomu:<numeric_work_id>`
- `latest_key`: 最新 episode id

## Docker run

1. `.env.example` を `.env` にコピーして Discord 設定を入れる
2. 必要なら `manga_watch/watchlist.json` を編集する
3. 起動する

```bash
docker compose up -d --build
docker compose logs -f
```

compose は `manga_watch/watchlist.json` を read-only mount し、state v2 は volume `crawler-data` に保存します。

### Environment variables

- `DISCORD_BOT_TOKEN`: Discord Bot token
- `DISCORD_MAIN_CHANNEL_ID`: 更新通知先 channel id
- `DISCORD_RUN_REPORT_CHANNEL_ID`: 毎回の run report 送信先 channel id
- `TZ`: スケジュール計算の timezone。既定値は `Asia/Tokyo`
- `CRAWL_SCHEDULE`: cron 形式。既定値は `0 19 * * *`
- `CRAWL_INTERVAL`: 秒単位の固定間隔。`CRAWL_SCHEDULE` と同時指定は不可
- `RUN_ON_STARTUP`: `true` のとき起動直後に 1 回実行
- `MANGA_WATCH_WATCHLIST`: watchlist v2 パス。compose では `/app/manga_watch/watchlist.json`
- `MANGA_WATCH_STATE`: state v2 パス。compose では `/data/state.json`

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
python3 -m manga_watch.check manga_watch/watchlist.json
python3 -m unittest tests.test_sources tests.test_check tests.test_runner tests.test_migrate_v2
```

runner をローカル起動する場合は Discord 環境変数を入れてから実行します。

```bash
python3 -m manga_watch.runner
```

## One-time migration from v1

```bash
python3 -m manga_watch.migrate_v2 \
  --watchlist-v1 manga_watch/urls.txt \
  --state-v1 /data/state.json \
  --watchlist-v2 manga_watch/watchlist.json \
  --state-v2 /data/state.json \
  --backup-dir /data/migration-backups/20260308T080000Z
```

- migration は v1 入力の backup を先に取ります
- migration 後は runtime 設定を `MANGA_WATCH_WATCHLIST` に切り替えます
- rollback には backup の復元に加えて pre-cutover runtime への差し戻しが必要です

詳細な mapping / cutover / rollback 条件は [spec.md](spec.md) を参照してください。

## Repository layout

- `manga_watch/check.py`: watchlist/state v2 を読む checker
- `manga_watch/migrate_v2.py`: v1 から v2 への one-time migration CLI
- `manga_watch/storage.py`: watchlist/state v2 validation と atomic write
- `manga_watch/runner.py`: スケジューラ + Discord 通知
- `manga_watch/watchlist.json`: watchlist v2 sample
- `manga_watch/state.json`: state v2 sample
- `manga_watch/urls.txt`: legacy v1 migration input sample
- `tests/fixtures/<source>/<case>/`: raw response bundle + `manifest.json`

## Maintenance tips

- サイトの HTML が変わって検知が止まったら `python3 -m manga_watch.check manga_watch/watchlist.json` を実行して例外を確認する
- migration や state contract を更新したら `python3 -m unittest tests.test_sources tests.test_check tests.test_runner tests.test_migrate_v2` を回す
- 新しい source を足すときは `manga_watch/sources/` に adapter を追加し、`registry.py` に登録する
