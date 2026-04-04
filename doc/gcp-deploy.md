# GCP Deploy Contract

この文書は `comic_crawler` repo の canonical GCP naming / deploy contract である。  
GCP 上の resource 名、artifact image、Scheduler 呼び出し契約、未解決 blocker をここで固定する。

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
| Artifact image | `ghcr.io/kentoku24/comic_crawler:latest` |
| Local Compose service | `comic-crawler` |
| Current container entrypoint | `python -m manga_watch.runner` |
| Cloud Run Job command override | `python -m manga_watch.run_job` |

使い分けは次で固定する。

- `comic-crawler-job`: 定期クロール実行用の Cloud Run Job 名
- `comic-crawler-service`: 将来の Discord interaction endpoint 用 Cloud Run Service 名
- `comic-crawler-scheduled-run`: Cloud Scheduler から Cloud Run Jobs API を叩く Job 名

## 2. Observed baseline

2026-03-25 に [#143 の確認コメント 1](https://github.com/kentoku24/comic_crawler/issues/143#issuecomment-4127050468) と [確認コメント 2](https://github.com/kentoku24/comic_crawler/issues/143#issuecomment-4127061135) で採取した observed baseline は次のとおり。ここでは issue #143 の確認証跡を canonical naming 契約の基準点として参照し、現時点の環境状態を repo 単体で断定しない。

- Cloud Run jobs list: `[]`
- Cloud Run services list: `[]`
- Cloud Scheduler jobs list: `[]`

再確認コマンド:

```bash
gcloud run jobs list \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --format='value(name)'

gcloud run services list \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --format='value(name)'

gcloud scheduler jobs list \
  --project=star-light-breaker \
  --location=asia-northeast1 \
  --format='value(name)'
```

## 3. Current scope and blockers

この task が追加するのは resource contract と command source of truth までであり、GCP runtime 完了はまだ主張しない。

- Firestore / Secret Manager / migration contract は [doc/gcp-runtime.md](./gcp-runtime.md) を source of truth とする
- 実環境 smoke test は [#139](https://github.com/kentoku24/comic_crawler/issues/139) が blocker
- Discord interaction endpoint / signature verification は [#146](https://github.com/kentoku24/comic_crawler/issues/146) で source of truth を追加した
- 現在 publish される image は `python -m manga_watch.runner` を起動する long-running container であり、Cloud Run Job の「1 execution で終了する task」にはまだ合わせ切れていない

したがって、この文書の `create` / `update` command は canonical resource を揃えるための contract であり、production-ready runtime 完了の宣言ではない。

## 4. Describe commands

```bash
gcloud run jobs describe comic-crawler-job \
  --project=star-light-breaker \
  --region=asia-northeast1

gcloud run services describe comic-crawler-service \
  --project=star-light-breaker \
  --region=asia-northeast1

gcloud scheduler jobs describe comic-crawler-scheduled-run \
  --project=star-light-breaker \
  --location=asia-northeast1
```

## 5. Cloud Run Job contract

Cloud Run Job の canonical name は `comic-crawler-job`。artifact image は `ghcr.io/kentoku24/comic_crawler:latest` を使い、Job 側では one-shot 実行のため `python -m manga_watch.run_job` を command override する。

作成:

```bash
gcloud run jobs create comic-crawler-job \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --image=ghcr.io/kentoku24/comic_crawler:latest \
  --command=python \
  --args=-m,manga_watch.run_job \
  --tasks=1 \
  --max-retries=0 \
  --set-env-vars=TZ=Asia/Tokyo,MANGA_WATCH_NOTIFIER_BACKENDS=stdout,DISCORD_MAIN_CHANNEL_ID=<main-channel-id>,DISCORD_RUN_REPORT_CHANNEL_ID=<run-report-channel-id>,DISCORD_BOT_TOKEN_SECRET_VERSION=projects/star-light-breaker/secrets/comic-crawler-discord-bot-token/versions/latest
```

更新:

```bash
gcloud run jobs update comic-crawler-job \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --image=ghcr.io/kentoku24/comic_crawler:latest \
  --command=python \
  --args=-m,manga_watch.run_job \
  --tasks=1 \
  --max-retries=0 \
  --update-env-vars=TZ=Asia/Tokyo,MANGA_WATCH_NOTIFIER_BACKENDS=stdout,DISCORD_MAIN_CHANNEL_ID=<main-channel-id>,DISCORD_RUN_REPORT_CHANNEL_ID=<run-report-channel-id>,DISCORD_BOT_TOKEN_SECRET_VERSION=projects/star-light-breaker/secrets/comic-crawler-discord-bot-token/versions/latest
```

手動実行:

```bash
gcloud run jobs execute comic-crawler-job \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --wait
```

注意:

- 上の `execute` command は API / CLI shape の source of truth として残す
- default container entrypoint は long-running runner のままだが、Cloud Run Job では `python -m manga_watch.run_job` を command override して 1 execution で終了させる
- Firestore / Secret Manager / migration contract は `doc/gcp-runtime.md` を参照する
- production-ready な Job 実行経路の実環境確認は #139 と後続 runtime packet が入るまで未完了

## 6. Cloud Run Service contract

Cloud Run Service の canonical name は `comic-crawler-service`。Discord interaction endpoint は `python -m manga_watch.run_service` を command override して起動する。

production deploy shape:

```bash
gcloud run deploy comic-crawler-service \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --image=ghcr.io/kentoku24/comic_crawler:latest \
  --command=python \
  --args=-m,manga_watch.run_service \
  --allow-unauthenticated \
  --set-env-vars=TZ=Asia/Tokyo,MANGA_WATCH_STORAGE_BACKEND=firestore,MANGA_WATCH_FIRESTORE_PROJECT=star-light-breaker,MANGA_WATCH_FETCH_BACKEND=cloud-run-job,MANGA_WATCH_GCP_PROJECT=star-light-breaker,MANGA_WATCH_CLOUD_RUN_REGION=asia-northeast1,MANGA_WATCH_CLOUD_RUN_JOB_NAME=comic-crawler-job \
  --set-secrets=DISCORD_APPLICATION_PUBLIC_KEY=comic-crawler-discord-application-public-key:latest
```

注意:

- Discord interaction endpoint は public ingress を前提にし、Discord request signature で認証する
- production では `MANGA_WATCH_INSECURE_DISABLE_VERIFICATION=true` を使わない
- `DISCORD_APPLICATION_PUBLIC_KEY` は direct env でも `*_SECRET_VERSION` でもよいが、deploy contract では Secret Manager を推奨する
- `MANGA_WATCH_FETCH_BACKEND=cloud-run-job` のとき `fetch` は Cloud Run Jobs API へ manual override 付きで handoff する
- local fallback として `MANGA_WATCH_FETCH_BACKEND=coordinator` を使って in-process 実行もできる

verification smoke shape:

```bash
eval "$(/Users/kentokumatsunami/Documents/GitHub/comic_crawler/.venv/bin/python - <<'PY'
from nacl.signing import SigningKey
key = SigningKey.generate()
print("export PRIVATE_KEY=" + key.encode().hex())
print("export PUBLIC_KEY=" + key.verify_key.encode().hex())
PY
)"

gcloud secrets create comic-crawler-discord-application-public-key \
  --project=star-light-breaker \
  --replication-policy=automatic

printf '%s' "$PUBLIC_KEY" | gcloud secrets versions add comic-crawler-discord-application-public-key \
  --project=star-light-breaker \
  --data-file=-

SERVICE_URL="$(gcloud run services describe comic-crawler-service \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --format='value(status.url)')"

/Users/kentokumatsunami/Documents/GitHub/comic_crawler/.venv/bin/python \
  scripts/post_signed_discord_interaction.py \
  --url "$SERVICE_URL" \
  --private-key "$PRIVATE_KEY" \
  --payload-json '{"type":1}' \
  --expect-status 200

/Users/kentokumatsunami/Documents/GitHub/comic_crawler/.venv/bin/python \
  scripts/post_signed_discord_interaction.py \
  --url "$SERVICE_URL" \
  --private-key "$PRIVATE_KEY" \
  --payload-json '{"type":1}' \
  --invalidate-signature \
  --expect-status 401
```

## 7. Scheduler caller IAM

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

## 8. Cloud Scheduler contract

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
