---
name: comic-crawler-deploy
description: >
  comic_crawler の main runtime を安全にデプロイする repo-local skill。Use when:
  「デプロイして」「本番反映して」「main checkout のコンテナを立ち上げ直して」
  のように、/Users/kentokumatsunami/Documents/GitHub/comic_crawler を source of truth
  として Docker Compose runtime を更新したいとき、Discord 用 env が code 側で
  compose に渡っているか確認したいとき、足りなければ code を修正して PR を作りたいとき。
---

# Comic Crawler Deploy

## Overview

この skill は comic_crawler の実運用デプロイ手順を固定化する。
コードの source of truth は `main` checkout、secret の source of truth はその checkout の gitignored `.env` とし、両者を混ぜない。
この skill は secret を補完しない。missing env は blocker として扱う。

## Fixed Runtime Contract

- deploy target checkout は `/Users/kentokumatsunami/Documents/GitHub/comic_crawler`
- deploy は target checkout から `docker compose up -d --build --force-recreate` を実行する
- runtime container の `com.docker.compose.project.working_dir` は上記 path を指しているべき
- local `.env` は gitignored であり、tracked file や PR に secret を書かない

必要な local secret env は次の 3 つだけを基本とする。

- `DISCORD_BOT_TOKEN`
- `DISCORD_MAIN_CHANNEL_ID`
- `DISCORD_RUN_REPORT_CHANNEL_ID`

次の値は compose / app default があるので、local `.env` に残さないことを優先する。

- `MANGA_WATCH_NOTIFIER_BACKENDS`
- `DISCORD_INBOUND_ENABLED`
- `DISCORD_COMMAND_POLL_INTERVAL`
- `TZ`
- `CRAWL_SCHEDULE`
- `RUN_ON_STARTUP`

## Workflow

### 1. Preflight

- target checkout の branch / `git status -sb` / `origin/main` との差分を確認する
- `docker ps` または `docker inspect` で現行コンテナの working dir を確認する
- target checkout が `main` で `origin/main` に追従できる状態かを見る
- unrelated な local change は勝手に戻さない

tracked change が `main` の fast-forward や deploy を妨げる場合は、そのまま進めず blocker として報告する。

### 2. Code-side Env Contract

deploy 前に target checkout の `docker-compose.yml` と `.env.example` を見て、少なくとも次が code 側に存在することを確認する。

- `DISCORD_BOT_TOKEN`
- `DISCORD_MAIN_CHANNEL_ID`
- `DISCORD_RUN_REPORT_CHANNEL_ID`

`DISCORD_INBOUND_ENABLED` と `DISCORD_COMMAND_POLL_INTERVAL` は default 付きなら十分。

もし required key が code 側に無ければ:

- current workspace で修正する
- 関連テストを回す
- branch を切って PR を作る
- `main` へ入っていない状態では「本番 deploy 完了」とは言わない

一時的な shell 注入だけで誤魔化さない。

### 3. Local Env Check

- target checkout の `.env` を確認する
- required secret key が無ければ deploy blocker として止める
- `.env` の cleanup を明示的に頼まれたときだけ、default を上書きしているだけの不要 key を削る
- `.env` は commit しない

### 4. Deploy

target checkout で次を実行する。

```bash
docker compose up -d --build --force-recreate
```

必要なら `git pull --ff-only origin main` を先に行うが、local tracked change を潰してまで進めない。

### 5. Verification

少なくとも次を確認する。

- `docker compose ps` で `comic-crawler` が `Up`
- container working dir が `/Users/kentokumatsunami/Documents/GitHub/comic_crawler`
- startup run が `ok: True` で、`configuration error` が無い
- 次回実行時刻が出ている

inbound command が有効なときは、追加で次を確認する。

- `docker compose logs --tail=... comic-crawler` に `[discord] command listener started:` が出る

`DISCORD_INBOUND_ENABLED=false` のように inbound command を無効化している構成では、listener start log が出なくても deploy failure とみなさない。

`DISCORD_BOT_TOKEN is required` などの設定エラーが出た場合は、まず local `.env` と code-side env passthrough を疑う。

## Result Contract

返答には次を含める。

- code change が必要だったか
- 必要だったなら PR URL
- local `.env` が deploy blocker だったか、cleanup をしたなら削除した key
- deploy 後の container status
- working dir とログ確認結果

## Guardrails

- 実運用 deploy は worktree ではなく fixed target checkout から行う
- secret は `.env` にだけ置き、tracked file・commit・PR body・chat summary に書かない
- missing secret を自動補完しない
- unrelated change は revert しない
- local `.env` cleanup は明示依頼があるときだけ行う
- `docker compose` の成功だけで終わらず、startup log まで見る
