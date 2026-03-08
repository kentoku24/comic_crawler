# comic_crawler

Docker コンテナ 1 つで定期クロールし、Discord に新着通知と run report を送る漫画更新監視アプリです。Issue #7 の cutover 以降、runtime は `watchlist/state v2` のみを読み書きします。Issue #17 以降は state v2 に更新履歴と未読イベントも保持します。

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
      "update_type": "main_story",
      "classification_reason": "episode_title matched main-story numbering",
      "default_notify": true,
      "from": {"seriesTitle": "...", "episodeTitle": "..."},
      "to": {
        "seriesTitle": "...",
        "episodeTitle": "...",
        "url": "...",
        "update_type": "main_story",
        "classification_reason": "episode_title matched main-story numbering",
        "default_notify": true
      }
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

checker は watchlist を並列に処理しますが、`updates` / `errors.sources` / state 更新順は常に watchlist 入力順で deterministic に保たれます。同一 host への HTTP burst は per-host cap で抑え、retry は transport error / timeout / HTTP `429` / `5xx` に限定します。`404` や parse error は即座に `errors.sources` に落ちます。

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

各作品は `latest`, `history`, `unread`, `health` を持ちます。

- `history`: `event_id` と `seen_at` を持つ更新イベント列
- `unread.event_ids`: 未読イベントの source of truth
- `health`: `last_checked_at`, `last_success_at`, `consecutive_failures`

履歴保持は作品ごとの `history_retention` で上書きでき、未指定時は既定値 20 件です。trim するときは「未読は全件保持 + 既読は最新 N 件のみ保持」を守ります。詳細な schema と migration contract は [spec.md](spec.md) を source of truth とします。

### backlog CLI

履歴と未読の確認には `python3 -m manga_watch.backlog` を使います。

```bash
python3 -m manga_watch.backlog --unread-only
python3 -m manga_watch.backlog --work-id KC_003913_S --json
python3 -m manga_watch.backlog --mark-read KC_003913_S
```

- `--json`: unread 数と履歴イベントを JSON で出力
- `--mark-read <work_id>`: その作品の現在未読を既読化し、保持ルールに従って履歴を trim

### legacy v1 input

`manga_watch/urls.txt` は migration 入力と rollback 用の参考データです。runtime はこのファイルを読みません。

更新分類の既定値は次の通りです。

- `main_story`: 既定で通知する
- `unknown`: fail-open で既定通知する
- `bonus`: 既定では main channel に通知しない
- `announcement`: 既定では main channel に通知しない

`main_story` と suppress 対象が衝突した場合は `unknown` に倒し、`bonus` と `announcement` だけが衝突した場合は suppress 側に残します。checker / state / run report には suppressed update も残ります。

## Supported sources

### ComicWalker

- 入力: `https://comic-walker.com/detail/<series>/episodes/<episode>`
- `work_id`: `KC_XXXXXX_S`
- `latest_key`: `episodeCode`

### webアクション

- 入力: `https://comic-action.com/episode/<id>`
- `work_id`: `comic-action:<series_id>`
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
- `MANGA_WATCH_HTTP_TIMEOUT`: source fetch の request timeout 秒。既定値は `25`
- `MANGA_WATCH_HTTP_RETRIES`: timeout / transport error / `429` / `5xx` に対する retry 回数。既定値は `2`
- `MANGA_WATCH_HTTP_RETRY_BACKOFF`: retry ごとの指数 backoff の基準秒。既定値は `0.5`
- `MANGA_WATCH_HTTP_WORKERS`: watchlist を並列処理する worker 数。既定値は `4`
- `MANGA_WATCH_HTTP_WORKERS_PER_HOST`: 同一 host に同時接続する上限。既定値は `2`

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
python3 -m manga_watch.check manga_watch/watchlist.json
python3 -m manga_watch.backlog --unread-only
python3 -m unittest tests.test_sources tests.test_update_classification tests.test_check tests.test_runner tests.test_migrate_v2 tests.test_backlog
```

runner をローカル起動する場合は Discord 環境変数を入れてから実行します。

```bash
python3 -m manga_watch.runner
```

## Adding a source adapter

`manga_watch/sources/registry.py` の `REGISTERED_ADAPTERS` が adapter registration の single source of truth です。

1. `manga_watch/sources/` に concrete `SourceAdapter` module を追加する
2. `manga_watch/sources/registry.py` の `REGISTERED_ADAPTERS` に adapter instance を追加する
3. fixture / state contract に影響がある場合は `tests/fixtures/` や関連 test を更新する
4. `.venv/bin/python -m unittest tests.test_sources tests.test_check tests.test_runner tests.test_migrate_v2` を実行する

2 を忘れると `tests.test_sources.SourceAdapterTests.test_registry_covers_every_concrete_adapter_module` が失敗します。

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
- `manga_watch/backlog.py`: 更新履歴 / 未読確認と既読化の最小 CLI
- `manga_watch/migrate_v2.py`: v1 から v2 への one-time migration CLI
- `manga_watch/storage.py`: watchlist/state v2 validation と atomic write
- `manga_watch/runner.py`: スケジューラ + Discord 通知
- `manga_watch/update_classification.py`: 更新種別と既定通知対象の分類ロジック
- `manga_watch/watchlist.json`: watchlist v2 sample
- `manga_watch/state.json`: state v2 sample
- `manga_watch/urls.txt`: legacy v1 migration input sample
- `tests/fixtures/<source>/<case>/`: raw response bundle + `manifest.json`

分類テストでは source ごとの代表例に加えて、main/bonus の曖昧ケースと bonus/announcement の suppress 維持ケースを確認します。

## Maintenance tips

- サイトの HTML が変わって検知が止まったら `python3 -m manga_watch.check manga_watch/watchlist.json` を実行して例外を確認する
- migration や state contract を更新したら `python3 -m unittest tests.test_sources tests.test_update_classification tests.test_check tests.test_runner tests.test_migrate_v2 tests.test_backlog` を回す
- 未読の確認や既読化を手動で行いたいときは `python3 -m manga_watch.backlog --unread-only` または `python3 -m manga_watch.backlog --mark-read <work_id>` を使う
- run/retry 設定を変えたときは `.venv/bin/python -m unittest tests.test_sources tests.test_update_classification tests.test_check tests.test_runner tests.test_migrate_v2` で runner まで確認する
- 新しい source を足すときは `manga_watch/sources/` に adapter を追加し、`registry.py` の `REGISTERED_ADAPTERS` に登録して fixture / source tests を更新する
