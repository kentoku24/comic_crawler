# GCP Deploy Contract

この文書は `comic_crawler` repo の canonical GCP naming / deploy contract である。  
GCP 上の resource 名、production artifact source of truth、GitHub Actions deploy / rollback 契約、検証コマンドをここで固定する。

## 0. Related source of truth

- 日常運用の入口は [`README.md`](../README.md)
- operator 向けの手順は [`doc/運用手順書.md`](./運用手順書.md)
- runtime の backend env / Firestore schema / Secret Manager mapping は [`doc/gcp-runtime.md`](./gcp-runtime.md)

## 1. Canonical contract

| 項目 | Canonical value |
| --- | --- |
| project | `star-light-breaker` |
| region | `asia-northeast1` |
| zone | `asia-northeast1-a` |
| Cloud Run Job | `comic-crawler-job` |
| Cloud Run Service | `comic-crawler-service` |
| Cloud Scheduler Job | `comic-crawler-scheduled-run` |
| Scheduler service account id | `comic-crawler-scheduler` |
| Scheduler service account email | `comic-crawler-scheduler@star-light-breaker.iam.gserviceaccount.com` |
| Artifact Registry repository | `asia-northeast1-docker.pkg.dev/star-light-breaker/comic-crawler/comic-crawler` |
| GitHub deploy workflow | `.github/workflows/deploy-production.yml` |
| GitHub rollback workflow | `.github/workflows/rollback-production.yml` |
| GitHub deploy environment | `production` |
| Local Compose service | `comic-crawler` |
| Current container entrypoint | `python -m manga_watch.runner` |
| Cloud Run Job command override | `python -m manga_watch.run_job` |
| Cloud Run Service command override | `python -m manga_watch.run_service` |

使い分けは次で固定する。

- `comic-crawler-job`: 定期クロール実行用の Cloud Run Job 名
- `comic-crawler-service`: Discord interaction endpoint 用 Cloud Run Service 名
- `comic-crawler-scheduled-run`: Cloud Scheduler から Cloud Run Jobs API を叩く Job 名
- Artifact Registry repository: production image の source of truth
- GHCR (`ghcr.io/kentoku24/comic_crawler`): 既存 publish workflow の publish 先だが、production deploy source of truth ではない

## 2. Current operating model

production deploy は GitHub Actions を control plane とし、手順は次で固定する。

1. `main` への push で `deploy-production.yml` が起動する
2. `test` job が unit tests を実行する
3. `build` job が Artifact Registry に commit SHA tag 付き image を push し、resolved digest を出力する
4. `deploy` job が GitHub `production` environment の reviewer gate で待機する
5. 承認後に Cloud Run Job / Service を同じ digest に更新する
6. 失敗時は `rollback-production.yml` を `workflow_dispatch` で起動し、指定 digest を再 deploy する

重要:

- deploy / rollback の source of truth は digest 固定の image ref であり、mutable tag ではない
- GitHub Actions 上の log / summary と GCP 上の実 digest を一致させて検証する
- GitHub 上に長期 service account key JSON は置かない

## 3. GitHub prerequisites

### 3.1 Repository variables

少なくとも次を repository variables として設定する。

- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT_EMAIL`
- `DISCORD_MAIN_CHANNEL_ID`
- `DISCORD_RUN_REPORT_CHANNEL_ID`

build job でも GCP 認証が必要なため、`GCP_WORKLOAD_IDENTITY_PROVIDER` と `GCP_SERVICE_ACCOUNT_EMAIL` は environment variable ではなく repository variable として使う前提にする。

### 3.2 GitHub environment

`production` environment を作成し、required reviewers を設定する。  
`deploy-production.yml` の `deploy` job と `rollback-production.yml` の `rollback` job は、どちらも `environment: production` で reviewer gate を通す。

reviewer は GitHub UI から次の flow で承認する。

1. workflow run を開く
2. `Review deployments` を押す
3. `production` を選ぶ
4. `Approve and deploy` を押す

## 4. GCP authentication contract

GitHub Actions から GCP への認証は Workload Identity Federation を使う。

前提:

- Workload Identity Pool
- Workload Identity Provider
- GitHub Actions から impersonate される service account

最低限必要な role 候補:

- `roles/artifactregistry.writer`
- `roles/run.admin`
- `roles/iam.serviceAccountUser`
- 必要に応じて `roles/secretmanager.secretAccessor`

初回実装では build / deploy / rollback で同一 service account を使ってよいが、role は最小権限を保つ。

## 5. Workflow contract

### 5.1 `deploy-production.yml`

source of truth:

- trigger: `push` on `main`
- jobs: `test`, `build`, `deploy`
- `deploy` job: `environment: production`
- Artifact Registry push: commit SHA tag
- deploy source of truth: resolved digest

deploy job が実行する contract shape:

```bash
gcloud run jobs update comic-crawler-job \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --image=asia-northeast1-docker.pkg.dev/star-light-breaker/comic-crawler/comic-crawler@sha256:<digest> \
  --command=python \
  --args=-m,manga_watch.run_job

gcloud run deploy comic-crawler-service \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --image=asia-northeast1-docker.pkg.dev/star-light-breaker/comic-crawler/comic-crawler@sha256:<digest> \
  --command=python \
  --args=-m,manga_watch.run_service \
  --allow-unauthenticated
```

workflow summary / log には少なくとも次が残ること。

- target commit SHA
- target image digest
- target image ref
- Cloud Run Service latest ready revision
- Cloud Run Job image ref

### 5.2 `rollback-production.yml`

source of truth:

- trigger: `workflow_dispatch`
- input: `image_ref`
- `rollback` job: `environment: production`
- rollback source of truth: `asia-northeast1-docker.pkg.dev/star-light-breaker/comic-crawler/comic-crawler@sha256:<digest>`

validation は少なくとも次を満たす。

- input が canonical Artifact Registry digest ref 形式である
- `gcloud artifacts docker images describe <image_ref>` が成功する

rollback job は通常 deploy と同じ GCP resource を、指定 digest に更新する。

## 6. Cloud Run resource contract

### 6.1 Cloud Run Job

canonical name は `comic-crawler-job`。deploy / rollback では one-shot 実行のため `python -m manga_watch.run_job` を command override する。

必要 env contract:

- `TZ=Asia/Tokyo`
- `MANGA_WATCH_STORAGE_BACKEND=firestore`
- `MANGA_WATCH_FIRESTORE_PROJECT=star-light-breaker`
- `MANGA_WATCH_NOTIFIER_BACKENDS=stdout`
- `DISCORD_MAIN_CHANNEL_ID=<configured channel id>`
- `DISCORD_RUN_REPORT_CHANNEL_ID=<configured channel id>`
- `DISCORD_BOT_TOKEN_SECRET_VERSION=projects/star-light-breaker/secrets/comic-crawler-discord-bot-token/versions/latest`

### 6.2 Cloud Run Service

canonical name は `comic-crawler-service`。deploy / rollback では `python -m manga_watch.run_service` を command override して起動する。

必要 env / secret contract:

- `TZ=Asia/Tokyo`
- `MANGA_WATCH_STORAGE_BACKEND=firestore`
- `MANGA_WATCH_FIRESTORE_PROJECT=star-light-breaker`
- `MANGA_WATCH_FETCH_BACKEND=cloud-run-job`
- `MANGA_WATCH_GCP_PROJECT=star-light-breaker`
- `MANGA_WATCH_CLOUD_RUN_REGION=asia-northeast1`
- `MANGA_WATCH_CLOUD_RUN_JOB_NAME=comic-crawler-job`
- `DISCORD_BOT_TOKEN_SECRET_VERSION=projects/star-light-breaker/secrets/comic-crawler-discord-bot-token/versions/latest`
- `DISCORD_APPLICATION_PUBLIC_KEY=comic-crawler-discord-application-public-key:latest`

service behavior notes:

- Discord interaction endpoint は public ingress を前提にし、Slash Command の `POST /` は Discord request signature で認証する
- lightweight keep-warm / monitoring 用に `GET /healthz` は signature なしで `200 ok` を返す
- production では `MANGA_WATCH_INSECURE_DISABLE_VERIFICATION=true` を使わない
- `MANGA_WATCH_FETCH_BACKEND=cloud-run-job` のとき `fetch` は Cloud Run Jobs API へ manual override 付きで handoff する
- local fallback として `MANGA_WATCH_FETCH_BACKEND=coordinator` を使って in-process 実行もできる

## 7. Post-deploy verification

deploy / rollback 後の客観的確認は、GitHub Actions の target digest と GCP 上の実 digest を照合して行う。

### 7.1 Job image

```bash
gcloud run jobs describe comic-crawler-job \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --format='value(spec.template.template.containers[0].image)'
```

### 7.2 Service latest ready revision

```bash
gcloud run services describe comic-crawler-service \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --format='value(status.latestReadyRevisionName)'
```

### 7.3 Service revision digest

```bash
gcloud run revisions describe <latest-ready-revision> \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --format='value(status.imageDigest)'
```

### 7.4 Service health endpoint

```bash
SERVICE_URL="$(gcloud run services describe comic-crawler-service \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --format='value(status.url)')"

curl -fsS "$SERVICE_URL/healthz"
```

完了判定:

- Job image ref が workflow summary の target image ref と一致する
- Service revision digest が workflow summary の target image digest と一致する

## 8. Rollback verification

`rollback-production.yml` に入力した `image_ref` を source of truth とし、上記 7.1-7.3 のコマンドで Job / Service が同じ digest を参照していることを確認する。

validation failure の期待値:

- 不正形式の `image_ref` は validation job で失敗する
- Artifact Registry に存在しない `image_ref` も validation job で失敗する
- どちらも Cloud Run 更新前で止まる

## 9. Scheduler caller IAM

Cloud Scheduler は `https://run.googleapis.com/...` を叩くので、OIDC ではなく OAuth service account auth を使う。  
Scheduler caller service account は `comic-crawler-scheduler@star-light-breaker.iam.gserviceaccount.com` を canonical とする。

service account 作成:

```bash
gcloud iam service-accounts create comic-crawler-scheduler \
  --project=star-light-breaker \
  --display-name="comic-crawler scheduler"
```

最低限必要な Job 側 role:

- `roles/run.jobsExecutorWithOverrides`

binding 例:

```bash
gcloud run jobs add-iam-policy-binding comic-crawler-job \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --member="serviceAccount:comic-crawler-scheduler@star-light-breaker.iam.gserviceaccount.com" \
  --role="roles/run.jobsExecutorWithOverrides"
```

備考:

- `roles/run.jobsExecutor` では `run.jobs.runWithOverrides` を含まないため、この contract には不足
- Scheduler job を create / update する operator 側には `iam.serviceAccounts.actAs` も必要

## 10. Cloud Scheduler contract

Scheduler target は Cloud Run Jobs API の run endpoint に固定する。

```text
https://run.googleapis.com/v2/projects/star-light-breaker/locations/asia-northeast1/jobs/comic-crawler-job:run
```

request body は override で `MANGA_WATCH_TRIGGER_SOURCE=scheduled` を渡す。

```json
{
  "overrides": {
    "containerOverrides": [
      {
        "env": [
          {
            "name": "MANGA_WATCH_TRIGGER_SOURCE",
            "value": "scheduled"
          }
        ]
      }
    ]
  }
}
```

helper script で create command を出す:

```bash
SCHEDULE="0 * * * *"
python3 scripts/print_cloud_scheduler_job.py create --schedule "$SCHEDULE"
```

helper script で update command を出す:

```bash
SCHEDULE="0 * * * *"
python3 scripts/print_cloud_scheduler_job.py update --schedule "$SCHEDULE"
```

helper script は次を固定で出力する。

- HTTP method: `POST`
- auth: OAuth service account token
- scope: `https://www.googleapis.com/auth/cloud-platform`
- header: `Content-Type=application/json`
- message body: Cloud Run Job `run` override payload
- time zone default: `Asia/Tokyo`

`SCHEDULE` の cron 自体は deployment decision であり、この task では canonical 値として固定しない。

### 10.1 Keep-warm ping for Cloud Run Service

Cloud Run Service の scale-to-zero 緩和を目的として、Scheduler から service 自体へ `GET /healthz` を送る keep-warm ping を別 job として持ってよい。

```bash
SERVICE_URL="$(gcloud run services describe comic-crawler-service \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --format='value(status.url)')"

gcloud scheduler jobs create http comic-crawler-service-keep-warm \
  --project=star-light-breaker \
  --location=asia-northeast1 \
  --schedule='*/5 * * * *' \
  --uri="${SERVICE_URL}/healthz" \
  --http-method=GET
```

helper script で command shape を固定したい場合は以下。

```bash
python3 scripts/print_keep_warm_scheduler_job.py create \
  --service-url "${SERVICE_URL}"
```

補足:

- この ping は cold start 発生率を下げるための best effort であり、`min instances=1` ほどの保証はない
- 初期値は 5 分間隔とする
- `comic-crawler-scheduled-run` とは別用途なので、job 名は分ける

## 9. Practical run / verify

この節は、上の contract を GCP で実際に確認するための実用コマンドをまとめる。
個別の運用判断は [`README.md`](../README.md) と [`doc/運用手順書.md`](./運用手順書.md) を優先し、この文書では command shape を source of truth として残す。

### Cloud Run Job の手動 run

```bash
gcloud run jobs execute comic-crawler-job \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --wait
```

### Cloud Scheduler の force-run

```bash
gcloud scheduler jobs run comic-crawler-scheduled-run \
  --project=star-light-breaker \
  --location=asia-northeast1
```

### Cloud Run Job / Service の logs 確認

```bash
gcloud run jobs logs read comic-crawler-job \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --limit=50

gcloud run services logs read comic-crawler-service \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --limit=50
```

### Cloud Logging の直接確認

```bash
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="comic-crawler-job"' \
  --project=star-light-breaker \
  --freshness=1d \
  --limit=20 \
  --format='value(timestamp,resource.type,textPayload)'

gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="comic-crawler-service"' \
  --project=star-light-breaker \
  --freshness=1d \
  --limit=20 \
  --format='value(timestamp,resource.type,textPayload)'
```

### Helper script の確認

```bash
python3 scripts/print_cloud_scheduler_job.py create --schedule "0 * * * *"
python3 scripts/print_cloud_scheduler_job.py update --schedule "0 * * * *"
```

- helper script は Cloud Scheduler の create / update command shape を固定する
- Cloud Run Job は `comic-crawler-job`
- Cloud Run Service は `comic-crawler-service`
- Scheduler force-run は `comic-crawler-scheduled-run` に対して実行する
