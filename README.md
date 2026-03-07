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
  ]
}
```

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

## Local run

checker 単体確認:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
python3 -m manga_watch.check manga_watch/urls.txt
```

runner をローカル起動する場合は Discord 環境変数を入れてから実行します。

```bash
python3 -m manga_watch.runner
```

## Adding a source adapter

`manga_watch/sources/registry.py` の `REGISTERED_ADAPTERS` が adapter registration の single source of truth です。

1. `manga_watch/sources/` に concrete `SourceAdapter` module を追加する
2. `manga_watch/sources/registry.py` の `REGISTERED_ADAPTERS` に adapter instance を追加する
3. `.venv/bin/python -m unittest tests.test_sources tests.test_check` を実行する

2 を忘れると `tests.test_sources.SourceAdapterTests.test_registry_covers_every_concrete_adapter_module` が失敗します。

## Repository layout

- `manga_watch/check.py`: 共通 runner。watchlist 読み込み、state 比較、更新判定
- `manga_watch/sources/`: source adapter interface、registry、各 source 実装
- `manga_watch/runner.py`: スケジューラ + Discord 通知
- `manga_watch/urls.txt`: watchlist
- `docker-compose.yml`: 本番想定の単一コンテナ起動定義

## Security notes

- Discord token はコミットしない
- cookies / login creds はコミットしない
- state には last-seen メタデータだけを保存する

## Maintenance tips

- サイトの HTML が変わって検知が止まったら `python3 -m manga_watch.check manga_watch/urls.txt` を実行して例外を確認する
- 新しいサイトを足すときは `manga_watch/sources/` に adapter を追加し、`registry.py` の `REGISTERED_ADAPTERS` に登録して `tests.test_sources` を通す
