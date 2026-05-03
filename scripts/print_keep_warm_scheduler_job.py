#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex

DEFAULT_PROJECT = "star-light-breaker"
DEFAULT_REGION = "asia-northeast1"
DEFAULT_TIME_ZONE = "Asia/Tokyo"
DEFAULT_SCHEDULER_JOB_NAME = "comic-crawler-service-keep-warm"
DEFAULT_SCHEDULE = "*/5 * * * *"
DEFAULT_SERVICE_PATH = "/healthz"


def build_service_healthz_uri(*, service_url: str, service_path: str = DEFAULT_SERVICE_PATH) -> str:
    normalized_base = service_url.rstrip("/")
    normalized_path = service_path if service_path.startswith("/") else f"/{service_path}"
    return f"{normalized_base}{normalized_path}"


def build_gcloud_scheduler_keep_warm_command(
    *,
    action: str,
    service_url: str,
    project: str = DEFAULT_PROJECT,
    region: str = DEFAULT_REGION,
    scheduler_job_name: str = DEFAULT_SCHEDULER_JOB_NAME,
    schedule: str = DEFAULT_SCHEDULE,
    time_zone: str = DEFAULT_TIME_ZONE,
    service_path: str = DEFAULT_SERVICE_PATH,
) -> str:
    normalized_schedule = schedule.strip()
    if action not in {"create", "update"}:
        raise ValueError(f"unsupported action: {action}")
    if not normalized_schedule:
        raise ValueError("schedule is required")

    flags = [
        f"--project={project}",
        f"--location={region}",
        f"--schedule={shlex.quote(normalized_schedule)}",
        f"--time-zone={time_zone}",
        f"--uri={build_service_healthz_uri(service_url=service_url, service_path=service_path)}",
        "--http-method=GET",
    ]
    command = f"gcloud scheduler jobs {action} http {scheduler_job_name}"
    return command + " \\\n  " + " \\\n  ".join(flags)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print keep-warm Cloud Scheduler command for Cloud Run Service.")
    parser.add_argument("action", choices=("create", "update"))
    parser.add_argument("--service-url", required=True)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--time-zone", default=DEFAULT_TIME_ZONE)
    parser.add_argument("--schedule", default=DEFAULT_SCHEDULE)
    parser.add_argument("--scheduler-job", default=DEFAULT_SCHEDULER_JOB_NAME)
    parser.add_argument("--service-path", default=DEFAULT_SERVICE_PATH)
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.schedule = args.schedule.strip()
    if not args.schedule:
        parser.error("--schedule must be a non-empty cron expression")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(
        build_gcloud_scheduler_keep_warm_command(
            action=args.action,
            service_url=args.service_url,
            project=args.project,
            region=args.region,
            scheduler_job_name=args.scheduler_job,
            schedule=args.schedule,
            time_zone=args.time_zone,
            service_path=args.service_path,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
