# comic_crawler / spec

## Runtime baseline

- ローカル実行 / Docker / 将来の CI は Python `3.12` を単一の runtime baseline とする
- Docker image policy は `python:3.12-slim` に合わせ、ローカル virtualenv は `python3.12` で作る
- Python `3.10` / `3.11` compatibility は required ではない

## Glossary

- **watchlist v2**: `manga_watch/watchlist.json`
- **state v2**: `manga_watch/state.json`
- **checker**: `python3 -m manga_watch.check <watchlist.json>`
- **runner**: `python3 -m manga_watch.runner`
- **work_id**: 作品単位で不変な識別子
- **latest_key**: 更新検知と通知重複排除の基準キー

## Purpose

複数の漫画サイトを作品単位で監視し、新しいエピソードが公開されたら通知する。Issue #7 の cutover 以降、runtime が正として扱う永続データは watchlist/state v2 のみで、v1 (`urls.txt`, `state.json` v1) は migration 入力と rollback 用 backup に限定する。

## Runtime Inputs

### Watchlist file

- ローカル既定値: `manga_watch/watchlist.json`
- env override: `MANGA_WATCH_WATCHLIST=/path/to/watchlist.json`
- legacy env fallback: `MANGA_WATCH_URLS=/path/to/watchlist.json`
- Docker 既定値: `/app/manga_watch/watchlist.json`

### Watchlist schema (v2)

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

### Watchlist field rules

- `id`: stable `work_id`。通知ポリシーや state はこの値に紐づく
- `source`: adapter registry の source 名
- `seed_url`: adapter normalize に再投入できる canonical seed
- `enabled`: `false` のとき checker はその作品を巡回しない
- `history_retention`: 任意。作品ごとの既読履歴保持件数。未指定時は既定値 `20`
- `notification_policy.mode`: `all` / `important_only` / `mute`。v2 migration では既定値 `all`
- `notification_policy.allowed_update_types`: 明示設定が無ければ `null`。`null` でないときは mode より優先する
- `notification_policy.mode=all`: classification default を bypass して全 `update_type` を通知する
- `notification_policy.mode=important_only`: `main_story` と `unknown` を通知する
- `notification_policy.mode=mute`: どの `update_type` も通知しない
- `health_policy.expected_interval_seconds`: stale 判定用の期待巡回間隔。未指定時は `CRAWL_INTERVAL`、無ければ `CRAWL_SCHEDULE`、さらに無ければ既定 cron (`0 19 * * *`) から導出する

### `watchlist add` CLI

```bash
python3 -m manga_watch.watchlist add <url>
python3 -m manga_watch.watchlist add <url> --watchlist /path/to/watchlist.json
```

- 出力は常に JSON
- `action=added` / `duplicate` は exit code `0`
- `action=error` は exit code `1`
- 書き込み前に normalize preview と duplicate 判定を行う
- duplicate は `work_id` 単位で判定する

#### Response contract

成功時:

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

重複時:

```json
{
  "action": "duplicate",
  "input_url": "https://kakuyomu.jp/works/123",
  "watchlist_path": "manga_watch/watchlist.json",
  "entry": {"id": "kakuyomu:123"},
  "existing": {"id": "kakuyomu:123"},
  "work_count": 1
}
```

エラー時:

```json
{
  "action": "error",
  "input_url": "https://comic-action.com/series/123",
  "watchlist_path": "manga_watch/watchlist.json",
  "error": {
    "kind": "unsupported_url_type",
    "message": "...",
    "next_action": "..."
  }
}
```

`error.kind` は少なくとも `invalid_url`, `unsupported_source`, `unsupported_url_type`, `normalize_failed`, `load_watchlist`, `save_watchlist` を使う。

#### Capability matrix

| Source | accepted input URL types | canonical / stored `seed_url` |
| --- | --- | --- |
| ComicWalker | canonical series URL, episode URL | `https://comic-walker.com/detail/<series>` |
| webアクション | episode URL, RSS/Atom series feed URL | canonical episode URL または canonical series feed URL |
| Kakuyomu | work URL, episode URL | 入力 URL のまま |

Phase 1 はこの matrix を source of truth とし、未記載の URL 種別は `unsupported_url_type` にする。

### work_id contract

- ComicWalker: `KC_XXXXXX_S`
- webアクション: `comic-action:<series_id>`
- Kakuyomu: `kakuyomu:<numeric_work_id>`

`work_id` は source ごとに 1 作品 1 値で不変とし、seed URL の表現揺れでは変わらない。

## State

### State file

- ローカル既定値: `manga_watch/state.json`
- env override: `MANGA_WATCH_STATE=/path/to/state.json`
- Docker 既定値: `/data/state.json`

### State schema (v2)

```json
{
  "version": 2,
  "works": {
    "KC_003913_S": {
      "latest": {
        "source": "comic-walker",
        "work_id": "KC_003913_S",
        "latest_key": "KC_0039130008900011_E",
        "url": "https://comic-walker.com/detail/KC_003913_S/episodes/KC_0039130008900011_E?episodeType=latest",
        "series": "KC_003913_S",
        "series_title": "蜘蛛ですが、なにか？",
        "episode_code": "KC_0039130008900011_E",
        "episode_title": "第77話その2",
        "update_type": "main_story",
        "classification_reason": "episode_title matched main-story numbering",
        "default_notify": true
      },
      "history": [
        {
          "event_id": "KC_0039130008800011_E",
          "seen_at": 1769830610,
          "latest": {
            "source": "comic-walker",
            "work_id": "KC_003913_S",
            "latest_key": "KC_0039130008800011_E",
            "series_title": "蜘蛛ですが、なにか？",
            "episode_code": "KC_0039130008800011_E",
            "episode_title": "第77話その1"
          }
        }
      ],
      "unread": {
        "event_ids": ["KC_0039130008800011_E"]
      },
      "health": {
        "last_checked_at": 1769917010,
        "last_success_at": 1769917010,
        "consecutive_failures": 0
      }
    }
  },
  "last_run_at": 1769917010
}
```

### State field rules

- `latest`: 現在の最新話 snapshot。未成功作品では `{}` を許容する
- `history`: 更新イベント列。各 event は `event_id`, `seen_at`, `latest` を持ち、必要に応じて `gap` を持てる
- `history[].event_id`: `latest_key` をそのまま使う。作品ごとに一意で、履歴追加の idempotency key でもある
- `history[].seen_at`: その更新 event を checker が検知した UNIX timestamp
- `history[].latest`: event 時点の latest snapshot
- `history[].gap.from_latest`: 直前 run で見えていた latest snapshot。multi-update gap を exact に取れない場合でも最低限ここは埋める
- `history[].gap.estimated_new_episode_count`: `episodeTitle` / `pageTitle` の両端から話数を抽出できたときだけ入る推定件数
- `history[].gap.multiple_updates`: 推定件数が 2 以上なら `true`、1 件なら `false`、話数推定不能なら `null` 相当で保持する
- `history[].gap.estimation_basis`: `episode_title_number` または `previous_latest_only`
- `unread.event_ids`: 未読 event id の source of truth。`unread_count` は永続化しない
- `health.last_checked_at`: 直近でその作品を巡回した UNIX timestamp
- `health.last_success_at`: 直近で成功した UNIX timestamp
- `health.consecutive_failures`: 連続失敗回数
- `last_run_at`: checker 全体の最終実行時刻

### Derived health states

status CLI と後続の通知設計では、state v2 に保存された `health` を次の離散状態へ射影して使う。

- `healthy`: 連続失敗がなく、`last_success_at` が stale 窓内にある
- `degraded`: `consecutive_failures` が 1 以上 3 未満
- `broken`: `consecutive_failures` が 3 以上
- `stale`: 連続失敗は無いが、`now - last_success_at > expected_interval_seconds * 2.0`
- `pending`: まだ成功実績が無く、`last_checked_at` / `last_success_at` が `null`

`stale` は固定 48 時間ではなく、作品ごとの `health_policy.expected_interval_seconds` または runtime cadence から求める。

### latest_key contract

- ComicWalker: `episode_code`
- webアクション: 最終到達 episode URL
- Kakuyomu: 最新 episode id

`latest_key` は「更新検知」と「通知 idempotency」の唯一の比較キーであり、タイトルや page title の改善だけでは変えない。

### History retention rule

- 作品ごとに `history_retention` を持てる。未指定時は既定値 `20`
- trim 時は `unread.event_ids` に含まれる未読 event を全件保持する
- 既読 event は新しいものから最大 `history_retention` 件だけ保持する
- 未読 state は `unread.event_ids` を source of truth にするため、trim しても unread marker が壊れない

## Core behavior

### Checker execution

```bash
python3 -m manga_watch.check manga_watch/watchlist.json
```

- checker は常に JSON を出力する
- watchlist は入力順で処理し、`updates` の順序も watchlist 順で deterministic にする
- source fetch は `MANGA_WATCH_HTTP_WORKERS` 本で並列実行できるが、state 更新順・`updates`・`errors.sources` は watchlist 入力順で deterministic に固定する
- `latest_key` が変わったときだけ `updates` に積む
- `latest_key` が変わったとき、未登録の `event_id=latest_key` を `history` に 1 回だけ追加する
- 新規 `history` event には `gap.from_latest=直前 latest` を保存する。これが backlog / unread で「latest 1 件以上」の入力になる
- `episodeTitle` / `pageTitle` の両端から `第N話` / `Episode N` / `Ep.N` / `#N` を比較できる場合だけ `gap.estimated_new_episode_count` を埋める
- 話数推定不能な source や title では `gap.estimation_basis=previous_latest_only` の fallback にし、exact count は出さない
- 同じ `event_id` を再検知しても履歴は重複させない。必要なら event snapshot だけ補完更新する
- 新規 event が履歴に追加されたときだけ `unread.event_ids` にその id を追加する
- `latest_key` が同じで `seriesTitle` / `episodeTitle` / `pageTitle` / 補足 metadata だけ改善された場合は silent merge する
- state.latest / history.latest には `update_type`, `classification_reason`, `default_notify` を含める
- checker の `updates[]` には top-level `notification` を含める。`should_notify=false` は「更新あり / backend 通知なし」を意味し、`updates=[]` の「更新なし」と区別できるようにする
- source ごとの parser/runtime failure は `errors.sources` に積み、成功した作品の state 更新は継続する
- retry 対象は transport error / timeout / HTTP `429` / `5xx` に限定する
- HTTP `404`、unsupported URL、parse error は即失敗として `errors.sources` に積む
- 同一 host への同時 request 数は `MANGA_WATCH_HTTP_WORKERS_PER_HOST` で抑制する
- 失敗した作品も `health.last_checked_at` と `health.consecutive_failures` は更新する
- watchlist/state の読み込みや state 保存のような run-level failure は `errors.run` に記録し、`CheckRunError` として返す

### Status CLI

```bash
python3 -m manga_watch.check --status
python3 -m manga_watch.check --status --format json
```

- `--status` は crawl を実行せず、watchlist/state v2 から現在の監視状態を表示する
- text 出力は監視件数、最終 run 時刻、最終成功時刻、health counts、失敗中作品、stale 作品、作品別 health を含む
- JSON 出力は同じ情報を `summary` と `works[]` に分けて返す
- `works[].health` には `state`, `last_checked_at`, `last_success_at`, `consecutive_failures`, `expected_interval_seconds`, `stale_after_seconds` を含む

## Backlog CLI

```bash
python3 -m manga_watch.backlog --unread-only
python3 -m manga_watch.backlog --work-id KC_003913_S --json
python3 -m manga_watch.backlog --mark-read KC_003913_S
```

- `--unread-only`: 未読がある作品だけ表示する
- `--work-id`: 対象作品を 1 つに絞る
- `--json`: 機械可読な履歴 / unread summary を出す。event に `gap` があればそのまま含める
- `--mark-read <work_id>`: その作品の `unread.event_ids` を空にして保存し、保持ルールに従って既読履歴を trim する

### Multi-update gap capability

- ComicWalker / Kakuyomu: `episodeTitle` / `pageTitle` に比較可能な番号が含まれるときは推定話数を出せる
- comic-action: `latest_key` は episode URL で、adapter contract だけでは series 内の差分件数を導けない。title から番号が取れない場合は `previous_latest_only` fallback になる
- どの source でも exact な全話遡及取得はしない。`gap.from_latest` と optional な推定件数を downstream 入力として使う

### Checker error schema

```json
{
  "errors": {
    "sources": [
      {
        "url": "https://example.com/work",
        "id": "work-1",
        "phase": "fetch_latest",
        "kind": "parse",
        "errorType": "SourceParseError",
        "message": "..."
      }
    ],
    "run": [
      {
        "stage": "save_state",
        "kind": "runtime",
        "errorType": "OSError",
        "message": "disk full"
      }
    ]
  }
}
```

### Atomic state writes

state 保存は `temp file -> json dump -> flush -> fsync(file) -> replace -> fsync(directory)` を必須とする。v2 cutover で durability を落とさない。

## Runner

```bash
python3 -m manga_watch.runner
```

必要な設定:

- `MANGA_WATCH_NOTIFIER_BACKENDS`
- `MANGA_WATCH_WEBHOOK_URL` (`webhook` backend を使うとき)
- `MANGA_WATCH_WEBHOOK_TIMEOUT`
- `TZ`。既定値は `Asia/Tokyo`
- `CRAWL_SCHEDULE` または `CRAWL_INTERVAL`
- `RUN_ON_STARTUP`
- `MANGA_WATCH_WATCHLIST` または `MANGA_WATCH_URLS`
- `MANGA_WATCH_STATE`
- `MANGA_WATCH_HTTP_TIMEOUT`
- `MANGA_WATCH_HTTP_RETRIES`
- `MANGA_WATCH_HTTP_RETRY_BACKOFF`
- `MANGA_WATCH_HTTP_WORKERS`
- `MANGA_WATCH_HTTP_WORKERS_PER_HOST`

### Notification backends

- `MANGA_WATCH_NOTIFIER_BACKENDS` は required。comma-separated で `stdout`, `webhook` を並べる
- runner は同じ update event を指定順に全 backend へ fan-out する
- `stdout` backend は 1 event = 1 JSON line を標準出力へ書き込んで flush する
- `webhook` backend は 1 event ごとに JSON POST する
- webhook success は HTTP `2xx` のみ。`3xx`/`4xx`/`5xx`、timeout、transport error は failure
- どれか 1 backend でも failure した run は失敗扱いにし、failure report を stderr に出す
- fan-out 中に一部 backend が成功してから別 backend が失敗し得るため、consumer は duplicate を `event_id` で dedupe する
- current implementation は persisted outbox や automatic replay を持たない。checker が state を進めた後の delivery failure は manual replay が必要

### Update event schema

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
    "classification_reason": "episode_title matched main-story numbering",
    "default_notify": true
  }
}
```

- `event_id` は `sha256(work_id + "\n" + latest_key)` を `"<work_id>:<digest>"` にした stable id
- `detected_at` は UTC の RFC 3339 timestamp
- `from` / `to` は snake_case に正規化した snapshot
- `notification` は watchlist policy を適用した effective decision。`default_notify=false` な update でも `mode=all` や explicit `allowed_update_types` で `should_notify=true` になり得る
- runner は `notification.should_notify=true` の update だけを backend に送る。`notification` が無い legacy payload だけ `default_notify` / update-type default に fallback する
- suppressed update は state と run report には残るが backend には送らない

### Classification defaults and notification policy

- `main_story`: 既定通知対象
- `unknown`: fail-open で既定通知対象
- `bonus`: 既定抑制対象
- `announcement`: 既定抑制対象
- `main_story` と suppress 対象が衝突した場合は `unknown` に倒す
- `bonus` と `announcement` だけが衝突した場合は suppress 側に残す
- `allowed_update_types` が明示設定されていれば、それをその作品の最終通知判定として使う。空 list も有効で、その場合は全 suppress
- `allowed_update_types` に許可される値は `main_story`, `bonus`, `announcement`, `unknown` のみ
- typo や未対応値を含む watchlist は validation error にする
- `allowed_update_types=null` のときだけ `mode` を使う
- `mode=all`: 全 `update_type` を通知し、classification default を bypass する
- `mode=important_only`: `main_story` と `unknown` だけを通知する
- `mode=mute`: 全 suppress
- suppressed update も state と run report には残し、run report には `通知対象件数` と `通知抑制件数` を含める

## Reader / Writer compatibility matrix

| Component | Reads v1 | Reads v2 | Writes v1 | Writes v2 |
| --- | --- | --- | --- | --- |
| `python3 -m manga_watch.migrate_v2` | yes | no | no | yes |
| `python3 -m manga_watch.check` | no | yes | no | yes (`state.json`) |
| `python3 -m manga_watch.backlog` | no | yes | no | yes (`state.json`, mark-read 時のみ) |
| `python3 -m manga_watch.runner` | no | yes | no | yes (`state.json`) |

- runtime は v1 / v2 混在運用をサポートしない
- rollback は cutover 時に作成した `rollback-manifest.json` に従って data backup と pre-cutover runtime/image の両方を戻す

## One-time migration

### CLI

```bash
docker compose images comic-crawler

python3 -m manga_watch.migrate_v2 \
  --watchlist-v1 manga_watch/urls.txt \
  --state-v1 /data/state.json \
  --watchlist-v2 manga_watch/watchlist.json \
  --state-v2 /data/state.json \
  --backup-dir /data/migration-backups/20260308T080000Z \
  --pre-cutover-image-ref sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

### Mapping rules

- watchlist v1 の各 URL を adapter normalize し、`id`, `source`, `seed_url`, `enabled=true`, `notification_policy.mode=all`, `allowed_update_types=null` を生成する
- 同じ `work_id` が 2 回以上出たら migration を失敗させる
- v1 state に対応 entry がある場合:
  - `latest` は v1 snapshot を引き継ぎつつ `source`, `work_id`, `latest_key` を補う
  - `health.last_checked_at` / `last_success_at` は `seenAt`、無ければ `lastRunAt`
  - `consecutive_failures` は `0`
- v1 state に対応 entry が無い場合:
  - `latest` は `{}`
  - `history` は `[]`
  - `unread.event_ids` は `[]`
  - `health.last_checked_at` / `last_success_at` は `null`
  - `consecutive_failures` は `0`
- watchlist に無い v1 state entry は `orphaned_state_ids` として report し、v2 には持ち込まない

### Backup / cutover / rollback

#### Backup

- migration CLI は入力 `urls.txt` と v1 `state.json` を `backup-dir` に copy2 し、`backup-dir/rollback-manifest.json` を書く
- backup dir は timestamped path を使い、前回 backup を上書きしない
- `rollback-manifest.json` は次を記録する
  - `data_backups[]`: `kind`, `source_path`, `backup_path`, `restore_to_path`
  - `cutover_outputs[]`: 生成した v2 `watchlist.json` / `state.json` の path
  - `pre_cutover_runtime`: `service`, `image_ref`, `image_ref_kind`, `git_commit`, `git_commit_captured_via`, `git_dirty`
  - `rollback_prechecks`, `rollback_steps`, `rollback_smoke_checks`
- `pre_cutover_runtime.image_ref` は rollback 時に実際に戻せる immutable identifier を使う。`repo@sha256:...` または local image ID `sha256:...` のみを許可し、tag や `:latest` は reject する
- `pre_cutover_runtime.git_commit` は full 40-character git SHA を記録する。`--pre-cutover-git-commit` を省略した場合は current git `HEAD` から解決する

#### Cutover

1. runner を停止する
2. migration CLI で watchlist/state v2 を生成し、backup と `rollback-manifest.json` を取得する
3. `rollback-manifest.json` を開き、`pre_cutover_runtime.image_ref` と `pre_cutover_runtime.git_commit` が今回の rollback target と一致していることを確認する
4. runtime 設定を `MANGA_WATCH_WATCHLIST=/app/manga_watch/watchlist.json` に切り替える
5. `python3 -m manga_watch.check manga_watch/watchlist.json` を 1 回実行して state validation と parser/state 挙動を確認する
6. runner を再起動する

#### Rollback conditions

- migration 出力 validation に失敗した
- migrated data で #11 の parser/state regression が落ちた
- cutover 後の初回 run で期待しない source errors / state corruption / update spam が出た

#### Rollback prechecks

- rollback 対象の cutover で作られた `backup-dir/rollback-manifest.json` を選び、その manifest を今回の source of truth に固定する
- `data_backups[*].backup_path` が全て存在し、`restore_to_path` が元の v1 `urls.txt` / `state.json` であることを確認する
- `pre_cutover_runtime.image_ref` が今回戻す runtime/image artifact と一致し、digest か image ID であることを確認する
- `pre_cutover_runtime.git_commit` が今回戻す pre-cutover checkout と一致していることを確認する
- v2 runner を停止し、rollback 判断に使う source error / state corruption / update spam の証跡を残す

#### Rollback steps

1. v2 runner を停止する
2. `rollback-manifest.json` の `data_backups[*]` に従って v1 `urls.txt` と `state.json` を `restore_to_path` へ戻す
3. `rollback-manifest.json` の `pre_cutover_runtime.image_ref` と `pre_cutover_runtime.git_commit` に従って pre-cutover image / checkout に戻す
4. 復元した pre-cutover runtime で `python3 -m manga_watch.check manga_watch/urls.txt` を実行する
5. `docker compose up -d comic-crawler` で pre-cutover runner を起動する

#### Post-rollback smoke checks

- 復元した pre-cutover runtime で `python3 -m manga_watch.check manga_watch/urls.txt` が成功し、v1 data load / state save error を出さない
- `docker compose up -d comic-crawler` 後、pre-cutover runner の初回 run に想定外の parser/state error が無い
- pre-cutover runner の初回 run で notification burst や既読 data の再送が起きていない

## Verification gate for migrated data

migrated sample data に対して最低限これを通す:

```bash
python3 -m unittest tests.test_sources tests.test_update_classification tests.test_check tests.test_runner tests.test_migrate_v2 tests.test_backlog
```

この suite で次を確認できることを cutover 条件にする。

- 最新話検知が `latest_key` 基準で動く
- 同一 event を再検知しても `history` と `unread.event_ids` が重複しない
- same stable id 時の metadata merge が silent に行われる
- 部分失敗時の `errors.sources` と health 更新が期待どおり
- backlog CLI で未読確認と既読化ができる
- migration が backup と v2 watchlist/state を正しく生成する

## Non-goals

- v1 runtime backward compatibility の維持
- v1 / v2 混在運用
- #11 の検証基盤が揃う前の migration 実施
