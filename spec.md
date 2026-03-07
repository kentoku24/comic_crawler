# comic_crawler / spec

## Glossary

- **comic_crawler**: このリポジトリ全体
- **watchlist**: `manga_watch/urls.txt`
- **checker**: `manga_watch/check.py`
- **runner**: `manga_watch/runner.py`
- **state / last_seen**: 永続化された最新話スナップショット
- **run**: checker の 1 回分の実行
- **diff**: checker が返す `updates`
- **alert**: 更新があったとき main channel に送る通知
- **run report**: 毎回 run-report channel に送る実行結果

## Purpose

複数の漫画サイトを監視し、新しいエピソードが公開されたら Discord に通知する。現行の正規運用は Docker コンテナ単体で自己完結する。

## Inputs

### Watch list
- ファイル: `manga_watch/urls.txt`
- 形式: 1 行 1 URL
- `#` で始まる行はコメント

対応 URL:
- ComicWalker episode URL
- webアクション episode URL
- Kakuyomu episode URL

## State

### State file
- ローカル既定値: `manga_watch/state.json`
- env override: `MANGA_WATCH_STATE=/path/to/state.json`
- Docker 既定値: `/data/state.json`

### State schema (v1)
```json
{
  "version": 1,
  "items": {
    "<workId>": {
      "latest": {
        "seriesTitle": "...",
        "episodeTitle": "...",
        "episodeCode": "...",
        "url": "...",
        "pageTitle": "..."
      },
      "seenAt": 1700000000
    }
  },
  "lastRunAt": 1700000000
}
```

### WorkId rules
- ComicWalker: `KC_XXXXXX_S`
- webアクション: seed episode URL
- Kakuyomu: `kakuyomu:<work_id>`

## Core behavior

### Checker execution
```bash
python3 -m manga_watch.check manga_watch/urls.txt
```

- 常に JSON を出力する: `{ "updates": [...], "errors": { "sources": [...], "run": [...] } }`
- state を更新する
- 既知の stable id が変わったときだけ `updates` に積む
- stable id が同じでタイトルなどの補足情報だけ増えた場合は silent update する
- source 単位の parser/runtime failure は `errors.sources` に積み、成功した item の state 更新は継続する
- watchlist 読み込みや state 保存のような run-level failure は `errors.run` に記録され、`CheckRunError` として扱う

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

### Runner execution
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
- `MANGA_WATCH_URLS`
- `MANGA_WATCH_STATE`

### Latest episode detection

#### ComicWalker
1. seed URL から `KC_XXXXXX_S` を抽出する
2. `https://comic-walker.com/detail/<series_code>` を取得する
3. `__NEXT_DATA__` から episode code を集める
4. 数値 suffix が最大の episode を最新話とみなす
5. 最新話 URL と `<title>` から `seriesTitle` と `episodeTitle` を取る

#### webアクション
1. seed episode URL から開始する
2. `nextReadableProductUri` を辿れるだけ辿る
3. 最後のページの `<title>` から `seriesTitle` と `episodeTitle` を取る
4. 最終到達 URL を stable id とする

#### Kakuyomu
1. work page の `__NEXT_DATA__` を読む
2. episode 一覧から `publishedAt` が最大のものを選ぶ
3. 最新 episode page の `<title>` から `seriesTitle` を補完する
4. 最新 episode id を stable id とする

## Fixture bundles

- layout: `tests/fixtures/<source>/<case>/`
- each case keeps `manifest.json` plus ordered raw responses (`01-*.html`, `02-*.html`, ...)
- `manifest.json` は `seedUrl`, `expectedWork`, `steps`, `expectedLatest` または `expectedError` を持つ
- fixture は parser が実際に読む raw input を保存し、HTML prettify や JSON 再直列化を行わない
- ComicWalker / Kakuyomu は `normal`, `title_variation_or_bonus`, `same_episode_refresh`, `broken_missing_next_data`
- webアクションは `normal`, `title_variation`, `escaped_next_uri`, `broken_missing_next`, `broken_loop`

## Notification behavior

runner は以下を担当する:

1. checker を実行する
2. 更新があるときだけ main channel に alert を送る
3. 毎回 run-report channel に run report を送る
4. checker が `errors.sources` を返した場合、run report は clean success ではなく partial failure summary を送る
5. checker 失敗時または Discord 投稿失敗時は run-report channel に error summary を送ろうとする
6. error summary 投稿にも失敗した場合は container log に落とす

run report には最低限これを含める:
- 実行時刻
- 更新件数
- main channel 通知を送ったか
- checker が返した error 件数と summary
- 現在の一覧

## Scheduling

- 既定の本番スケジュール: `CRAWL_SCHEDULE=0 19 * * *`
- 既定 timezone: `TZ=Asia/Tokyo`
- 代替として `CRAWL_INTERVAL=<seconds>` を使える
- `CRAWL_SCHEDULE` と `CRAWL_INTERVAL` の同時指定は不可
- `RUN_ON_STARTUP=true` のとき起動直後に 1 回実行する

## Non-goals

- 認証付きサイト対応
- JS レンダリング必須サイトへの全面対応
- Web UI 提供
- OpenClaw への依存

## Security

- token / password / cookie はコミットしない
- Discord 設定は環境変数で注入する
- state には last-seen メタデータだけを保存する
