# Piccoma Source Design

**Date:** 2026-04-27
**Repository:** `kentoku24/comic_crawler`
**Base:** `origin/main` at `a1c591f`
**Status:** Proposed

---

## Goal

ピッコマを `comic_crawler` の supported source に追加する。

最初の対象はピッコマだけとし、LINEマンガと BOOK☆WALKER は別 spec / issue に分ける。ピッコマでは、既知の作品 URL からの更新監視だけでなく、既存の `/search` と `/supertwins-search` 経由の横断候補検索にも参加させる。

## Decisions

- source 名は `piccoma` とする
- 対象ベースラインは `origin/main`
- 入力 URL は未ログインで見える公開 web ページだけを対象にする
- canonical seed URL は `https://piccoma.com/web/product/<product_id>?etype=episode` とする
- `work_id` は `piccoma:<product_id>` とする
- 更新監視の main latest は話読みの最新話だけにする
- 巻読みは latest 判定に使わない
- 購入済み、閲覧権、ログイン後だけ見える情報、アプリ専用情報は対象外にする
- availability metadata は公開ページで見える無料話数、待てば¥0、全話数などの文字列だけを扱う

## Current State

`origin/main` では source adapter 追加の主要接続点が既に揃っている。

- `manga_watch/sources/registry.py` が supported source の runtime registration の source of truth
- `manga_watch/watchlist.py` の `SOURCE_CAPABILITIES` が `watchlist add` の UX と unsupported URL error hint を持つ
- `manga_watch/source_drift.py` が live source drift canary contract を持つ
- `manga_watch/source_search.py` が `/search` と `/supertwins-search` の source search backend を持つ
- `manga_watch/discord_supertwins_search.py` は `supported_search_sources()` を巡回し、root source 以外の候補を探す

したがって、ピッコマも既存の `SourceAdapter` / `SearchResult` / fixture regression の型に合わせる。

## Non-Goals

- LINEマンガ、BOOK☆WALKER を同じ実装単位で追加すること
- ピッコマのログイン、Cookie、購入済み状態、閲覧権を扱うこと
- アプリ API や非公開 API を前提にすること
- 巻読みの最新巻を更新通知として扱うこと
- 個別 episode URL を公開 HTML から安定して取れない場合に推測生成すること
- `/search` や `/supertwins-search` の UX を作り替えること

## Architecture

### Source adapter

`manga_watch/sources/piccoma.py` に `PiccomaAdapter` を追加する。

`PiccomaAdapter.can_handle()` は次の URL を受け付ける。

- `https://piccoma.com/web/product/<product_id>`
- `https://piccoma.com/web/product/<product_id>?etype=episode`
- query 付きの同等 URL

`PiccomaAdapter.normalize()` は product id を抽出し、次の `WorkDescriptor` を返す。

```text
source: piccoma
work_id: piccoma:<product_id>
seed_url: https://piccoma.com/web/product/<product_id>?etype=episode
metadata:
  productId: <product_id>
  series: piccoma:<product_id>
```

`PiccomaAdapter.fetch_latest()` は canonical product URL を取得し、公開 product page から作品名と availability label を抽出する。話読みの latest は、公開 product page から参照できる episodes endpoint `https://piccoma.com/web/product/<product_id>/episodes?etype=E` を取得し、episode list の安定識別子から抽出して `LatestEpisode` を返す。

`LatestEpisode` の主な値は次の方針にする。

```text
source: piccoma
work_id: piccoma:<product_id>
latest_key: piccoma:<product_id>:episode:<stable_episode_identifier>
url: canonical product URL
series_title: 作品名
episode_title: 公開 HTML から取れる最新話ラベル
extra:
  freeEpisodeLabel: optional
  waitFreeLabel: optional
  totalEpisodeLabel: optional
```

公開 HTML から個別 episode URL が安定して取得できる場合は `url` に使ってよい。ただし、2026-04-27 の live probe では episode anchor は `href="#"` で、安定値は `data-episode_id` だったため、`url` は product URL のままにする。存在しない episode URL を推測して作らない。

### Registry and watchlist

`manga_watch/sources/registry.py` に `PiccomaAdapter()` を追加する。

`manga_watch/watchlist.py` の `SOURCE_CAPABILITIES` に `piccoma` を追加する。

```text
source: piccoma
domains: piccoma.com
input_labels: product URL
examples: https://piccoma.com/web/product/58170?etype=episode
```

これにより `watchlist add`、duplicate detection、unsupported source / unsupported URL type の既存 flow に乗る。

### Source search

`manga_watch/source_search.py` に `piccoma` を opt-in 追加する。

`_SOURCE_SEARCH_CONFIG` にはピッコマの公開検索 endpoint と allowed domain を追加する。2026-04-27 の live probe では検索 HTML に product anchors はなく、公開 AJAX JSON endpoint `https://piccoma.com/web/search/result_ajax/list?tab_type=T&word=<query>&page=1` の `products[].id` / `products[].title` が安定していた。`_search_piccoma()` はこの JSON を読み、product id から canonical seed URL を組み立てる。

検索結果は次の形に正規化する。

```text
SearchResult(
  source="piccoma",
  title=<作品名>,
  seed_url="https://piccoma.com/web/product/<product_id>?etype=episode",
  subtitle="piccoma",
)
```

`supported_search_sources()` に `piccoma` が入れば、既存 `/search` の source choice と `/supertwins-search` の横断候補検索に自動で参加する。

## Data Flow

### `watchlist add`

ユーザーがピッコマ product URL を渡す。

1. `watchlist.add_watchlist_url()` が URL を受け取る
2. `build_watchlist_preview()` が `build_watchlist_entry()` を呼ぶ
3. registry が `PiccomaAdapter` を選ぶ
4. `normalize()` が `piccoma:<product_id>` と canonical seed URL を返す
5. 既存の duplicate detection が `work_id` で重複を判定する

### Scheduled crawl / manual fetch

1. checker が watchlist entry から `WorkDescriptor` を復元する
2. registry が `PiccomaAdapter.fetch_latest()` を呼ぶ
3. adapter が canonical product page と public episodes endpoint を取得する
4. parser が product page から作品名 / availability label を抽出し、episodes endpoint から latest identifier と episode title label を抽出する
5. `LatestEpisode` が existing state と比較される
6. 差分があれば既存 Discord notification / backlog / status flow に流れる

### `/search`

1. Discord `/search` が source `piccoma` と query を受け取る
2. `search_source("piccoma", query)` が公開検索ページを取得する
3. parser が product URL と title を抽出する
4. ユーザーが候補を選択する
5. 既存の `build_watchlist_preview()` 経由で `PiccomaAdapter.normalize()` が呼ばれる
6. watchlist に visible または hidden として追加される

### `/supertwins-search`

1. root work の `series_title` を query にする
2. `supported_search_sources()` を巡回する
3. root source が `piccoma` の場合はピッコマを skip する
4. root source が他媒体の場合は `piccoma` も候補検索対象になる
5. 選択されたピッコマ候補は hidden watchlist entry として追加され、supertwins group に入る

## Error Handling

HTTP timeout、429、5xx は既存 `RequestsHttpClient` の retry に乗せる。

product page または public episodes endpoint が取得できたが product id、作品名、話読み latest が見つからない場合は `SourceParseError` にする。これは既存 checker / runner の source failure として degraded に流れる。

次の欠損は fatal にしない。

- 無料話数 label がない
- 待てば¥0 label がない
- 全話数 label がない
- 個別 episode URL がない

次の状態は fatal にする。

- product URL 形式ではない
- product page から作品名が取れない
- 話読み latest の安定識別子が取れない
- 話読みタブがなく、今回の accepted scope を満たせない

検索では、HTML 構造変更により候補が抽出できない場合は空結果を返す。HTTP 例外は既存 `/search` の failure/no-results 分岐に委ねる。`/supertwins-search` は既存通り source 単位の検索失敗を握りつぶし、他媒体候補の探索を続ける。

## Testing

### Fixtures

次の fixture bundle を追加する。

- `tests/fixtures/piccoma/normal/`
  - product page から作品名と公開 availability metadata、episodes endpoint から話読み latest を抽出できる
- `tests/fixtures/piccoma/broken_missing_episode/`
  - product page / episodes endpoint は取れるが話読み latest が見つからず `SourceParseError` になる
- `tests/fixtures/source-search/piccoma/01-search.json`
  - 公開検索 JSON から title と product id を抽出できる

fixture には parser が読む HTML / JSON 断片を残す。Cookie、token、viewer id、tracking query、個人情報は含めない。

### Unit tests

`tests/test_sources.py`

- `REGISTERED_SOURCES` に `piccoma` が入る
- concrete adapter discovery が registry と一致する
- `PiccomaAdapter.normalize()` が product URL と query 付き URL を canonical seed にする
- normal fixture が expected `LatestEpisode` を返す
- broken fixture が `SourceParseError` を返す

`tests/test_watchlist.py`

- `watchlist add` が `piccoma.com/web/product/<id>` を追加できる
- canonical seed URL が保存される
- 同じ product id の query 違いを duplicate として扱う
- supported host の unsupported URL type は `unsupported_url_type` になる

`tests/test_source_search.py`

- `supported_search_sources()` に `piccoma` が入る
- ピッコマ検索 fixture から `SearchResult` を返す
- product URL は canonical seed URL に正規化される
- noise link や外部 link は候補にしない

`tests/test_source_drift.py`

- default canary contracts が registered sources を cover する
- fixture client で `piccoma` canary が通る
- drift 時の next action が fixture refresh と source tests の再実行を案内する

### Live canary

`manga_watch/source_drift.py` に `piccoma` canary contract を追加する。

監視 signal は次にする。

- product page が公開 HTML として取得できる
- 作品名が取得できる
- public episodes endpoint が取得できる
- 話読み latest identifier が取得できる
- availability label が取れる場合は observation に出す

live canary の URL は実装時に公開ページで安定している代表作品を選ぶ。canary は unit gate とは分け、drift detection と fixture refresh 導線として扱う。

### Verification

必須 verification:

```bash
/Users/kentoku.matsunami/Documents/GitHub/comic_crawler/.venv/bin/python -m unittest tests.test_sources tests.test_watchlist tests.test_source_drift tests.test_source_search
```

影響が広い場合の追加 verification:

```bash
/Users/kentoku.matsunami/Documents/GitHub/comic_crawler/.venv/bin/python -m unittest tests.test_discord_search tests.test_discord_supertwins tests.test_discord_interactions_search
```

real network search e2e は既存通り env opt-in にする。unit test の合格条件にはしない。

## Open Questions For Implementation

実装前に live probe で次を確定する。

2026-04-27 の live probe で次を確定した。

1. ピッコマ検索 URL は `https://piccoma.com/web/search/result_ajax/list?tab_type=T&word=<query>&page=1`
2. 作品名 signal は product page の `application/ld+json` `Product.name`
3. 話読み latest signal は `https://piccoma.com/web/product/<product_id>/episodes?etype=E` の `#js_episodeList` と `data-episode_id`
4. `episode_title` として使える公開 label は episodes list の最新 item の表示 title
5. availability metadata label は product page の text extraction から `totalEpisodeLabel`, `waitFreeLabel`, `freeEpisodeLabel` として扱う
6. 個別 episode URL は安定しておらず、episode anchors は `href="#"` のため推測生成しない

これらは spec の scope を広げるためではなく、公開 HTML adapter の parser contract を固定するために確認する。

## Acceptance Criteria

- `piccoma` が registered source として追加されている
- `watchlist add` がピッコマ product URL を canonical entry にできる
- ピッコマ product page から話読み latest を取得し、既存 notification / backlog / status flow に流せる
- 無料話数、待てば¥0、全話数などの公開 availability metadata が取れる範囲で state に残る
- `/search` で `piccoma` を選択でき、候補から watchlist 追加できる
- `/supertwins-search` でピッコマが横断候補 source として参加する
- ログイン後情報、購入済み状態、アプリ専用情報を扱わないことが README または source docs に明記されている
- source drift canary がピッコマの公開 HTML signal を監視する
- fixture regression と source search tests が追加されている
