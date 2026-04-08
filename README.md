# comic_crawler

GCP では Cloud Run Job / Cloud Run Service / Cloud Scheduler を primary path として定期クロールし、generic notifier backend (`stdout` / webhook) に update event を送る漫画更新監視アプリです。Discord surface は別契約で、daily notification を main channel、run report を run-report channel へ送ります。stdout/stderr はローカル運用ログとして引き続き使います。Issue #7 の cutover 以降、runtime は `watchlist/state v2` のみを読み書きし、Issue #17 以降は state v2 に更新履歴と未読イベントも保持します。

## Canonical docs

この repo の source of truth は次の 6 文書です。

- `doc/要件定義書.md`
- `doc/設計書.md`
- `doc/gcp-deploy.md`
- `spec.md` (document title: `SPEC.md`)
- `doc/運用手順書.md`
- `doc/受け入れテスト計画書.md`

GCP runtime の backend env / Firestore schema / Secret Manager mapping / migration command は [`doc/gcp-runtime.md`](doc/gcp-runtime.md) を source of truth とします。

GCP の deploy / run / verify の source of truth は [`doc/gcp-deploy.md`](doc/gcp-deploy.md)、日常運用の確認手順は [`doc/運用手順書.md`](doc/運用手順書.md) を参照します。

## GCP runtime

- Cloud Run Job `comic-crawler-job`: 定期クロールと手動実行の実体
- Cloud Run Service `comic-crawler-service`: Discord interaction endpoint
- Cloud Scheduler helper: `python3 scripts/print_cloud_scheduler_job.py create|update --schedule "<cron>"`
- Scheduler force-run: `gcloud scheduler jobs run comic-crawler-scheduled-run --project=star-light-breaker --location=asia-northeast1`

root の受け入れ仕様書は Git 上の実ファイル名を `spec.md` にしていますが、文書名と cross-document 参照では `SPEC.md` と表記します。これは macOS などの case-insensitive filesystem で path 衝突を避けるためです。canonical docs や新しい issue / PR で `SPEC.md` と書かれている場合は、この `spec.md` を指します。旧 single-file spec への過去の言及は reference 扱いで、source of truth ではありません。

## Python 3.12 baseline

Docker / ローカル開発 / 将来の CI はすべて Python `3.12` を単一の runtime baseline とします。Docker image policy は `python:3.12-slim` に合わせ、ローカルツール向けには `.python-version` でも `3.12` を宣言します。Python `3.10` / `3.11` compatibility は要求しません。
`python3.12` が PATH に無い場合は、pyenv / asdf / OS package manager などで 3.12 を先に導入または選択してから `.venv` を作ってください。

## What it does

1. `manga_watch/watchlist.json` の watchlist v2 を読む
2. source adapter が `seed_url` を work descriptor に正規化する
3. source adapter が最新エピソードを取得する
4. `manga_watch/state.json` の state v2 と比較する
5. 更新があれば configured notifier backend(s) に update event を fan-out する
6. Discord main channel に daily notification を送り、Discord run-report channel に run report を送る
7. 同じ内容を必要に応じて標準出力 / 標準エラーにも残す

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

- `history`: `event_id`, `seen_at`, `latest` を持つ更新イベント列。`latest_key` が進んだ event には任意で `gap` を持てる
- `history[].gap.from_latest`: 直前 run で見えていた latest snapshot。複数話進行を exact に取れない source でも最低限この差分は残す
- `history[].gap.estimated_new_episode_count`: `episodeTitle` / `pageTitle` から話数を比較できたときだけ入る推定件数
- `unread.event_ids`: 未読イベントの source of truth
- `health`: `last_checked_at`, `last_success_at`, `consecutive_failures`
- root `discord_delivery.daily_notification`: Discord main channel 向け daily notification の durable dedupe / pending state

履歴保持は作品ごとの `history_retention` で上書きでき、未指定時は既定値 20 件です。trim するときは「未読は全件保持 + 既読は最新 N 件のみ保持」を守ります。必要なら watchlist 側で `health_policy.expected_interval_seconds` を指定し、stale 判定の期待巡回間隔を作品単位で上書きできます。詳細な schema と state contract は [root 受け入れ仕様書 (`spec.md`, 文書名: `SPEC.md`)](spec.md) を source of truth とします。

### backlog CLI

履歴と未読の確認には `python3 -m manga_watch.backlog` を使います。

```bash
python3 -m manga_watch.backlog --unread-only
python3 -m manga_watch.backlog --work-id KC_003913_S --json
python3 -m manga_watch.backlog --mark-read KC_003913_S
```

- `--json`: unread 数と履歴イベントを JSON で出力
- `--json` 出力の event には任意で `gap` が入り、`from_latest` と推定話数から multi-update gap を downstream に渡せる
- `--mark-read <work_id>`: その作品の現在未読を既読化し、保持ルールに従って履歴を trim

複数話進行の推定は source 固有 id ではなく title から行います。`第N話` / `Episode N` / `Ep.N` / `#N` のような番号が両端で取れるときだけ `estimated_new_episode_count` を出し、取れない source や title では `from_latest` だけを残す fallback にします。

更新分類の既定値は次の通りです。

- `main_story`: 既定で通知する
- `unknown`: fail-open で既定通知する
- `bonus`: 既定では notifier backend に通知しない
- `announcement`: 既定では notifier backend に通知しない

`main_story` と suppress 対象が衝突した場合は `unknown` に倒し、`bonus` と `announcement` だけが衝突した場合は suppress 側に残します。

watchlist の `notification_policy` は classification default の上に適用されます。

- `allowed_update_types` に明示できる値は `main_story`, `bonus`, `announcement`, `unknown` のみ
- typo や未対応値を入れた watchlist は validation error として reject する
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
- runner は delivery 前に state v2 の `notification_outbox` へ event を保存し、pending entry を次回 run で automatic replay します。manual replay は `python3 -m manga_watch.replay_outbox` で実行できます。
- `stdout` backend は 1 event = 1 JSON line を標準出力へ flush します。
- `webhook` backend は 1 event ごとに JSON POST します。HTTP `2xx` だけを success とし、それ以外の status / timeout / transport error は failure として run を失敗扱いにします。
- `MANGA_WATCH_NOTIFIER_BACKENDS=stdout,webhook` のように comma-separated で複数 backend を指定すると、同じ event を backend ごとに fan-out し、失敗した backend だけ outbox に残します。

## Supported sources

| Source | Discord `/add` accepted inputs | Stored `seed_url` | `work_id` | `latest_key` |
| --- | --- | --- | --- | --- |
| ComicWalker | canonical series URL, episode URL | `https://comic-walker.com/detail/<series>` | `KC_XXXXXX_S` | `episodeCode` |
| webアクション | episode URL, RSS/Atom series feed URL | canonical episode URL または canonical series feed URL | `comic-action:<series_id>` | 最終到達 episode URL |
| 少年ジャンプ＋ | episode URL, RSS/Atom series feed URL | `https://shonenjumpplus.com/rss/series/<series_id>` | `shonenjumpplus:<series_id>` | 最新 episode URL |
| Champion Cross | episode URL, series URL, series RSS URL | canonical episode URL / canonical series URL / canonical series RSS URL | `champion-cross:<series_hash>` | 最新 episode URL |
| マガポケ | title URL, episode URL | `https://pocket.shonenmagazine.com/title/<title_id>` | `magapoke:<title_id>` | 最新 episode URL |
| Kakuyomu | work URL, episode URL | 入力 URL のまま | `kakuyomu:<numeric_work_id>` | 最新 episode id |

Phase 1 では source ごとの capability 差を隠しません。作品追加で受け付ける URL 種別は上の表だけです。内部の source capability / normalize 契約もこの表を source of truth とします。

`Supported sources` にまだ入っていない host/domain の legacy/current 判定や successor mapping は、runtime contract を直接広げる前に `doc/` 配下の triage note へ残します。`comic-valkyrie.com -> comic-brise.com` の判定根拠は [`doc/source-triage-comic-valkyrie-comic-brise.md`](doc/source-triage-comic-valkyrie-comic-brise.md) を参照してください。

## Discord `/add`

作品追加の正式導線は Discord slash command `/add url:<作品URL>` です。内部では shared add logic が URL を normalize し、duplicate / unsupported 判定を行ってから watchlist を更新します。

成功時は normalize preview 相当の結果から、登録された `work_id` と `seed_url` を返します。

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

エラー時は shared add logic の `kind`, `message`, `next_action` をもとに応答します。`kind` は少なくとも `invalid_url`, `unsupported_source`, `unsupported_url_type`, `normalize_failed` を使います。

```json
{
  "action": "error",
  "error": {
    "kind": "unsupported_url_type",
    "message": "comic-action does not support this URL type for work registration: https://comic-action.com/series/123",
    "next_action": "Supported input types for comic-action: episode URL, series feed URL. Examples: https://comic-action.com/episode/123456 / https://comic-action.com/rss/series/123456"
  }
}
```

## GCP run / verify

GCP での運用は Cloud Run Job / Cloud Run Service / Cloud Scheduler を基準にします。詳細な resource contract は [`doc/gcp-deploy.md`](doc/gcp-deploy.md) を見てください。

```bash
gcloud run jobs execute comic-crawler-job \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --wait

gcloud scheduler jobs run comic-crawler-scheduled-run \
  --project=star-light-breaker \
  --location=asia-northeast1

gcloud run jobs logs read comic-crawler-job \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --limit=20

gcloud run services logs read comic-crawler-service \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --limit=20
```

- Cloud Run Job は手動 run と定期 run の実行主体
- Cloud Run Service は `latest` / `fetch` を受ける Discord interaction endpoint
- Cloud Scheduler helper script は `create` / `update` の command shape を出すので、Scheduler 側の設定確認に使う
- 詳細な日次確認は [`doc/運用手順書.md`](doc/運用手順書.md) を参照する

## Legacy / local fallback

`docker compose` は GCP の代替ではなく、ローカル検証や一時的な fallback 用です。

1. `.env.example` を `.env` にコピーして notifier 設定を入れる
2. 必要なら `manga_watch/watchlist.json` を編集する
3. 起動する

```bash
docker compose up -d --build
docker compose logs -f
```

compose は `manga_watch/watchlist.json` を read-only mount し、state v2 は volume `crawler-data` に保存します。

### Legacy local update

ローカル fallback を更新するときは、repo root で次を実行します。

```bash
git pull --ff-only origin main
docker compose up -d --build
docker compose ps
docker compose logs --tail 80 comic-crawler
```

- `git pull --ff-only origin main`: ローカル `main` を `origin/main` に fast-forward する
- `docker compose up -d --build`: 新しい image を build してコンテナを再作成する
- `docker compose ps`: `comic-crawler` が `Up` になっていることを確認する
- `docker compose logs --tail 80 comic-crawler`: startup run に configuration / state / delivery failure が出ていないことを確認する

GCP production runtime の deploy / rollback はこの compose 手順ではなく、GitHub Actions の `Deploy Production` / `Rollback Production` workflow を source of truth とします。production deploy contract と確認コマンドは [`doc/gcp-deploy.md`](doc/gcp-deploy.md)、日常運用は [`doc/運用手順書.md`](doc/運用手順書.md) を参照してください。

### Environment variables

- `MANGA_WATCH_NOTIFIER_BACKENDS`: required。comma-separated backend list。現在値は `stdout`, `webhook`
- `MANGA_WATCH_WEBHOOK_URL`: `webhook` backend を使うときの POST 先 URL
- `MANGA_WATCH_WEBHOOK_TIMEOUT`: webhook timeout 秒。既定値は `10`
- `DISCORD_BOT_TOKEN`: Discord main/run-report channel に送る bot token
- `DISCORD_APPLICATION_ID`: slash command 登録先の application id。省略時は bot token で `/oauth2/applications/@me` を引いて解決する
- `DISCORD_GUILD_ID`: slash command を test guild scope で登録したいときの guild id。未指定なら global command を更新する
- `DISCORD_MAIN_CHANNEL_ID`: daily notification の送信先 channel id
- `DISCORD_RUN_REPORT_CHANNEL_ID`: run report の送信先 channel id
- `DISCORD_INBOUND_ENABLED`: local fallback の polling inbound を有効化する。既定値は `true`
- `DISCORD_COMMAND_POLL_INTERVAL`: local fallback の inbound polling 間隔（秒）。既定値は `5`
- `DISCORD_APPLICATION_PUBLIC_KEY`: Cloud Run Service の Discord interaction verification に使う public key
- `MANGA_WATCH_GITHUB_TOKEN`: `/add` で未対応媒体を受けたときに GitHub Issue を自動作成するための token
- `MANGA_WATCH_GITHUB_REPOSITORY`: 未対応媒体の対応候補 Issue を作る GitHub repository。例: `kentoku24/comic_crawler`
- `MANGA_WATCH_GITHUB_API_BASE_URL`: GitHub API base URL。既定値は `https://api.github.com`
- `MANGA_WATCH_INSECURE_DISABLE_VERIFICATION`: local のみで verification を無効化する escape hatch。production では使わない
- `MANGA_WATCH_FETCH_BACKEND`: Cloud Run Service の `fetch` 実行先。`coordinator` または `cloud-run-job`。既定値は `coordinator`
- `MANGA_WATCH_GCP_PROJECT`: `MANGA_WATCH_FETCH_BACKEND=cloud-run-job` のときに使う GCP project
- `MANGA_WATCH_CLOUD_RUN_REGION`: `MANGA_WATCH_FETCH_BACKEND=cloud-run-job` のときに使う Cloud Run region。既定値は `asia-northeast1`
- `MANGA_WATCH_CLOUD_RUN_JOB_NAME`: `MANGA_WATCH_FETCH_BACKEND=cloud-run-job` のときに起動する Job 名。既定値は `comic-crawler-job`
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
.venv/bin/python -m manga_watch.source_drift
.venv/bin/python -m manga_watch.source_drift --format json
.venv/bin/python -m unittest tests.test_source_drift tests.test_sources tests.test_update_classification tests.test_check tests.test_status tests.test_watchlist tests.test_runner tests.test_backlog
.venv/bin/python -m manga_watch.run_mocked_acceptance
.venv/bin/python -m manga_watch.discord_real_e2e --case all --json
```

runner をローカル起動する場合は notifier 環境変数と Discord outbound 環境変数を入れてから実行します。

```bash
export MANGA_WATCH_NOTIFIER_BACKENDS=stdout
export DISCORD_BOT_TOKEN=...
export DISCORD_MAIN_CHANNEL_ID=...
export DISCORD_RUN_REPORT_CHANNEL_ID=...
.venv/bin/python -m manga_watch.runner
.venv/bin/python -m manga_watch.replay_outbox
```

Discord main channel では trim 後に本文がちょうど `latest` のメッセージで保存済み最新話一覧を返し、`fetch` のメッセージで手動巡回を受け付けます。Discord interaction endpoint では slash command として `/add url:<作品URL>` も受け付け、shared add logic で対応できる URL のみクロール対象へ追加します。`MANGA_WATCH_GITHUB_TOKEN` と `MANGA_WATCH_GITHUB_REPOSITORY` が設定されている場合、`unsupported_source` は追加失敗のまま GitHub Issue を自動作成し、「対応候補として記録した」と返信します。
Cloud Run Service の interaction endpoint では slash command として `/latest` `/fetch` `/add` `/remove` を扱います。`/remove` は ephemeral な select menu と confirm/cancel button を返し、watchlist と state から対象作品を完全削除します。
Discord 実機補助確認は test guild / test channel だけで `.venv/bin/python -m manga_watch.discord_real_e2e --case all --json` を実行します。これは primary gate ではなく、差異が出たときは先に mocked acceptance (`manga_watch.run_mocked_acceptance`) と formatter / builder を確認します。

Cloud Run Service の Discord interaction endpoint をローカルで起動する場合は、署名検証用の public key に加えて command registration 用の bot token を入れて `python -m manga_watch.run_service` を使います。service startup では `/latest` `/fetch` `/add` `/remove` の command 定義を Discord へ idempotent に登録し、登録に失敗した場合は fail-fast で起動を中断します。`DISCORD_GUILD_ID` を入れると guild command、未指定なら global command を更新します。

```bash
export DISCORD_BOT_TOKEN=...
export DISCORD_APPLICATION_ID=...
export DISCORD_GUILD_ID=...  # optional
export DISCORD_APPLICATION_PUBLIC_KEY=...
export MANGA_WATCH_GITHUB_TOKEN=...        # optional
export MANGA_WATCH_GITHUB_REPOSITORY=...   # optional
export MANGA_WATCH_INSECURE_DISABLE_VERIFICATION=false
.venv/bin/python -m manga_watch.run_service
```

startup registration だけを手動で確認したいときは次を使います。service と同じ env を読み、planned payload の表示や再登録の fallback に使えます。

```bash
.venv/bin/python scripts/register_discord_commands.py --dry-run
.venv/bin/python scripts/register_discord_commands.py
```

`manga_watch.run_service` は Slash Command 用の `POST /` に加えて、署名検証なしの lightweight health check として `GET /healthz` を返します。Cloud Run の scale-to-zero を完全には防げませんが、Cloud Scheduler から `15` 分おきに `GET /healthz` を送って warm 状態を維持しやすくできます。不十分なら、運用しながら間隔を短くします。

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

## Source Drift Canary

fixture regression だけでは拾えない upstream HTML / embedded JSON drift を早めに見るために、各 source に 1 本ずつ live canary を持たせています。

```bash
.venv/bin/python -m manga_watch.source_drift
.venv/bin/python -m manga_watch.source_drift --source comic-action
.venv/bin/python -m manga_watch.source_drift --format json
```

- exit code `0`: 選択した source の canary がすべて通過
- exit code `1`: 少なくとも 1 source で drift。`fixtureBundle`, `monitoredSignals`, `nextAction` を見て fixture refresh に進む
- live URL は `manga_watch/source_drift.py` の canary contract が source of truth

| Source | Seed URL | Monitored URL / signal | Fixture bundle |
| --- | --- | --- | --- |
| ComicWalker | `https://comic-walker.com/detail/KC_003913_S` | canonical series page の `__NEXT_DATA__`、同一 series の最新 `episodeCode`、最新 episode page title parse | `tests/fixtures/comic-walker/normal` |
| webアクション | `https://comic-action.com/episode/2550689798784879524` | seed episode page の `series_id`、`nextReadableProductUri`、最終到達 episode page title parse | `tests/fixtures/comic-action/normal` |
| 少年ジャンプ＋ | `https://shonenjumpplus.com/episode/17107419589191805801` | seed episode page 由来の stable `series_id`、series RSS の最新 episode URL、最新 episode page title parse | `tests/fixtures/shonenjumpplus/normal` |
| マガポケ | `https://pocket.shonenmagazine.com/title/03021` | title page の RSS feed URL、title page の次回更新ラベル、series RSS の最新 episode URL/title | `tests/fixtures/magapoke/normal` |
| Kakuyomu | `https://kakuyomu.jp/works/16818093092974667738/episodes/822139844009936710` | work page の `__NEXT_DATA__`、最新 episode id/title、最新 episode page title | `tests/fixtures/kakuyomu/normal` |

drift を検知したら、次の順で進めます。

1. `.venv/bin/python -m manga_watch.source_drift --source <source>` で再実行し、どの signal が落ちたかを固定する
2. 対応する `tests/fixtures/<source>/normal` を、adapter が実際に辿る順序で raw response ごと取り直す
3. `manifest.json` の期待値を更新し、落ちた signal に対応する parser contract を見直す
4. `.venv/bin/python -m unittest tests.test_source_drift tests.test_sources tests.test_check` を回して fixture refresh と parser contract の両方を確認する

## Adding a source adapter

`manga_watch/sources/registry.py` の `REGISTERED_ADAPTERS` が adapter registration の single source of truth です。

1. `manga_watch/sources/` に concrete `SourceAdapter` module を追加する
2. `manga_watch/sources/registry.py` の `REGISTERED_ADAPTERS` に adapter instance を追加する
3. `manga_watch/source_drift.py` に live canary target URL と monitored signal contract を追加する
4. fixture / state contract に影響がある場合は `tests/fixtures/` や関連 test を更新する
5. `.venv/bin/python -m unittest tests.test_source_drift tests.test_sources tests.test_check tests.test_runner` を実行する

2 を忘れると `tests.test_sources.SourceAdapterTests.test_registry_covers_every_concrete_adapter_module` が失敗します。
source expansion の Issue / PR review には [`docs/source-expansion-review-rubric.md`](docs/source-expansion-review-rubric.md) を使って、implementation readiness と merge readiness を分けて評価してください。

## Repository layout

- `manga_watch/check.py`: watchlist/state v2 を読む checker
- `manga_watch/backlog.py`: 更新履歴 / 未読確認と既読化の最小 CLI
- `manga_watch/source_drift.py`: live source drift canary と fixture refresh 導線
- `manga_watch/status.py`: status CLI 向けの health 集約と text / JSON 表示
- `manga_watch/storage.py`: watchlist/state v2 validation と atomic write
- `manga_watch/discord_text.py`: Discord 表示向け label fallback / truncate helper
- `manga_watch/discord_outbound.py`: Discord daily notification / run report formatter と sender
- `manga_watch/notifier.py`: update event schema + stdout/webhook backend
- `manga_watch/watchlist.py`: Discord `/add` が使う shared add logic と source capability 定義
- `manga_watch/runner.py`: スケジューラ + notifier fan-out + Discord outbound orchestration
- `manga_watch/update_classification.py`: 更新種別と既定通知対象の分類ロジック
- `manga_watch/watchlist.json`: watchlist v2 sample
- `manga_watch/state.json`: state v2 sample
- `tests/fixtures/<source>/<case>/`: raw response bundle + `manifest.json`

分類テストでは source ごとの代表例に加えて、main/bonus の曖昧ケースと bonus/announcement の suppress 維持ケースを確認します。

## Maintenance tips

- ローカル venv は常に `python3.12 -m venv .venv` で作る。Python `3.10` / `3.11` compatibility は追わない
- サイトの HTML が変わって検知が止まったら `.venv/bin/python -m manga_watch.check manga_watch/watchlist.json` を実行して例外を確認する
- upstream drift が silent に見えるときは `.venv/bin/python -m manga_watch.source_drift` を先に回して、source ごとの canary signal がまだ生きているか確認する
- silent failure が疑わしいときは `.venv/bin/python -m manga_watch.check --status` で stale / degraded / broken な作品を先に確認する
- state contract を更新したら `.venv/bin/python -m unittest tests.test_source_drift tests.test_sources tests.test_update_classification tests.test_check tests.test_status tests.test_watchlist tests.test_runner tests.test_backlog` を回す
- canonical docs の mocked acceptance 契約をまとめて確認したいときは `.venv/bin/python -m manga_watch.run_mocked_acceptance` を使う
- 未読の確認や既読化を手動で行いたいときは `.venv/bin/python -m manga_watch.backlog --unread-only` または `.venv/bin/python -m manga_watch.backlog --mark-read <work_id>` を使う
- run/retry 設定を変えたときは `.venv/bin/python -m unittest tests.test_source_drift tests.test_sources tests.test_update_classification tests.test_check tests.test_status tests.test_watchlist tests.test_runner tests.test_backlog` で runner まで確認する
- 新しい source を足すときは `manga_watch/sources/` に adapter を追加し、`registry.py` の `REGISTERED_ADAPTERS` と `manga_watch/source_drift.py` の canary contract を更新して fixture / source tests を更新する
