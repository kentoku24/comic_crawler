# GCP Runtime Contract

この文書は `#145` の source of truth として、Firestore persistence / Secret Manager resolution / migration contract を固定する。

## 1. Backend switch

- local default: `MANGA_WATCH_STORAGE_BACKEND=json`
- GCP runtime: `MANGA_WATCH_STORAGE_BACKEND=firestore`
- local default の watchlist/state path は従来どおり `MANGA_WATCH_WATCHLIST` / `MANGA_WATCH_STATE`
- Firestore backend では `load_watchlist` / `load_state` / `save_watchlist` / `save_state` の public API は維持しつつ、backend を Firestore に切り替える

Firestore backend 用 env:

- `MANGA_WATCH_FIRESTORE_PROJECT`
- `MANGA_WATCH_FIRESTORE_DATABASE` (default: `(default)`)
- `MANGA_WATCH_FIRESTORE_WATCHLIST_COLLECTION` (default: `watchlists`)
- `MANGA_WATCH_FIRESTORE_WATCHLIST_DOCUMENT` (default: `current`)
- `MANGA_WATCH_FIRESTORE_STATE_COLLECTION` (default: `states`)
- `MANGA_WATCH_FIRESTORE_STATE_DOCUMENT` (default: `runtime`)
- `MANGA_WATCH_FIRESTORE_RUNS_COLLECTION` (default: `runs`)
- `MANGA_WATCH_FIRESTORE_NOTIFICATION_DEDUPE_COLLECTION` (default: `notification_dedupe`)
- `MANGA_WATCH_FIRESTORE_DELIVERY_BACKLOG_COLLECTION` (default: `delivery_backlog`)

## 2. Secret resolution

secret は direct env を優先し、未設定時だけ `*_SECRET_VERSION` を解決する。

- `DISCORD_BOT_TOKEN` or `DISCORD_BOT_TOKEN_SECRET_VERSION`
- `MANGA_WATCH_WEBHOOK_URL` or `MANGA_WATCH_WEBHOOK_URL_SECRET_VERSION`

`*_SECRET_VERSION` は Secret Manager の version resource name をそのまま入れる。

例:

```bash
export DISCORD_BOT_TOKEN_SECRET_VERSION="projects/star-light-breaker/secrets/comic-crawler-discord-bot-token/versions/latest"
export MANGA_WATCH_WEBHOOK_URL_SECRET_VERSION="projects/star-light-breaker/secrets/comic-crawler-webhook-url/versions/latest"
```

## 3. Firestore schema

watchlist/state の canonical doc は次で固定する。

- `watchlists/current`: watchlist v2 payload 全体
- `states/runtime`: state v2 payload 全体

runtime から導出される collection は次で固定する。

- `runs/<run_id>`: `run_once` outcome の summary
- `notification_dedupe/<work_id>`: `discord_delivery.daily_notification.delivered_latest_keys`
- `delivery_backlog/<doc_id>`: `notification_outbox` と Discord daily pending message の pending delivery state

補足:

- backlog / dedupe の primary source of truth は引き続き `states/runtime`
- `notification_dedupe` と `delivery_backlog` は smoke test と運用確認のための shadow collection

## 4. Migration

JSON watchlist/state を Firestore backend へ投入する entrypoint は次で固定する。

```bash
export MANGA_WATCH_STORAGE_BACKEND=firestore
export MANGA_WATCH_FIRESTORE_PROJECT=star-light-breaker
.venv/bin/python -m manga_watch.migrate_storage \
  --watchlist-json manga_watch/watchlist.json \
  --state-json manga_watch/state.json
```

machine-readable output が必要なとき:

```bash
.venv/bin/python -m manga_watch.migrate_storage --json
```

## 5. Deploy / smoke handoff

`#139` が参照すべき最低限の command shape は次である。

```bash
export MANGA_WATCH_STORAGE_BACKEND=firestore
export MANGA_WATCH_FIRESTORE_PROJECT=star-light-breaker
export DISCORD_BOT_TOKEN_SECRET_VERSION="projects/star-light-breaker/secrets/comic-crawler-discord-bot-token/versions/latest"
export MANGA_WATCH_WEBHOOK_URL_SECRET_VERSION="projects/star-light-breaker/secrets/comic-crawler-webhook-url/versions/latest"
.venv/bin/python -m manga_watch.migrate_storage --watchlist-json manga_watch/watchlist.json --state-json manga_watch/state.json
.venv/bin/python -m manga_watch.runner
```

## 6. Local fallback boundary

- local / compose / unit test default は JSON backend のまま維持する
- Firestore / Secret Manager を使うのは env が明示されたときだけ
- direct env と `*_SECRET_VERSION` が両方ある場合は direct env を優先する
