# Docker Compose 単一ホスト向け CI/CD 設計・実装

## 1. 要件整理
- GitHub Actions を起点に、アプリ変更で Docker image を build / push する。
- レジストリは `ghcr.io/example/myapp` を使い、`latest` 依存ではなく追跡可能な識別子（`<branch>-<shortsha>`、`sha-<fullsha>`、digest）を利用する。
- デプロイ先 `/opt/myapp` は Docker Compose で `app` を更新する。
- デプロイ反映は手動前提にせずイベント駆動で行う。
- デプロイ後に `http://127.0.0.1:8080/health` で正常性を確認し、失敗時は失敗扱い + rollback 可能にする。
- シークレットを安全に扱い、ログ・終了コードを明確にする。

## 2. 候補アーキテクチャ比較

### A. CI から SSH 直接反映
- 概要: Actions からホストへ SSH して `docker compose pull && up -d`。
- 長所: 最短で実装可能。
- 短所: CI に強いデプロイ権限が必要、SSH 到達性に依存、今回の「SSH 直依存を避ける」優先度と不一致。

### B. containrrr/watchtower ベース
- 概要: watchtower が新イメージ検知後に更新。
- 長所: 実績ある OSS、Compose と相性がよい。
- 短所: 本命はポーリング運用になりやすく、即時イベント駆動・厳密なデプロイ制御・ロールバック制御を追加で補う必要がある。

### C. OSS webhook receiver (`adnanh/webhook`) + Compose deploy script（採用）
- 概要: Actions が webhook を送信し、ホスト側の `adnanh/webhook` が `deploy.sh` を実行。
- 長所: 実績ある OSS を優先利用、イベント駆動、SSH 非依存、Compose 中心、健康確認と rollback を明示制御できる。
- 短所: webhook 用の最小設定（token, hooks.json）が必要。

### D. microk8s / k3s
- 概要: Kubernetes 化して rollout。
- 長所: 高機能なデプロイ基盤。
- 短所: 今回の制約（Kubernetes 不使用）に抵触するため不採用。

## 3. 採用アーキテクチャ
- 採用は **C案**（OSS webhook receiver + deploy script）。
- `build-push-deploy.yml` がイメージを build/push し、`image_ref` / `image_digest` / `version` / `commit_sha` を webhook payload で送る。
- `/opt/myapp` の Compose が `APP_IMAGE` を参照し、`deploy.sh` が `.env` を更新して `docker compose pull/up` を実行。
- `deploy.sh` が health check を行い、失敗時は自動 rollback。
- 成功時 `current-release.json` を更新し、どの build が deploy されたか追跡可能にする。

## 4. ファイル一覧
- `.github/workflows/build-push-deploy.yml`
- `deploy/compose/docker-compose.yml`
- `deploy/hooks/hooks.json.example`
- `deploy/scripts/deploy.sh`
- `deploy/scripts/rollback.sh`
- `doc/compose_cicd_single_host.md`

## 5. 各ファイルの完全な内容
- 実ファイルを参照（本リポジトリに配置済み）。

## 6. デプロイフローの説明
1. `main` への push で Actions 起動。
2. Docker image を build / push。
3. Actions が deploy webhook (`/hooks/deploy-app` など) に metadata を POST。
4. `adnanh/webhook` が token / branch を検証し `deploy.sh` を実行。
5. `deploy.sh` が `APP_IMAGE` を更新して Compose 反映 (`pull` → `up -d`)。
6. `health` 成功で完了、失敗で rollback。
7. `current-release.json` と `deploy.log` に結果を残す。

## 7. ロールバック方針
- 自動 rollback: deploy 後 health check 失敗時に `PREV_APP_IMAGE` へ復帰。
- 手動 rollback: `rollback.sh <image_ref_or_digest>` を実行。
- 監査情報: `/opt/myapp/current-release.json` と `/opt/myapp/deploy.log`。

## 8. 導入手順
1. ホストに `/opt/myapp` を作成し、以下を配置:
   - `deploy/compose/docker-compose.yml` → `/opt/myapp/docker-compose.yml`
   - `deploy/scripts/deploy.sh` → `/opt/myapp/bin/deploy.sh`
   - `deploy/scripts/rollback.sh` → `/opt/myapp/bin/rollback.sh`
   - `deploy/hooks/hooks.json.example` を `/opt/myapp/hooks/hooks.json` としてコピーし、token を本番値へ置換
2. 実行権限を付与:
   - `chmod +x /opt/myapp/bin/deploy.sh /opt/myapp/bin/rollback.sh`
3. GHCR pull 用認証:
   - `docker login ghcr.io`
4. `/opt/myapp/.env` を用意（最低限）:
   - `APP_IMAGE=ghcr.io/example/myapp:bootstrap`
   - `TZ=Asia/Tokyo`
5. Compose 起動:
   - `docker compose -f /opt/myapp/docker-compose.yml up -d`
6. GitHub Secrets 設定:
   - `DEPLOY_WEBHOOK_URL=http(s)://<host>:9000/hooks/deploy-app`
   - `DEPLOY_WEBHOOK_TOKEN=<hooks.json に設定した値>`
7. `main` へ push し、Actions / `/opt/myapp/deploy.log` / `/opt/myapp/current-release.json` を確認。

## 9. 運用上の注意点
- `9000/tcp` は FW で GitHub Actions 送信元に限定、または reverse proxy + mTLS などを併用。
- `hooks.json` は secret を含むため root 限定権限で管理（例: `chmod 600`）。
- `deploy.log` は logrotate で肥大化を防ぐ。
- 同時デプロイは `flock` と webhook 側の逐次実行で衝突回避。
- 緊急時 rollback は `rollback.sh` と `APP_IMAGE` 直接切替で即応。
