# GCP Deploy Automation Design

**Date:** 2026-04-04
**Repository:** `kentoku24/comic_crawler`
**Status:** Proposed

---

## Goal

`main` へのマージ後に production deploy を半自動化する。  
build と image push は自動化し、Cloud Run Job / Service への本番反映だけを GitHub 上の手動承認で止める。  
あわせて、過去の安定 image digest を明示指定して切り戻せる手動 rollback workflow を追加する。

## Current State

### Repo-managed automation

- GitHub Actions には `main` push を契機に GHCR へ image を publish する workflow がある
- repo 内には Artifact Registry push や Cloud Run deploy を行う workflow はない
- README の既存 deployment 更新手順は `git pull` と `docker compose up -d --build` を前提としている

### GCP-managed runtime

- production artifact source of truth は `asia-northeast1-docker.pkg.dev/star-light-breaker/comic-crawler/comic-crawler`
- Cloud Run Job `comic-crawler-job` が定期クロール本体
- Cloud Run Service `comic-crawler-service` が Discord interaction endpoint
- Cloud Scheduler `comic-crawler-scheduled-run` が Job 実行を起動
- 現状の Job / Service 更新は `gcloud run jobs update` と `gcloud run deploy` を人手で実行している

## Non-Goals

- Cloud Deploy の導入
- blue/green や canary など段階的リリース
- multi-environment 展開
- Scheduler / Firestore / Secret Manager contract の再設計
- runtime code の挙動変更

## Requirements

### Functional requirements

1. `main` push で unit tests が走ること
2. `main` push で production 用 image が Artifact Registry に push されること
3. deploy 対象は mutable tag ではなく immutable digest で固定されること
4. production deploy は GitHub Environment 承認後にだけ実行されること
5. deploy 時に Cloud Run Job と Cloud Run Service の両方が同じ digest に更新されること
6. rollback workflow で任意の過去 digest を入力して再 deploy できること
7. rollback も production 承認後にだけ実行されること
8. workflow 実行ログから commit SHA と image digest と deploy 結果が追跡できること

### Operational requirements

- GitHub Secrets に長期 GCP service account key を置かない
- deploy 対象 digest が明示され、承認者が確認できる
- rollback 手順が通常 deploy と同じ認証・承認モデルで動く
- 既存 Cloud Run resource 名と env contract を維持する

## Proposed Architecture

GitHub Actions を deployment control plane とし、GCP 認証は Workload Identity Federation を使う。

### Workflow 1: `deploy-production.yml`

Trigger:

- `push` on `main`
- 任意で `workflow_dispatch` を追加して再実行可能にしてもよい

Jobs:

1. `test`
   - 既存 unit test suite を実行する

2. `build`
   - Google auth を行う
   - Artifact Registry にログインする
   - Docker image を build する
   - image を `:<commit-sha>` tag で push する
   - push 後に image digest を取得する
   - digest を job output として次 job に渡す

3. `deploy`
   - `environment: production`
   - required reviewers により承認待ちになる
   - 承認後、digest 固定で以下を実行する
     - `gcloud run jobs update comic-crawler-job --image=<digest> ...`
     - `gcloud run deploy comic-crawler-service --image=<digest> ...`
   - 実行結果として digest と revision / update 完了をログに出す

### Workflow 2: `rollback-production.yml`

Trigger:

- `workflow_dispatch`

Inputs:

- `image_ref`
  - 形式: `asia-northeast1-docker.pkg.dev/star-light-breaker/comic-crawler/comic-crawler@sha256:<digest>`

Jobs:

1. `validate`
   - 入力が digest reference 形式か確認する
   - Artifact Registry に対象 image が存在するか確認する

2. `rollback`
   - `environment: production`
   - required reviewers により承認待ちになる
   - 承認後、通常 deploy と同じコマンドで Job / Service を指定 digest に更新する

## Authentication Model

GitHub Actions から GCP への認証は Workload Identity Federation を使う。

### Why

- JSON key を GitHub Secrets に保存しなくてよい
- deploy 権限を workflow 実行時に限定できる
- 監査ログ上も GitHub Actions 由来の操作として追いやすい

### GCP resources

- Workload Identity Pool
- Workload Identity Provider
- build 用 service account
- deploy 用 service account

最初の導入では build と deploy を 1 つの service account にまとめても動くが、長期的には分離が望ましい。

## Permissions

### Build identity

- Artifact Registry へ image push できること

候補:

- `roles/artifactregistry.writer`

### Deploy identity

- Cloud Run Service 更新
- Cloud Run Job 更新
- Secret 参照に必要な権限

候補:

- `roles/run.admin`
- `roles/iam.serviceAccountUser`
- Secret access が必要なら `roles/secretmanager.secretAccessor`

最小権限化は implementation で再確認する。

## Deployment Contract

既存 contract を崩さず、image 参照だけを digest 固定にする。

### Cloud Run Job

- resource name: `comic-crawler-job`
- command override: `python -m manga_watch.run_job`
- region: `asia-northeast1`
- project: `star-light-breaker`

### Cloud Run Service

- resource name: `comic-crawler-service`
- command override: `python -m manga_watch.run_service`
- region: `asia-northeast1`
- project: `star-light-breaker`

### Image reference policy

- build では commit SHA tag を使う
- deploy / rollback では resolved digest を使う
- `latest` tag は人が見る補助情報としては残しても、deploy source of truth にはしない

## Failure Handling

### Build failure

- deploy job へ進まない
- GitHub Actions 上で失敗として終了する

### Deploy failure

- 承認後の deploy job が失敗として記録される
- Cloud Run Job と Service の片方だけ更新された場合に備え、対象 digest をログに必ず残す
- 運用上は `rollback-production.yml` で直前の安定 digest に戻す

### Rollback failure

- validation 失敗なら deploy 前で停止
- rollback 実行失敗時は GitHub Actions ログを source of truth とし、必要なら手動 `gcloud` で復旧する

## Observability

deploy job と rollback job は最低限次を出力する。

- target commit SHA
- target image digest
- Cloud Run Service latest ready revision
- Cloud Run Job update 完了メッセージ

必要なら後続で GitHub Actions summary に見やすく整形する。

## Security Considerations

- production deploy は GitHub Environment reviewers で保護する
- workflow は `main` push に限定する
- GCP 認証は short-lived credential を使う
- rollback も同じ reviewer gate を通す
- digest 形式以外の image 指定は rollback workflow で拒否する

## Testing Strategy

### Repo-level verification

- workflow YAML の lint
- 既存 unit tests
- `workflow_dispatch` を使った dry-run 相当の検証

### Runtime verification

- build 後に digest が解決できること
- deploy 後に Cloud Run Service revision が更新されること
- rollback 後に指定 digest が反映されること

最初の導入では smoke execution の自動実行までは必須にしない。deploy パイプライン安定化後に必要なら追加する。

## Migration Plan

1. GitHub 側に `production` environment を作る
2. Workload Identity Federation を構成する
3. Artifact Registry push が GitHub Actions から通るようにする
4. `deploy-production.yml` を追加する
5. `rollback-production.yml` を追加する
6. 既存 GHCR publish workflow の役割を見直す
   - 残すなら GitHub package publish 用
   - 不要なら削除候補
7. 運用手順書と GCP deploy contract を update する

## Open Questions

1. GHCR publish workflow を併存させるか、Artifact Registry 中心に整理するか
2. build identity と deploy identity を初回から分離するか
3. deploy 後に smoke job execution を自動で走らせるか

## Recommendation

初回導入は次で始める。

- GitHub Actions 1 本で `test -> build -> approve -> deploy`
- 別 workflow で `approve -> rollback`
- image は commit SHA tag で push し、deploy は digest 固定
- GCP 認証は Workload Identity Federation
- smoke execution は first version では入れない

これが最小の運用負荷で、誤 deploy を抑えながら rollback 可能性も確保できる。
