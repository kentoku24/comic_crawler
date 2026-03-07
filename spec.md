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
- `notification_policy.mode`: v2 migration では既定値 `all`
- `notification_policy.allowed_update_types`: 明示設定が無ければ `null`

### work_id contract

- ComicWalker: `KC_XXXXXX_S`
- webアクション: seed episode URL
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
        "episode_title": "第77話その2"
      },
      "history": [],
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
- `history`: Issue #17 の土台。Issue #7 では空配列を保持し、runtime は内容を解釈しない
- `health.last_checked_at`: 直近でその作品を巡回した UNIX timestamp
- `health.last_success_at`: 直近で成功した UNIX timestamp
- `health.consecutive_failures`: 連続失敗回数
- `last_run_at`: checker 全体の最終実行時刻

### latest_key contract

- ComicWalker: `episode_code`
- webアクション: 最終到達 episode URL
- Kakuyomu: 最新 episode id

`latest_key` は「更新検知」と「通知 idempotency」の唯一の比較キーであり、タイトルや page title の改善だけでは変えない。

## Core behavior

### Checker execution

```bash
python3 -m manga_watch.check manga_watch/watchlist.json
```

- checker は常に JSON を出力する
- watchlist は入力順で処理し、`updates` の順序も watchlist 順で deterministic にする
- `latest_key` が変わったときだけ `updates` に積む
- `latest_key` が同じで `seriesTitle` / `episodeTitle` / `pageTitle` / 補足 metadata だけ改善された場合は silent merge する
- source ごとの parser/runtime failure は `errors.sources` に積み、成功した作品の state 更新は継続する
- 失敗した作品も `health.last_checked_at` と `health.consecutive_failures` は更新する
- watchlist/state の読み込みや state 保存のような run-level failure は `errors.run` に記録し、`CheckRunError` として返す

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

## Reader / Writer compatibility matrix

| Component | Reads v1 | Reads v2 | Writes v1 | Writes v2 |
| --- | --- | --- | --- | --- |
| `python3 -m manga_watch.migrate_v2` | yes | no | no | yes |
| `python3 -m manga_watch.check` | no | yes | no | yes (`state.json`) |
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
python3 -m unittest tests.test_sources tests.test_check tests.test_runner tests.test_migrate_v2
```

この suite で次を確認できることを cutover 条件にする。

- 最新話検知が `latest_key` 基準で動く
- same stable id 時の metadata merge が silent に行われる
- 部分失敗時の `errors.sources` と health 更新が期待どおり
- migration が backup と v2 watchlist/state を正しく生成する

## Non-goals

- v1 runtime backward compatibility の維持
- v1 / v2 混在運用
- history / unread semantics の完成
- #11 の検証基盤が揃う前の migration 実施
