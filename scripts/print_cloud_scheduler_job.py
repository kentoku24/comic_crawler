#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex

DEFAULT_PROJECT = "star-light-breaker"
DEFAULT_REGION = "asia-northeast1"
DEFAULT_TIME_ZONE = "Asia/Tokyo"
DEFAULT_CLOUD_RUN_JOB_NAME = "comic-crawler-job"
DEFAULT_CLOUD_SCHEDULER_JOB_NAME = "comic-crawler-scheduled-run"
DEFAULT_SCHEDULER_SERVICE_ACCOUNT_EMAIL = (
    "comic-crawler-scheduler@star-light-breaker.iam.gserviceaccount.com"
)
DEFAULT_OAUTH_TOKEN_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
DEFAULT_TRIGGER_SOURCE = "scheduled"


def build_cloud_run_job_run_uri(*, project: str, region: str, job_name: str) -> str:
    return (
        "https://run.googleapis.com/v2/projects/"
        f"{project}/locations/{region}/jobs/{job_name}:run"
    )


def build_run_request_body(*, trigger_source: str = DEFAULT_TRIGGER_SOURCE) -> dict[str, object]:
    return {
        "overrides": {
            "containerOverrides": [
                {
                    "env": [
                        {
                            "name": "MANGA_WATCH_TRIGGER_SOURCE",
                            "value": trigger_source,
                        }
                    ]
                }
            ]
        }
    }


def build_gcloud_scheduler_http_command(
    *,
    action: str,
    project: str = DEFAULT_PROJECT,
    region: str = DEFAULT_REGION,
    scheduler_job_name: str = DEFAULT_CLOUD_SCHEDULER_JOB_NAME,
    cloud_run_job_name: str = DEFAULT_CLOUD_RUN_JOB_NAME,
    oauth_service_account_email: str = DEFAULT_SCHEDULER_SERVICE_ACCOUNT_EMAIL,
    schedule: str | None = None,
    time_zone: str = DEFAULT_TIME_ZONE,
    oauth_token_scope: str = DEFAULT_OAUTH_TOKEN_SCOPE,
    trigger_source: str = DEFAULT_TRIGGER_SOURCE,
) -> str:
    normalized_schedule = schedule.strip() if schedule is not None else None

    if action not in {"create", "update"}:
        raise ValueError(f"unsupported action: {action}")
    if action == "create" and not normalized_schedule:
        raise ValueError("schedule is required when action=create")

    uri = build_cloud_run_job_run_uri(
        project=project,
        region=region,
        job_name=cloud_run_job_name,
    )
    message_body = json.dumps(
        build_run_request_body(trigger_source=trigger_source),
        separators=(",", ":"),
    )

    flags = [
        f"--project={project}",
        f"--location={region}",
    ]
    if normalized_schedule:
        flags.append(f"--schedule={shlex.quote(normalized_schedule)}")
    header_flag = "--headers=Content-Type=application/json"
    if action == "update":
        header_flag = "--update-headers=Content-Type=application/json"

    flags.extend(
        [
            f"--time-zone={time_zone}",
            "--http-method=POST",
            f"--uri={uri}",
            f"--oauth-service-account-email={oauth_service_account_email}",
            f"--oauth-token-scope={oauth_token_scope}",
            f"--message-body={shlex.quote(message_body)}",
            header_flag,
        ]
    )
    command = f"gcloud scheduler jobs {action} http {scheduler_job_name}"
    return command + " \\\n  " + " \\\n  ".join(flags)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print the canonical Cloud Scheduler command for comic_crawler.",
    )
    parser.add_argument("action", choices=("create", "update"))
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--time-zone", default=DEFAULT_TIME_ZONE)
    parser.add_argument("--schedule")
    parser.add_argument("--cloud-run-job", default=DEFAULT_CLOUD_RUN_JOB_NAME)
    parser.add_argument("--scheduler-job", default=DEFAULT_CLOUD_SCHEDULER_JOB_NAME)
    parser.add_argument(
        "--scheduler-service-account-email",
        default=DEFAULT_SCHEDULER_SERVICE_ACCOUNT_EMAIL,
    )
    parser.add_argument("--trigger-source", default=DEFAULT_TRIGGER_SOURCE)
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.action == "create":
        normalized_schedule = args.schedule.strip() if args.schedule is not None else None
        if not normalized_schedule:
            parser.error("--schedule must be a non-empty cron expression when action=create")
        args.schedule = normalized_schedule
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(
        build_gcloud_scheduler_http_command(
            action=args.action,
            project=args.project,
            region=args.region,
            scheduler_job_name=args.scheduler_job,
            cloud_run_job_name=args.cloud_run_job,
            oauth_service_account_email=args.scheduler_service_account_email,
            schedule=args.schedule,
            time_zone=args.time_zone,
            trigger_source=args.trigger_source,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
