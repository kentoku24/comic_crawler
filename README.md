# comic_crawler

Docker コンテナ 1 つで定期クロールし、Discord に新着通知と run report を送る漫画更新監視アプリです。

## What it does

1. `manga_watch/urls.txt` の watchlist を読む
2. source adapter が URL を work descriptor に正規化する
3. source adapter が最新エピソードを取得する
4. state と比較する
5. 更新があれば Discord main channel に通知する
6. 毎回 Discord run-report channel に実行結果を送る

checker 単体の出力契約は引き続き JSON です。

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

`errors.sources` は source ごとの partial failure、`errors.run` は watchlist 読み込みや state 保存のような run-level failure を表します。

checker は watchlist を並列に処理しますが、`updates` / `errors.sources` / state 更新順は常に入力順で deterministic に保たれます。同一 host への HTTP burst は per-host cap で抑え、retry は transport error / timeout / HTTP `429` / `5xx` に限定します。`404` や parse error は即座に `errors.sources` に落ちます。

## Supported sources

### ComicWalker
- 入力: `https://comic-walker.com/detail/<series>/episodes/<episode>`
- 比較キー: `episodeCode`

### webアクション
- 入力: `https://comic-action.com/episode/<id>`
- 比較キー: 最終到達エピソード URL

### Kakuyomu
- 入力: `https://kakuyomu.jp/works/<work>/episodes/<episode>`
- 比較キー: 最新 episode id

## Docker run

1. `.env.example` を `.env` にコピーして Discord 設定を入れる
2. 必要なら `manga_watch/urls.txt` を編集する
3. 起動する

```bash
docker compose up -d --build
docker compose logs -f
```

永続 state は Docker volume `crawler-data` に保存されます。コンテナ再起動後も差分判定は維持されます。

### Environment variables

- `DISCORD_BOT_TOKEN`: Discord Bot token
- `DISCORD_MAIN_CHANNEL_ID`: 更新通知先 channel id
- `DISCORD_RUN_REPORT_CHANNEL_ID`: 毎回の run report 送信先 channel id
- `TZ`: スケジュール計算の timezone。既定値は `Asia/Tokyo`
- `CRAWL_SCHEDULE`: cron 形式。既定値は `0 19 * * *`
- `CRAWL_INTERVAL`: 秒単位の固定間隔。`CRAWL_SCHEDULE` と同時指定は不可
- `RUN_ON_STARTUP`: `true` のとき起動直後に 1 回実行
- `MANGA_WATCH_URLS`: watchlist パス。compose では `/app/manga_watch/urls.txt`
- `MANGA_WATCH_STATE`: state ファイルパス。compose では `/data/state.json`
- `MANGA_WATCH_HTTP_TIMEOUT`: source fetch の request timeout 秒。既定値は `25`
- `MANGA_WATCH_HTTP_RETRIES`: timeout / transport error / `429` / `5xx` に対する retry 回数。既定値は `2`
- `MANGA_WATCH_HTTP_RETRY_BACKOFF`: retry ごとの指数 backoff の基準秒。既定値は `0.5`
- `MANGA_WATCH_HTTP_WORKERS`: watchlist を並列処理する worker 数。既定値は `4`
- `MANGA_WATCH_HTTP_WORKERS_PER_HOST`: 同一 host に同時接続する上限。既定値は `2`

## Local run

checker 単体確認:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
python3 -m manga_watch.check manga_watch/urls.txt
.venv/bin/python -m unittest tests.test_sources tests.test_check
```

runner をローカル起動する場合は Discord 環境変数を入れてから実行します。

```bash
python3 -m manga_watch.runner
```

## Repository layout

- `manga_watch/check.py`: 共通 runner。watchlist 読み込み、state 比較、更新判定
- `manga_watch/sources/`: source adapter interface、registry、各 source 実装
- `manga_watch/runner.py`: スケジューラ + Discord 通知
- `manga_watch/urls.txt`: watchlist
- `tests/fixtures/<source>/<case>/`: raw response bundle + `manifest.json` による adapter regression fixture
- `docker-compose.yml`: 本番想定の単一コンテナ起動定義

## Fixture regression tests

- fixture は `tests/fixtures/<source>/<case>/manifest.json` と、ordered response bundle を表す raw payload (`01-*.html`, `02-*.html`, ...) で構成する
- `manifest.json` は `seedUrl`, `expectedWork`, `steps`, `expectedLatest` または `expectedError` を持つ
- ComicWalker / Kakuyomu は `normal`, `title_variation_or_bonus`, `same_episode_refresh`, `broken_missing_next_data`
- webアクションは `normal`, `title_variation`, `escaped_next_uri`, `broken_missing_next`, `broken_loop`
- fixture の更新手順とサニタイズ規則は [tests/fixtures/README.md](tests/fixtures/README.md) にまとめる

## Security notes

- Discord token はコミットしない
- cookies / login creds はコミットしない
- state には last-seen メタデータだけを保存する

## Maintenance tips

- サイトの HTML が変わって検知が止まったら `python3 -m manga_watch.check manga_watch/urls.txt` を実行して例外を確認する
- parser/state regression を更新するときは `.venv/bin/python -m unittest tests.test_sources tests.test_check` を先に回す
- run/retry 設定を変えたときは `.venv/bin/python -m unittest tests.test_sources tests.test_check tests.test_runner` で runner まで確認する
- 新しいサイトを足すときは `manga_watch/sources/` に adapter を追加し、`registry.py` に登録する
