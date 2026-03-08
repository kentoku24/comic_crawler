# comic_crawler / spec

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
- `notification_policy.mode`: v2 migration では既定値 `all`
- `notification_policy.allowed_update_types`: 明示設定が無ければ `null`

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
| webアクション | episode URL only | 入力 URL のまま |
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
- `history`: 更新イベント列。各 event は `event_id`, `seen_at`, `latest` を持つ
- `history[].event_id`: `latest_key` をそのまま使う。作品ごとに一意で、履歴追加の idempotency key でもある
- `history[].seen_at`: その更新 event を checker が検知した UNIX timestamp
- `history[].latest`: event 時点の latest snapshot
- `unread.event_ids`: 未読 event id の source of truth。`unread_count` は永続化しない
- `health.last_checked_at`: 直近でその作品を巡回した UNIX timestamp
- `health.last_success_at`: 直近で成功した UNIX timestamp
- `health.consecutive_failures`: 連続失敗回数
- `last_run_at`: checker 全体の最終実行時刻

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
- 同じ `event_id` を再検知しても履歴は重複させない。必要なら event snapshot だけ補完更新する
- 新規 event が履歴に追加されたときだけ `unread.event_ids` にその id を追加する
- `latest_key` が同じで `seriesTitle` / `episodeTitle` / `pageTitle` / 補足 metadata だけ改善された場合は silent merge する
- update event と state.latest には `update_type`, `classification_reason`, `default_notify` を含める
- source ごとの parser/runtime failure は `errors.sources` に積み、成功した作品の state 更新は継続する
- retry 対象は transport error / timeout / HTTP `429` / `5xx` に限定する
- HTTP `404`、unsupported URL、parse error は即失敗として `errors.sources` に積む
- 同一 host への同時 request 数は `MANGA_WATCH_HTTP_WORKERS_PER_HOST` で抑制する
- 失敗した作品も `health.last_checked_at` と `health.consecutive_failures` は更新する
- watchlist/state の読み込みや state 保存のような run-level failure は `errors.run` に記録し、`CheckRunError` として返す

## Backlog CLI

```bash
python3 -m manga_watch.backlog --unread-only
python3 -m manga_watch.backlog --work-id KC_003913_S --json
python3 -m manga_watch.backlog --mark-read KC_003913_S
```

- `--unread-only`: 未読がある作品だけ表示する
- `--work-id`: 対象作品を 1 つに絞る
- `--json`: 機械可読な履歴 / unread summary を出す
- `--mark-read <work_id>`: その作品の `unread.event_ids` を空にして保存し、保持ルールに従って既読履歴を trim する

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

- `DISCORD_BOT_TOKEN`
- `DISCORD_MAIN_CHANNEL_ID`
- `DISCORD_RUN_REPORT_CHANNEL_ID`
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

### Default notification behavior

- `main_story`: 既定通知対象
- `unknown`: fail-open で既定通知対象
- `bonus`: 既定抑制対象
- `announcement`: 既定抑制対象
- `main_story` と suppress 対象が衝突した場合は `unknown` に倒す
- `bonus` と `announcement` だけが衝突した場合は suppress 側に残す
- runner の main channel 通知は既定通知対象だけを送る
- suppressed update も state と run report には残し、run report には `既定通知対象件数` と `既定抑制件数` を含める

## Reader / Writer compatibility matrix

| Component | Reads v1 | Reads v2 | Writes v1 | Writes v2 |
| --- | --- | --- | --- | --- |
| `python3 -m manga_watch.migrate_v2` | yes | no | no | yes |
| `python3 -m manga_watch.check` | no | yes | no | yes (`state.json`) |
| `python3 -m manga_watch.backlog` | no | yes | no | yes (`state.json`, mark-read 時のみ) |
| `python3 -m manga_watch.runner` | no | yes | no | yes (`state.json`) |

- runtime は v1 / v2 混在運用をサポートしない
- rollback は backup を戻すだけでなく、v1 runtime へ戻せる pre-cutover image / commit が必要

## One-time migration

### CLI

```bash
python3 -m manga_watch.migrate_v2 \
  --watchlist-v1 manga_watch/urls.txt \
  --state-v1 /data/state.json \
  --watchlist-v2 manga_watch/watchlist.json \
  --state-v2 /data/state.json \
  --backup-dir /data/migration-backups/20260308T080000Z
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

- migration CLI は入力 `urls.txt` と v1 `state.json` を `backup-dir` に copy2 する
- backup dir は timestamped path を使い、前回 backup を上書きしない

#### Cutover

1. runner を停止する
2. migration CLI で watchlist/state v2 を生成し、backup を取得する
3. runtime 設定を `MANGA_WATCH_WATCHLIST=/app/manga_watch/watchlist.json` に切り替える
4. `python3 -m manga_watch.check manga_watch/watchlist.json` を 1 回実行して state validation と parser/state 挙動を確認する
5. runner を再起動する

#### Rollback conditions

- migration 出力 validation に失敗した
- migrated data で #11 の parser/state regression が落ちた
- cutover 後の初回 run で期待しない source errors / state corruption / update spam が出た

#### Rollback steps

1. v2 runner を停止する
2. backup-dir から v1 `urls.txt` と `state.json` を戻す
3. pre-cutover runtime image / commit に戻す
4. v1 runtime で `python3 -m manga_watch.check manga_watch/urls.txt` を実行して復旧確認する

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
