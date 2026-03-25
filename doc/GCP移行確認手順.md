# GCP移行確認手順

この文書は `comic_crawler` の GCP resource contract が壊れていないかを確認するための手順書である。  
命名、deploy target、Scheduler 呼び出し、blocker の境界を毎回同じ観点で確認する。

## 1. 事前条件

- `gcloud auth login` または `gcloud auth application-default login` が完了している
- 対象 project は `star-light-breaker`
- 対象 region は `asia-northeast1`
- 対象 zone は `asia-northeast1-a`

初期化:

```bash
gcloud config set project star-light-breaker
gcloud config set run/region asia-northeast1
```

## 2. Baseline 確認

まず空の baseline または既存 resource の有無を確認する。

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

2026-03-25 に [#143 の確認コメント 1](https://github.com/kentoku24/comic_crawler/issues/143#issuecomment-4127050468) と [確認コメント 2](https://github.com/kentoku24/comic_crawler/issues/143#issuecomment-4127061135) で採取した observed baseline。ここでは issue #143 の確認証跡を参照し、現時点の環境状態を repo 文書だけで断定しない:

- Cloud Run jobs list: `[]`
- Cloud Run services list: `[]`
- Cloud Scheduler jobs list: `[]`

## 3. Canonical naming 確認

存在してよい resource 名は次だけである。

- Cloud Run Job: `comic-crawler-job`
- Cloud Run Service: `comic-crawler-service`
- Cloud Scheduler Job: `comic-crawler-scheduled-run`
- Scheduler service account: `comic-crawler-scheduler@star-light-breaker.iam.gserviceaccount.com`
- Artifact image: `ghcr.io/kentoku24/comic_crawler:latest`

`describe` で対象が canonical name と一致することを確認する。

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

## 4. Scheduler command 確認

Scheduler helper が canonical target を出すかを確認する。

create 用:

```bash
SCHEDULE="0 * * * *"
python3 scripts/print_cloud_scheduler_job.py create --schedule "$SCHEDULE"
```

update 用:

```bash
SCHEDULE="0 * * * *"
python3 scripts/print_cloud_scheduler_job.py update --schedule "$SCHEDULE"
```

確認ポイント:

- command が `gcloud scheduler jobs create http comic-crawler-scheduled-run` または `update http comic-crawler-scheduled-run` で始まる
- URI が `https://run.googleapis.com/v2/projects/star-light-breaker/locations/asia-northeast1/jobs/comic-crawler-job:run`
- auth が OAuth service account (`comic-crawler-scheduler@star-light-breaker.iam.gserviceaccount.com`)
- request body に `MANGA_WATCH_TRIGGER_SOURCE=scheduled` override が含まれる

## 5. Scheduler caller IAM 確認

service account が存在し、Cloud Run Job に対して override 付き実行 role を持つことを確認する。

存在確認:

```bash
gcloud iam service-accounts describe \
  comic-crawler-scheduler@star-light-breaker.iam.gserviceaccount.com \
  --project=star-light-breaker
```

binding 確認:

```bash
gcloud run jobs get-iam-policy comic-crawler-job \
  --project=star-light-breaker \
  --region=asia-northeast1
```

確認ポイント:

- member に `serviceAccount:comic-crawler-scheduler@star-light-breaker.iam.gserviceaccount.com` がある
- role が `roles/run.jobsExecutorWithOverrides`
- `roles/run.jobsExecutor` だけで済ませていない

## 6. Deploy contract 確認

Job deploy command shape:

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

Service deploy shape:

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

確認ポイント:

- image が `ghcr.io/kentoku24/comic_crawler:latest`
- Job が `python -m manga_watch.run_job` を command override している
- Service が `python -m manga_watch.run_service` を command override している
- Service が `DISCORD_APPLICATION_PUBLIC_KEY` と `MANGA_WATCH_FETCH_BACKEND=cloud-run-job` を持つ
- Job 名と Service 名を取り違えていない
- region が `asia-northeast1`
- production deploy で `MANGA_WATCH_INSECURE_DISABLE_VERIFICATION=true` を使っていない

署名検証 smoke:

```bash
eval "$(/Users/kentokumatsunami/Documents/GitHub/comic_crawler/.venv/bin/python - <<'PY'
from nacl.signing import SigningKey
key = SigningKey.generate()
print("export PRIVATE_KEY=" + key.encode().hex())
print("export PUBLIC_KEY=" + key.verify_key.encode().hex())
PY
)"

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

確認ポイント:

- valid signature request が `200`
- invalid signature request が `401`
- `latest` / `fetch` も `--payload-json '{"type":2,"data":{"name":"latest"}}'` / `fetch` で同じ helper から確認できる

## 7. Manual run 確認

resource contract の manual run command は次で固定する。

```bash
gcloud run jobs execute comic-crawler-job \
  --project=star-light-breaker \
  --region=asia-northeast1 \
  --wait
```

ただし、この task 時点では次を前提に「command shape を確認する」までに留める。

- Firestore / Secret Manager / migration contract 自体は `doc/gcp-runtime.md` を参照する
- 実環境 smoke test は #139 が未解決なので未完了
- Discord interaction service path は `python -m manga_watch.run_service` を source of truth とする
- default image entrypoint は `python -m manga_watch.runner` のままだが、Cloud Run Job contract では `python -m manga_watch.run_job` を command override して使う

したがって、手動実行を success criteria に含めるのは後続 runtime packet 完了後とする。

## 8. 完了判定

この packet の確認完了条件は次である。

- canonical resource 名が文書どおり固定されている
- helper script が canonical Scheduler command を出力する
- docs が `doc/gcp-runtime.md` と #146 の blocker 境界を明記している
- GCP resource contract を参照する後続 issue が、この文書の名前と command をそのまま使える
