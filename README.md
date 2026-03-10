# comic_crawler

Docker コンテナ 1 つで定期クロールし、generic notifier backend (`stdout` / webhook) に update event を送れる漫画更新監視アプリです。Discord surface は別契約で、daily notification を main channel、run report を run-report channel へ送ります。stdout/stderr はローカル運用ログとして引き続き使います。Issue #7 の cutover 以降、runtime は `watchlist/state v2` のみを読み書きし、Issue #17 以降は state v2 に更新履歴と未読イベントも保持します。

## Canonical docs

この repo の source of truth は次の 5 文書です。

- `doc/要件定義書.md`
- `doc/設計書.md`
- `spec.md` (document title: `SPEC.md`)
- `doc/運用手順書.md`
- `doc/受け入れテスト計画書.md`

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

| Source | `watchlist add` accepted inputs | Stored `seed_url` | `work_id` | `latest_key` |
| --- | --- | --- | --- | --- |
| ComicWalker | canonical series URL, episode URL | `https://comic-walker.com/detail/<series>` | `KC_XXXXXX_S` | `episodeCode` |
| webアクション | episode URL, RSS/Atom series feed URL | canonical episode URL または canonical series feed URL | `comic-action:<series_id>` | 最終到達 episode URL |
| Champion Cross | episode URL, series URL, series RSS URL | canonical episode URL / canonical series URL / canonical series RSS URL | `champion-cross:<series_hash>` | 最新 episode URL |
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
    "next_action": "Supported input types for comic-action: episode URL, series feed URL. Examples: https://comic-action.com/episode/123456 / https://comic-action.com/rss/series/123456"
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
- `DISCORD_BOT_TOKEN`: Discord main/run-report channel に送る bot token
- `DISCORD_MAIN_CHANNEL_ID`: daily notification の送信先 channel id
- `DISCORD_RUN_REPORT_CHANNEL_ID`: run report の送信先 channel id
- `DISCORD_INBOUND_ENABLED`: `true` のとき Discord main channel で `latest` / `fetch` コマンドを監視する。既定値は `true`
- `DISCORD_COMMAND_POLL_INTERVAL`: inbound command polling 間隔（秒）。既定値は `5`
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

Discord main channel では trim 後に本文がちょうど `latest` のメッセージで保存済み最新話一覧を返し、`fetch` のメッセージで手動巡回を受け付けます。
Discord 実機補助確認は test guild / test channel だけで `.venv/bin/python -m manga_watch.discord_real_e2e --case all --json` を実行します。これは primary gate ではなく、差異が出たときは先に mocked acceptance (`manga_watch.run_mocked_acceptance`) と formatter / builder を確認します。

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

## Repository layout

- `manga_watch/check.py`: watchlist/state v2 を読む checker
- `manga_watch/backlog.py`: 更新履歴 / 未読確認と既読化の最小 CLI
- `manga_watch/source_drift.py`: live source drift canary と fixture refresh 導線
- `manga_watch/status.py`: status CLI 向けの health 集約と text / JSON 表示
- `manga_watch/storage.py`: watchlist/state v2 validation と atomic write
- `manga_watch/discord_text.py`: Discord 表示向け label fallback / truncate helper
- `manga_watch/discord_outbound.py`: Discord daily notification / run report formatter と sender
- `manga_watch/notifier.py`: update event schema + stdout/webhook backend
- `manga_watch/watchlist.py`: `watchlist add <url>` CLI
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
