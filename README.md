# comic_crawler

Docker コンテナ 1 つで定期クロールし、`stdout` と generic webhook に新着通知 event を送れる漫画更新監視アプリです。run report は毎回標準出力に出します。Issue #7 の cutover 以降、runtime は `watchlist/state v2` のみを読み書きし、Issue #17 以降は state v2 に更新履歴と未読イベントも保持します。

## Python 3.12 baseline

Docker / ローカル開発 / 将来の CI はすべて Python `3.12` を単一の runtime baseline とします。Docker image policy は `python:3.12-slim` に合わせ、ローカルツール向けには `.python-version` でも `3.12` を宣言します。Python `3.10` / `3.11` compatibility は要求しません。
`python3.12` が PATH に無い場合は、pyenv / asdf / OS package manager などで 3.12 を先に導入または選択してから `.venv` を作ってください。

## What it does

1. `manga_watch/watchlist.json` の watchlist v2 を読む
2. source adapter が `seed_url` を work descriptor に正規化する
3. source adapter が最新エピソードを取得する
4. `manga_watch/state.json` の state v2 と比較する
5. 更新があれば configured notifier backend(s) に update event を fan-out する
6. 毎回 run report を標準出力に出す

checker の出力契約は JSON のままです。

```json
{
  "updates": [
    {
      "id": "KC_003913_S",
      "update_type": "main_story",
      "classification_reason": "episode_title matched main-story numbering",
      "default_notify": true,
      "notification": {
        "mode": "important_only",
        "allowed_update_types": null,
        "should_notify": true,
        "applied_via": "mode",
        "reason": "mode=important_only allows main_story"
      },
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
      },
      "health_policy": {
        "expected_interval_seconds": 86400
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

履歴保持は作品ごとの `history_retention` で上書きでき、未指定時は既定値 20 件です。trim するときは「未読は全件保持 + 既読は最新 N 件のみ保持」を守ります。必要なら watchlist 側で `health_policy.expected_interval_seconds` を指定し、stale 判定の期待巡回間隔を作品単位で上書きできます。詳細な schema と migration contract は [spec.md](spec.md) を source of truth とします。

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
- `bonus`: 既定では notifier backend に通知しない
- `announcement`: 既定では notifier backend に通知しない

`main_story` と suppress 対象が衝突した場合は `unknown` に倒し、`bonus` と `announcement` だけが衝突した場合は suppress 側に残します。

watchlist の `notification_policy` は classification default の上に適用されます。

- `allowed_update_types` が `null` でないときは mode より優先する
- `mode=all`: `default_notify` を無視して全 `update_type` を通知する
- `mode=important_only`: `main_story` と `unknown` だけを通知する
- `mode=mute`: どの `update_type` も通知しない

checker / state / run report には suppressed update も残ります。machine-readable な checker 出力では `updates[].notification.should_notify=false` で「更新はあったが通知しない」を区別できます。

## Notification events

runner が backend に送る update event は次の schema です。

```json
{
  "schema_version": 1,
  "event_id": "KC_003913_S:6ec0f89d...",
  "work_id": "KC_003913_S",
  "latest_key": "KC_0039130008900011_E",
  "series_title": "蜘蛛ですが、なにか？",
  "update_type": "main_story",
  "detected_at": "2026-03-08T08:00:00Z",
  "notification": {
    "mode": "important_only",
    "allowed_update_types": null,
    "should_notify": true,
    "applied_via": "mode",
    "reason": "mode=important_only allows main_story"
  },
  "from": {
    "latest_key": "KC_0039130008800011_E",
    "series_title": "蜘蛛ですが、なにか？",
    "episode_title": "第77話その1",
    "episode_code": "KC_0039130008800011_E",
    "url": "https://example.com/old"
  },
  "to": {
    "latest_key": "KC_0039130008900011_E",
    "series_title": "蜘蛛ですが、なにか？",
    "episode_title": "第77話その2",
    "episode_code": "KC_0039130008900011_E",
    "url": "https://example.com/new",
    "update_type": "main_story",
    "default_notify": true
  }
}
```

- `event_id` は `work_id + latest_key` を SHA-256 で固定長化した stable id です。consumer はこれで dedupe します。
- delivery contract は consumer 視点では at-least-once 前提です。duplicate を受け取っても `event_id` で idempotent に処理してください。
- `notification` は watchlist policy を適用した時点の effective decision です。`default_notify=false` な `bonus` update でも `mode=all` なら `should_notify=true` になります。
- current runner は persisted outbox を持たず、backend 送信は同期 1 回です。backend failure が state 更新後に起きると manual replay が必要です。
- `stdout` backend は 1 event = 1 JSON line を標準出力へ flush します。
- `webhook` backend は 1 event ごとに JSON POST します。HTTP `2xx` だけを success とし、それ以外の status / timeout / transport error は failure として run を失敗扱いにします。
- `MANGA_WATCH_NOTIFIER_BACKENDS=stdout,webhook` のように comma-separated で複数 backend を指定すると、同じ event を同一 run 内で全 backend に送ります。

## Supported sources

| Source | `watchlist add` accepted inputs | Stored `seed_url` | `work_id` | `latest_key` |
| --- | --- | --- | --- | --- |
| ComicWalker | canonical series URL, episode URL | `https://comic-walker.com/detail/<series>` | `KC_XXXXXX_S` | `episodeCode` |
| webアクション | episode URL only | 入力 URL のまま | `comic-action:<series_id>` | 最終到達 episode URL |
| Kakuyomu | work URL, episode URL | 入力 URL のまま | `kakuyomu:<numeric_work_id>` | 最新 episode id |

Phase 1 では source ごとの capability 差を隠しません。`watchlist add` が受け付ける URL 種別は上の表だけです。

## Watchlist add CLI

```bash
python3 -m manga_watch.watchlist add <url>
python3 -m manga_watch.watchlist add <url> --watchlist /path/to/watchlist.json
```

- デフォルトの watchlist パスは `MANGA_WATCH_WATCHLIST`、未設定時は `MANGA_WATCH_URLS`、さらに未設定なら `manga_watch/watchlist.json`
- 出力は常に JSON
- `action=added` と `action=duplicate` は exit code `0`
- `action=error` は exit code `1`

成功時は normalize preview を `entry` に返します。

```json
{
  "action": "added",
  "input_url": "https://kakuyomu.jp/works/123",
  "watchlist_path": "manga_watch/watchlist.json",
  "entry": {
    "id": "kakuyomu:123",
    "source": "kakuyomu",
    "seed_url": "https://kakuyomu.jp/works/123",
    "enabled": true,
    "notification_policy": {"mode": "all", "allowed_update_types": null}
  },
  "work_count": 1
}
```

重複時は新規追加せず、既存 entry を返します。

```json
{
  "action": "duplicate",
  "entry": {"id": "kakuyomu:123"},
  "existing": {"id": "kakuyomu:123"},
  "work_count": 1
}
```

エラー時は `kind`, `message`, `next_action` を返します。`kind` は少なくとも `invalid_url`, `unsupported_source`, `unsupported_url_type`, `normalize_failed` を使います。

```json
{
  "action": "error",
  "error": {
    "kind": "unsupported_url_type",
    "message": "comic-action does not support this URL type for `watchlist add`: https://comic-action.com/series/123",
    "next_action": "Supported input types for comic-action: episode URL. Examples: https://comic-action.com/episode/123456"
  }
}
```

## Docker run

1. `.env.example` を `.env` にコピーして notifier 設定を入れる
2. 必要なら `manga_watch/watchlist.json` を編集する
3. 起動する

```bash
docker compose up -d --build
docker compose logs -f
```

compose は `manga_watch/watchlist.json` を read-only mount し、state v2 は volume `crawler-data` に保存します。

### Environment variables

- `MANGA_WATCH_NOTIFIER_BACKENDS`: required。comma-separated backend list。現在値は `stdout`, `webhook`
- `MANGA_WATCH_WEBHOOK_URL`: `webhook` backend を使うときの POST 先 URL
- `MANGA_WATCH_WEBHOOK_TIMEOUT`: webhook timeout 秒。既定値は `10`
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

ローカル実行は `python3.12` で作った `.venv` を前提にします。Python `3.10` / `3.11` での互換確認は不要です。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m manga_watch.check manga_watch/watchlist.json
.venv/bin/python -m manga_watch.backlog --unread-only
.venv/bin/python -m manga_watch.check --status
.venv/bin/python -m manga_watch.check --status --format json
.venv/bin/python -m unittest tests.test_sources tests.test_update_classification tests.test_check tests.test_status tests.test_watchlist tests.test_runner tests.test_migrate_v2 tests.test_backlog
```

runner をローカル起動する場合は notifier 環境変数を入れてから実行します。

```bash
export MANGA_WATCH_NOTIFIER_BACKENDS=stdout
.venv/bin/python -m manga_watch.runner
```

## Status CLI

`--status` は crawl を走らせず、現在の health を確認するための自己診断モードです。

```bash
.venv/bin/python -m manga_watch.check --status
.venv/bin/python -m manga_watch.check --status --format json
```

- text 出力: 監視件数、最終 run 時刻、最終成功時刻、health counts、失敗中作品、stale 作品、作品別 health
- JSON 出力: `summary` と `works[]` を返す
- stale 判定: 固定 48 時間ではなく `health_policy.expected_interval_seconds`、無ければ `CRAWL_INTERVAL` / `CRAWL_SCHEDULE` 由来の expected interval を 2 倍した窓で判定
- health state: `healthy`, `degraded`, `stale`, `broken`, `pending`

## Adding a source adapter

`manga_watch/sources/registry.py` の `REGISTERED_ADAPTERS` が adapter registration の single source of truth です。

1. `manga_watch/sources/` に concrete `SourceAdapter` module を追加する
2. `manga_watch/sources/registry.py` の `REGISTERED_ADAPTERS` に adapter instance を追加する
3. fixture / state contract に影響がある場合は `tests/fixtures/` や関連 test を更新する
4. `.venv/bin/python -m unittest tests.test_sources tests.test_check tests.test_runner tests.test_migrate_v2` を実行する

2 を忘れると `tests.test_sources.SourceAdapterTests.test_registry_covers_every_concrete_adapter_module` が失敗します。

## One-time migration from v1

migration も `python3.12` で作った `.venv` から実行します。

```bash
.venv/bin/python -m manga_watch.migrate_v2 \
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
- `manga_watch/status.py`: status CLI 向けの health 集約と text / JSON 表示
- `manga_watch/storage.py`: watchlist/state v2 validation と atomic write
- `manga_watch/notifier.py`: update event schema + stdout/webhook backend
- `manga_watch/watchlist.py`: `watchlist add <url>` CLI
- `manga_watch/runner.py`: スケジューラ + notifier fan-out + run report logging
- `manga_watch/update_classification.py`: 更新種別と既定通知対象の分類ロジック
- `manga_watch/watchlist.json`: watchlist v2 sample
- `manga_watch/state.json`: state v2 sample
- `manga_watch/urls.txt`: legacy v1 migration input sample
- `tests/fixtures/<source>/<case>/`: raw response bundle + `manifest.json`

分類テストでは source ごとの代表例に加えて、main/bonus の曖昧ケースと bonus/announcement の suppress 維持ケースを確認します。

## Maintenance tips

- ローカル venv は常に `python3.12 -m venv .venv` で作る。Python `3.10` / `3.11` compatibility は追わない
- サイトの HTML が変わって検知が止まったら `.venv/bin/python -m manga_watch.check manga_watch/watchlist.json` を実行して例外を確認する
- silent failure が疑わしいときは `.venv/bin/python -m manga_watch.check --status` で stale / degraded / broken な作品を先に確認する
- migration や state contract を更新したら `.venv/bin/python -m unittest tests.test_sources tests.test_update_classification tests.test_check tests.test_status tests.test_watchlist tests.test_runner tests.test_migrate_v2 tests.test_backlog` を回す
- 未読の確認や既読化を手動で行いたいときは `.venv/bin/python -m manga_watch.backlog --unread-only` または `.venv/bin/python -m manga_watch.backlog --mark-read <work_id>` を使う
- run/retry 設定を変えたときは `.venv/bin/python -m unittest tests.test_sources tests.test_update_classification tests.test_check tests.test_status tests.test_watchlist tests.test_runner tests.test_migrate_v2 tests.test_backlog` で runner まで確認する
- 新しい source を足すときは `manga_watch/sources/` に adapter を追加し、`registry.py` の `REGISTERED_ADAPTERS` に登録して fixture / source tests を更新する
