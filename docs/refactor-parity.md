# Refactor Parity Contract

Issue: https://github.com/kentoku24/comic_crawler/issues/339

この文書は、コードベース近代化 refactor の parity contract を固定する。
この Issue の各 pass は、明示された functional change / migration Issue に分離しない限り、
ここに書いた挙動を維持する。

## 1. Public Runtime Entry Points

維持する entry point:

- `python -m manga_watch.check <watchlist_path>`
- `python -m manga_watch.check --status [--format text|json]`
- `python -m manga_watch.runner`
- `python -m manga_watch.run_service`
- `python -m manga_watch.run_job`
- `python -m manga_watch.replay_outbox`
- `python -m manga_watch.backlog`
- `python -m manga_watch.migrate_storage`
- `python -m manga_watch.run_mocked_acceptance`
- `scripts/register_discord_commands.py --dry-run`
- `scripts/register_discord_commands.py`
- `scripts/post_signed_discord_interaction.py`
- `scripts/print_cloud_scheduler_job.py`
- `scripts/export_piccoma_cookie.py`

Passes may move implementation details behind these entry points, but the command shape,
exit-code meaning, and machine-readable JSON shape must stay stable unless a separate
migration Issue is created.

## 2. Environment Variables

維持する env contract:

- `MANGA_WATCH_WATCHLIST`: watchlist v2 path
- `MANGA_WATCH_URLS`: legacy fallback for watchlist path
- `MANGA_WATCH_STATE`: state v2 path
- `MANGA_WATCH_STORAGE_BACKEND`: `json` or `firestore`
- `MANGA_WATCH_NOTIFIER_BACKENDS`
- `MANGA_WATCH_WEBHOOK_URL` / `MANGA_WATCH_WEBHOOK_URL_SECRET_VERSION`
- `DISCORD_BOT_TOKEN` / `DISCORD_BOT_TOKEN_SECRET_VERSION`
- `DISCORD_APPLICATION_ID`
- `DISCORD_GUILD_ID`
- `DISCORD_MAIN_CHANNEL_ID`
- `DISCORD_RUN_REPORT_CHANNEL_ID`
- `DISCORD_APPLICATION_PUBLIC_KEY` / `DISCORD_APPLICATION_PUBLIC_KEY_SECRET_VERSION`
- `MANGA_WATCH_INSECURE_DISABLE_VERIFICATION`
- `MANGA_WATCH_FETCH_BACKEND`
- `MANGA_WATCH_GCP_PROJECT`
- `MANGA_WATCH_CLOUD_RUN_REGION`
- `MANGA_WATCH_CLOUD_RUN_JOB_NAME`
- `MANGA_WATCH_GITHUB_TOKEN`
- `MANGA_WATCH_GITHUB_REPOSITORY`
- `MANGA_WATCH_GITHUB_API_BASE_URL`
- `MANGA_WATCH_HTTP_TIMEOUT`
- `MANGA_WATCH_HTTP_RETRIES`
- `MANGA_WATCH_HTTP_RETRY_BACKOFF`
- `MANGA_WATCH_HTTP_WORKERS`
- `MANGA_WATCH_HTTP_WORKERS_PER_HOST`
- `PICCOMA_COOKIE` / `PICCOMA_COOKIE_SECRET_VERSION`
- `PICCOMA_COOKIE_SECRET_NAME`
- `TZ`
- `CRAWL_SCHEDULE`
- `CRAWL_INTERVAL`
- `RUN_ON_STARTUP`

Secret resolution must continue to prefer direct env values over `*_SECRET_VERSION`.
Removing legacy env support, renaming variables, or changing defaults is a separate
operational migration task.

## 3. Storage Schema

維持する storage contract:

- Watchlist root has `version` and `works`.
- Work entries keep `id`, `source`, `seed_url`, `enabled`, `hidden`,
  `notification_policy`, and source-specific tracking fields.
- State root has `version`, `works`, `last_run_at`, `notification_outbox`, and
  `discord_delivery` where present.
- `latest_runtime_to_storage()` and `latest_storage_to_runtime()` keep camelCase /
  snake_case compatibility.
- Existing legacy `discordDelivery` state must keep normalizing into
  `discord_delivery`.
- JSON backend keeps atomic write behavior.
- Firestore backend keeps the current collection/document contract from
  `doc/gcp-runtime.md`.

Refactor passes may split modules or rename internal helpers, but persisted data shape
must stay readable both before and after the pass.

## 4. Source Identity

維持する source identity contract:

- `work_id` values remain stable for existing watchlist entries.
- `latest_key` remains the stable dedupe identity for each source.
- Piccoma `latest_key` remains `piccoma:<product_id>:episode:<episode_id>`.
- Piccoma story numbering, platform availability numbering, and purchase/readability
  state must not be conflated.
- Source adapter `normalize()` and `fetch_latest()` public behavior remains stable.
- `REGISTERED_SOURCES`, `registered_sources()`, `normalize_seed_url()`, and
  `fetch_latest_for_work()` remain usable public module APIs.

Changing source identity, latest-key construction, or cross-source numbering semantics
is a functional change and must be split out.

## 5. Discord Interaction Contract

維持する command surface:

- `/latest`
- `/fetch`
- `/add`
- `/search`
- `/where`
- `/remove`
- `/supertwins-search`
- `/supertwins-manage`
- `/piccoma-cookie set`

維持する visibility:

- `/latest`, `/fetch`, `/add`: non-ephemeral channel messages
- `/search`, `/where`, `/remove`, `/supertwins-search`, `/supertwins-manage`,
  `/piccoma-cookie set`: existing ephemeral/modal behavior

維持する interaction behavior:

- Request signature verification remains enabled by default.
- `MANGA_WATCH_INSECURE_DISABLE_VERIFICATION` remains a local escape hatch only.
- Deferred callback behavior must continue to satisfy Discord's ACK timing for slow
  command/component flows.
- `allowed_mentions` must continue to suppress automatic mentions for interaction
  response messages.
- Cookie or token values must not be echoed in Discord responses.

## 6. Notification / Runner Contract

維持する runner behavior:

- Scheduled, startup, and Discord-triggered runs keep their trigger-source labels.
- A running fetch rejects concurrent fetch requests with the existing user-facing
  message.
- Update events preserve `event_id`, `work_id`, `latest_key`, update type metadata,
  notification policy metadata, and unread/history behavior.
- Failed delivery remains durable through notification outbox / pending Discord daily
  notification state.
- Run report still summarizes source failures, run-level failures, delivery failures,
  pending outbox counts, and suppressed update counts.

## 7. Source Search / Drift Contract

維持する search behavior:

- `supported_search_sources()` and `search_source()` remain public APIs.
- `/search` and `/supertwins-search` keep their existing source choices and result
  selection flows.
- Real network E2E search tests remain opt-in through existing skip conditions.

維持する drift behavior:

- `python -m manga_watch.source_drift` remains the live canary entry point.
- Canary output remains text by default and JSON when requested.
- Runtime parser and canary parser may share helpers, but canary coverage must not be
  weakened during extraction.

## 8. Required Validation Matrix

Every refactor pass:

```bash
python -m unittest
python -m py_compile <touched python modules>
git diff --check
```

Pass-specific gates:

| Pass | Required focused checks |
| --- | --- |
| Baseline / parity docs | `python -m unittest`; dry-run command registration with dummy Discord env; `python -m manga_watch.check --status --format json` |
| Dead code audit | `rg` reference proof; affected tests removed/updated; `tests.test_watchlist` if CLI compatibility is touched |
| `check.py` extraction | `tests.test_check`; `tests.test_storage` |
| Piccoma availability extraction | Piccoma wait-free tests; `tests.test_sources` |
| Discord command registry | `tests.test_discord_command_registration*`; `tests.test_discord_interactions*`; `tests.test_discord_supertwins_interactions` |
| Storage split | `tests.test_storage`; `tests.test_firestore_storage`; `tests.test_migrate_storage`; web admin tests |
| Source search split | `tests.test_source_search`; Discord search tests |
| Source adapter helpers | `tests.test_sources`; `tests.test_source_drift` |
| Runner/outbox split | `tests.test_runner`; `tests.test_discord_outbound`; `tests.test_run_job` |
| Test helper cleanup | affected test modules; full unittest |

Dry-run command registration requires bot config even when it does not call Discord:

```bash
DISCORD_BOT_TOKEN=dummy DISCORD_APPLICATION_ID=dummy \
  python scripts/register_discord_commands.py --dry-run
```

## 9. Migration Split Triggers

Create a separate migration / behavior-change Issue before doing any of the following:

- dependency upgrades
- framework upgrades
- unittest to pytest migration
- formatter/linter/type-checker introduction
- storage schema version changes
- source identity or latest-key changes
- Discord command name, visibility, or response-payload behavior changes
- removal of legacy env fallback
- change in notification delivery semantics
