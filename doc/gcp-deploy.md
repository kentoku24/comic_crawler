# GCP Deploy Contract

この文書は `comic_crawler` repo の canonical GCP naming / deploy contract である。  
GCP 上の resource 名、artifact image、Scheduler 呼び出し契約、未解決 blocker をここで固定する。

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

- Job の durable state / secret resolution は [#145](https://github.com/kentoku24/comic_crawler/issues/145) が blocker
- Discord interaction endpoint は [#146](https://github.com/kentoku24/comic_crawler/issues/146) が blocker
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

Cloud Run Job の canonical name は `comic-crawler-job`。artifact image は `ghcr.io/kentoku24/comic_crawler:latest` を使う。

作成:

```bash
gcloud run jobs create comic-crawler-job \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --image=ghcr.io/kentoku24/comic_crawler:latest \
  --tasks=1 \
  --max-retries=0 \
  --set-env-vars=TZ=Asia/Tokyo,MANGA_WATCH_NOTIFIER_BACKENDS=stdout
```

更新:

```bash
gcloud run jobs update comic-crawler-job \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --image=ghcr.io/kentoku24/comic_crawler:latest \
  --tasks=1 \
  --max-retries=0 \
  --update-env-vars=TZ=Asia/Tokyo,MANGA_WATCH_NOTIFIER_BACKENDS=stdout
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
- 現在の image は long-running runner を起動するため、Job 実行成功をこの task では保証しない
- production-ready な Job 実行経路は #145 と後続 runtime packet が入るまで未完了

## 6. Cloud Run Service naming reservation

Cloud Run Service の canonical name は `comic-crawler-service`。この名前は Discord interaction endpoint 用に予約する。

service 名だけを先に固定する場合の deploy skeleton:

```bash
gcloud run deploy comic-crawler-service \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --image=ghcr.io/kentoku24/comic_crawler:latest
```

注意:

- `comic-crawler-service` は naming contract を先に固定するための entry
- Discord interaction runtime 自体は #146 が blocker
- この task では Service routing / request auth / ingress / public-or-private exposure / Discord signature verification は固定しない
- `--allow-unauthenticated` / `--no-allow-unauthenticated` を含む公開形態の選択は #146 の inbound contract で決める

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
