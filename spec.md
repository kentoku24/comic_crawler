# comic_crawler / spec

## Table of contents

- [Runtime baseline](#runtime-baseline)
- [Glossary](#glossary)
- [Purpose](#purpose)
- [Runtime Inputs](#runtime-inputs)
- [State](#state)
- [Core behavior](#core-behavior)
- [Reply Discord `latest` query](#reply-discord-latest-query)
- [Checker](#checker)
- [Runner](#runner)
- [Reader / Writer compatibility matrix](#reader--writer-compatibility-matrix)
- [One-time migration](#one-time-migration)
- [Verification gate for migrated data](#verification-gate-for-migrated-data)
- [Non-goals](#non-goals)

## Runtime baseline

- ローカル実行 / Docker / 将来の CI は Python `3.12` を単一の runtime baseline とする
- Docker image policy は `python:3.12-slim` に合わせ、ローカル virtualenv は `python3.12` で作る
- Python `3.10` / `3.11` compatibility は required ではない

## Glossary

- **watchlist v2**: `manga_watch/watchlist.json`
- **state v2**: `manga_watch/state.json`
- **checker**: `python3 -m manga_watch.check <watchlist.json>`
- **runner**: `python3 -m manga_watch.runner`
- **latest query**: 保存済み state から最新話一覧を返す read-only 問い合わせ
- **fetch trigger**: Discord から runner を手動起動する write path の問い合わせ
- **daily notification**: 更新があったとき Discord main channel に送る通知
- **run report**: 毎回 Discord run-report channel に送る実行結果
- **work_id**: 作品単位で不変な識別子
- **latest_key**: 更新検知と通知重複排除の基準キー

## Purpose

複数の漫画サイトを作品単位で監視し、新しいエピソードが公開されたら通知し、保存済みの最新話一覧を問い合わせできるようにする。Issue #7 の cutover 以降、runtime が正として扱う永続データは watchlist/state v2 のみで、v1 (`urls.txt`, `state.json` v1) は migration 入力と rollback 用 backup に限定する。

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

### Reply Discord `latest` query

保存済みの watchlist/state v2 を読み取り、Discord 上の `latest` 問い合わせに対して現在の最新話一覧を返す read-only 機能。

#### Input contract

- Discord の inbound surface は read-only な `latest` query をサポートする
- canonical input は trim 後に本文がちょうど `latest` であるメッセージとする
- `latest` query は live crawl を走らせず、保存済み watchlist/state v2 だけを読む
- `latest` query は watchlist/state を変更しない
- 応答生成失敗時も checker や runner の定期実行には影響を与えない

#### Source of truth and ordering

- query の source of truth は `watchlist v2 + state v2`
- 一覧順は watchlist の入力順を正とする
- `enabled=false` の作品は既定では一覧に含めない
- watchlist に無い orphaned state entry は `latest` 応答に含めない
- 各行の内容は `state.works[work_id].latest` と `state.works[work_id].health` から生成する
- `state.last_run_at` は一覧全体の `最終巡回` として使う

#### Response contract

正常系の本文は次の形を正とする。

```text
保存済みの最新話一覧です
最終巡回: 2026-03-07 17:03:09 JST
現在のリスト:
[第71話](<https://example.com/episodes/71>)　作品A
[第8話](<https://example.com/episodes/8>)　作品B
```

- 1 行目は固定で `保存済みの最新話一覧です`
- `最終巡回` は `state.last_run_at` を `TZ` で `YYYY-MM-DD HH:MM:SS ZZZ` に整形する
- `state.last_run_at` が `null` または未設定なら `最終巡回: まだ実行されていません` とする
- 3 行目は固定で `現在のリスト:`
- 各作品は 1 行で返し、少なくとも `最新話ラベル + URL + 作品名` を含める
- URL があるときは Discord Markdown link 形式 `[label](<url>)` を使う
- URL が無いときは plain text で `label　作品名` とする
- `latest` が空オブジェクトの作品は `（未取得）　作品名` とする

#### Label fallback rules

- 作品名は `latest.series_title`, `latest.series`, `work_id` の順で選ぶ
- 最新話ラベルは `latest.episode_title`, `latest.episode_code`, `latest.url`, `未取得` の順で選ぶ
- `latest.url` があり、`episode_title` が無い場合でも link label には `episode_code` を優先し、両方無いときだけ URL 自体を label とする

#### Episode label truncation rules

- `latest` query の一覧は縦に見比べやすいことを優先し、長い最新話ラベルは省略してよい
- 省略対象は「話数ヘッダの後ろに続く自由文 subtitle」とし、話数ヘッダ自体はできるだけ保持する
- 話数ヘッダの例:
  - `第71話`
  - `第78話その1`
  - `第55話後編`
  - `第62話②`
  - `Episode 12`
  - `Ep.8`
  - `#8`
- 話数ヘッダの直後に空白または区切り記号があり、その後ろに subtitle が続く場合は `header + separator + subtitle` に分けて扱う
- truncate は subtitle にだけ適用し、`header` と `separator` はそのまま残す
- 文字数は Unicode grapheme cluster 単位で数える
- subtitle の最大長は `…` を含めて 8 文字とする
- subtitle が 8 文字を超える場合は、先頭 7 文字を残して `…` を付ける
- 省略記号は常に `…` とする
- 全角/半角の違いは文字数計算に使わない
- mixed width の subtitle も同じ文字数ルールで切る
- subtitle を分離できない場合は、最新話ラベル全体に fallback truncate を適用する
- fallback truncate の上限は `…` を含めて 20 文字とする
- 最新話ラベル全体が 20 文字を超える場合は、先頭 19 文字を残して `…` を付ける
- fallback truncate は subtitle 分離に失敗した場合だけ使う。分離できる場合は subtitle-only truncate を優先する

例:

- `第71話 abcdefghijk` -> `第71話 abcdefg…`
- `第71話 あいうえおかきくけ` -> `第71話 あいうえおかき…`
- `第71話 abあいうcdef` -> `第71話 abあいうcd…`
- `abcdefghijklmnopqrstu` -> `abcdefghijklmnopqrs…`
- `第55話後編` -> `第55話後編`

#### Empty / stale / partial-failure semantics

- 一覧対象作品が 0 件、または全作品が未取得なら次を返す

```text
保存済みの最新話一覧です
最終巡回: まだ実行されていません
現在のリスト:
- まだ保存済みの監視結果がありません
```

- `latest` query は `更新なし` を意味しない。あくまで「保存済み state の参照」である
- 直近 run で 1 件以上 `health.consecutive_failures > 0` の作品がある場合、本文末尾に warning summary を追加する
- warning summary は少なくとも「一部作品は直近巡回で失敗しており、表示内容は保存済みデータである」ことを伝える
- `last_run_at` が大きく古い場合の stale 判定閾値は query surface 側で別途持ってよいが、stale warning を出しても live crawl を自動実行してはならない
- source failure と run-level failure は `更新なし` と混同しない文言で返す

#### Verification gate

- command routing は `latest` を read-only query として解釈できること
- response generation は watchlist 順、timestamp formatting、empty state、partial failure warning を自動テストで担保する
- `latest` query 実行時に source fetch が呼ばれないことをテストで担保する

### Checker

watchlist を巡回して各作品の最新話を取得し、更新検知・エラー収集・state v2 更新を行うコア処理。

#### Execution contract

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

#### Status CLI

```bash
python3 -m manga_watch.check --status
python3 -m manga_watch.check --status --format json
```

- `--status` は crawl を実行せず、watchlist/state v2 から現在の監視状態を表示する
- text 出力は監視件数、最終 run 時刻、最終成功時刻、health counts、失敗中作品、stale 作品、作品別 health を含む
- JSON 出力は同じ情報を `summary` と `works[]` に分けて返す
- `works[].health` には `state`, `last_checked_at`, `last_success_at`, `consecutive_failures`, `expected_interval_seconds`, `stale_after_seconds` を含む

#### Backlog CLI

```bash
python3 -m manga_watch.backlog --unread-only
python3 -m manga_watch.backlog --work-id KC_003913_S --json
python3 -m manga_watch.backlog --mark-read KC_003913_S
```

- `--unread-only`: 未読がある作品だけ表示する
- `--work-id`: 対象作品を 1 つに絞る
- `--json`: 機械可読な履歴 / unread summary を出す。event に `gap` があればそのまま含める
- `--mark-read <work_id>`: その作品の `unread.event_ids` を空にして保存し、保持ルールに従って既読履歴を trim する

#### Multi-update gap capability

- ComicWalker / Kakuyomu: `episodeTitle` / `pageTitle` に比較可能な番号が含まれるときは推定話数を出せる
- comic-action: `latest_key` は episode URL で、adapter contract だけでは series 内の差分件数を導けない。title から番号が取れない場合は `previous_latest_only` fallback になる
- どの source でも exact な全話遡及取得はしない。`gap.from_latest` と optional な推定件数を downstream 入力として使う

#### Error schema

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

#### Atomic state writes

state 保存は `temp file -> json dump -> flush -> fsync(file) -> replace -> fsync(directory)` を必須とする。v2 cutover で durability を落とさない。

### Runner

Checker を定期実行または手動実行し、daily notification と run report を Discord に送る運用オーケストレーション機能。

```bash
python3 -m manga_watch.runner
```

必要な設定:

- `MANGA_WATCH_NOTIFIER_BACKENDS`
- `MANGA_WATCH_WEBHOOK_URL` (`webhook` backend を使うとき)
- `MANGA_WATCH_WEBHOOK_TIMEOUT`
- `DISCORD_BOT_TOKEN` (Discord inbound / outbound surface を使うとき)
- `DISCORD_MAIN_CHANNEL_ID` (daily notification を Discord main channel へ送るとき)
- `DISCORD_RUN_REPORT_CHANNEL_ID` (run report を Discord run-report channel へ送るとき)
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

#### Scheduled scan contract

- runner は watchlist 全体を定期スキャンする
- スキャンの目的は各作品の最新話を再取得し、保存済み `latest_key` と比較して更新を検知すること
- 本番既定値は日次スキャンであり、既定スケジュールは `CRAWL_SCHEDULE=0 19 * * *` とする
- `CRAWL_INTERVAL` を使う構成では日次以外の頻度も許容するが、contract 上の最小要件は「定期スキャンされること」である
- `RUN_ON_STARTUP=true` のときは定期スキャンに加えて起動直後に 1 回スキャンする
- 1 回の定期スキャンの結果は、更新検知・state 更新・run report・失敗可視化に一貫して反映される
- `latest` query は read-only 参照であり、定期スキャンの代替ではない

#### Notification backends

- `MANGA_WATCH_NOTIFIER_BACKENDS` は required。comma-separated で `stdout`, `webhook` を並べる
- runner は同じ update event を指定順に全 backend へ fan-out する
- `stdout` backend は 1 event = 1 JSON line を標準出力へ書き込んで flush する
- `webhook` backend は 1 event ごとに JSON POST する
- webhook success は HTTP `2xx` のみ。`3xx`/`4xx`/`5xx`、timeout、transport error は failure
- どれか 1 backend でも failure した run は失敗扱いにし、failure report を stderr に出す
- fan-out 中に一部 backend が成功してから別 backend が失敗し得るため、consumer は duplicate を `event_id` で dedupe する
- runner は delivery 前に state v2 root の `notification_outbox` へ event を保存する
- `notification_outbox` entry は少なくとも `event`, `pending_backends`, `attempt_count`, `last_attempted_at`, `last_error` を持つ
- delivery failure 時は failed backend だけ `pending_backends` に残し、次の `runner` run または `python3 -m manga_watch.replay_outbox` で replay する
- `notification_outbox` が空になるまで delivery は at-least-once で続く。consumer は `event_id` で idempotent に処理する
- Discord `latest` / `fetch` / daily notification / run report はこの backend fan-out とは別の surface であり、契約は後続節を正とする

#### Update event schema

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

#### Classification defaults and notification policy

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

#### Discord `fetch` trigger

- Discord の inbound surfaceは write path の `fetch` trigger をサポートする
- canonical input は trim 後に本文がちょうど `fetch` であるメッセージとする
- `fetch` trigger は「その時点で 1 回 runner を実行する」手動トリガーであり、日次 19 時の定期実行と同じ実行経路を通る
- `fetch` trigger で開始された run は、checker 実行、state 更新、daily notification、run report、failure handling を定期実行と同じ contract で処理する
- `fetch` trigger は read-only ではなく、成功時には state を更新しうる
- 実行中の runner が無い場合は trigger を受け付け、command を受けた Discord 上に受理メッセージを返してよい
- 受理メッセージは少なくとも「手動 fetch を受け付けた」ことと「結果は daily notification / run report を確認すべき」ことを伝える
- すでに scheduled run, startup run, または別の `fetch` run が進行中なら、新しい `fetch` run は開始しない
- 進行中に拒否した場合は「現在巡回実行中であるため新しい fetch は開始しない」ことを返す
- `fetch` run と scheduled run の違いは trigger source だけであり、更新検知・通知重複防止・失敗時挙動は同一である

#### Daily notification contract

- daily notification の送信先は `DISCORD_MAIN_CHANNEL_ID` とする
- runner は checker の `updates` を入力として daily notification を生成する
- 1 run で 1 件以上更新があった場合、その run の更新を 1 通の集約メッセージとして通知してよい
- 更新 0 件の run では daily notification を送らない
- 通知対象は「今回 run で `latest_key` が変わった作品」だけとする
- 同じ `work_id` と `latest_key` の組み合わせに対する daily notification は 1 回だけ送る
- 更新を検知した直後の成功 run で 1 回通知したあとは、後続 run で `latest_key` が変わらない限り再通知しない
- 翌日など更新が無い run では daily notification を送らず、run report だけを送る
- `fetch` run でも同じ重複防止 contract を適用し、すでに通知済みの `work_id + latest_key` は再通知しない
- metadata refresh のような silent merge は daily notification の対象にしない
- 通知の並び順は `updates` の順、すなわち watchlist 順を正とする

#### Daily notification response contract

更新通知本文は次の形を正とする。

```text
新着エピソードを検知しました（2026-03-02）
[蜘蛛ですが、なにか？：第78話その1](<https://comic-walker.com/detail/KC_003913_S/episodes/KC_0039130009000011_E?episodeType=latest>)←第77話その2
[航宙軍士官、冒険者になる：第62話①](<https://comic-walker.com/detail/KC_001405_S/episodes/KC_0014050006800011_E?episodeType=latest>)←第61話
```

- 1 行目は固定で `新着エピソードを検知しました（YYYY-MM-DD）` とする
- 日付は通知生成時刻ではなく、その run が属する local date を `TZ` 基準で整形して使う
- 2 行目以降は 1 更新につき 1 行とする
- 各行は `[作品名：新しい最新話](<URL>)←前回話` の形式を正とする
- URL は更新後 `to.url` を使う
- 作品名は `to.series_title`, `to.seriesTitle`, `to.series`, `id` の順で選ぶ
- 新しい最新話は `to.episode_title`, `to.episodeTitle`, `to.episode_code`, `to.episodeCode`, `to.url` の順で選ぶ
- 前回話は `from.episode_title`, `from.episodeTitle`, `from.episode_code`, `from.episodeCode`, `from.url`, `未取得` の順で選ぶ
- 作品名と新しい最新話の区切りは全角コロン `：` を使う
- 新旧比較の区切りは ASCII の left arrow ではなく、固定で `←` を使う
- URL が無い場合は `[label](<url>)` ではなく plain text の `作品名：新しい最新話←前回話` に degrade してよい

#### Notification label normalization

- 更新通知内の `新しい最新話` には `latest` query と同じ episode label truncation rules を適用してよい
- `前回話` にも同じ truncate rules を適用してよい
- 作品名は原則として truncate しない。極端に長い場合の truncation は別 contract として扱う

#### Run report contract

- run report の送信先は `DISCORD_RUN_REPORT_CHANNEL_ID` とする
- runner は更新有無にかかわらず、1 run ごとに 1 通の run report を送る
- run report は少なくとも次を含む
  - 実行時刻
  - trigger source (`scheduled`, `startup`, `discord_fetch` のいずれか)
  - 更新検知件数
  - daily notification を送信したか
  - source failure / run-level failure の要約
  - 現在のリスト、または最新状態の要約
- run report の目的は「更新がなかった」ことと「run が失敗した」ことを区別可能にすることである
- 更新 0 件でも run report は送る
- 更新があって daily notification 送信にも成功した run でも、別途 run report は送る

#### Notification failure semantics

- 更新通知の送信失敗は `更新なし` と混同してはならない
- 更新通知送信に失敗した run でも、run report または別の failure surface から「更新検知はあったが通知 delivery は失敗した」ことが分かる必要がある
- run report 自体の送信失敗も、更新なしとして扱ってはならない
- delivery の durable replay を行う場合、その contract は outbox/replay 側の仕様を正とする

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
