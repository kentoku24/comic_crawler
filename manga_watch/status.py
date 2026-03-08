#!/usr/bin/env python3
import json
import os
import time
from datetime import datetime
from typing import Dict, List, Mapping, Optional
from zoneinfo import ZoneInfo

from croniter import croniter

from manga_watch.storage import load_state, load_watchlist

DEFAULT_CRAWL_SCHEDULE = "0 19 * * *"
DEFAULT_STALE_TOLERANCE = 2.0
DEFAULT_BROKEN_FAILURES = 3
DEFAULT_TIMEZONE = "Asia/Tokyo"
HEALTH_STATES = ("healthy", "degraded", "stale", "broken", "pending")
SCHEDULE_INTERVAL_SAMPLES = 8


def status_timezone_name() -> str:
    return os.environ.get("TZ", DEFAULT_TIMEZONE)


def format_timestamp(unix_ts: Optional[int], timezone_name: str) -> str:
    if unix_ts is None:
        return "-"
    return datetime.fromtimestamp(unix_ts, tz=ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M:%S %Z")


def format_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return "-"
    remaining = int(seconds)
    if remaining <= 0:
        return "0s"

    parts: List[str] = []
    units = (
        ("d", 24 * 60 * 60),
        ("h", 60 * 60),
        ("m", 60),
        ("s", 1),
    )
    for suffix, span in units:
        value, remaining = divmod(remaining, span)
        if value:
            parts.append(f"{value}{suffix}")
        if len(parts) == 2:
            break
    return " ".join(parts)


def expected_interval_seconds_from_schedule(
    schedule: str,
    *,
    now: int,
    timezone_name: str,
) -> int:
    reference = datetime.fromtimestamp(now, tz=ZoneInfo(timezone_name))
    iterator = croniter(schedule, reference)
    previous = iterator.get_next(datetime)
    gaps: List[int] = []
    for _ in range(max(1, SCHEDULE_INTERVAL_SAMPLES - 1)):
        next_run = iterator.get_next(datetime)
        gaps.append(max(1, int((next_run - previous).total_seconds())))
        previous = next_run
    return int(sum(gaps) / len(gaps))


def default_expected_interval_seconds(*, now: int, timezone_name: str) -> int:
    raw_interval = os.environ.get("CRAWL_INTERVAL")
    if raw_interval:
        interval = int(raw_interval)
        if interval <= 0:
            raise ValueError("CRAWL_INTERVAL must be a positive integer (seconds)")
        return interval

    schedule = os.environ.get("CRAWL_SCHEDULE") or DEFAULT_CRAWL_SCHEDULE
    return expected_interval_seconds_from_schedule(
        schedule,
        now=now,
        timezone_name=timezone_name,
    )


def health_policy_for_entry(entry: Mapping[str, object], work_id: str) -> Dict[str, object]:
    policy = entry.get("health_policy")
    if policy is None:
        return {}
    if not isinstance(policy, Mapping):
        raise ValueError(f"watchlist entry {work_id} health_policy must be an object")

    normalized: Dict[str, object] = {}
    expected_interval = policy.get("expected_interval_seconds")
    if expected_interval is not None:
        expected_interval = int(expected_interval)
        if expected_interval <= 0:
            raise ValueError(
                f"watchlist entry {work_id} health_policy.expected_interval_seconds must be > 0"
            )
        normalized["expected_interval_seconds"] = expected_interval

    return normalized


def latest_label(latest: Mapping[str, object]) -> str:
    return str(
        latest.get("episode_title")
        or latest.get("episodeTitle")
        or latest.get("episode_code")
        or latest.get("episodeCode")
        or latest.get("url")
        or "未取得"
    )


def series_label(work_id: str, latest: Mapping[str, object]) -> str:
    return str(latest.get("series_title") or latest.get("seriesTitle") or latest.get("series") or work_id)


def derive_health_status(
    health: Mapping[str, object],
    *,
    now: int,
    expected_interval_seconds: int,
) -> Dict[str, object]:
    last_checked_at = health.get("last_checked_at")
    last_success_at = health.get("last_success_at")
    consecutive_failures = int(health.get("consecutive_failures") or 0)
    stale_after_seconds = max(1, int(expected_interval_seconds * DEFAULT_STALE_TOLERANCE))
    stale = last_success_at is not None and now - int(last_success_at) > stale_after_seconds

    if consecutive_failures >= DEFAULT_BROKEN_FAILURES:
        state = "broken"
    elif consecutive_failures > 0:
        state = "degraded"
    elif last_checked_at is None and last_success_at is None:
        state = "pending"
    elif stale:
        state = "stale"
    else:
        state = "healthy"

    return {
        "state": state,
        "stale": state == "stale",
        "last_checked_at": int(last_checked_at) if last_checked_at is not None else None,
        "last_success_at": int(last_success_at) if last_success_at is not None else None,
        "consecutive_failures": consecutive_failures,
        "expected_interval_seconds": expected_interval_seconds,
        "stale_after_seconds": stale_after_seconds,
    }


def build_status_report(
    *,
    watchlist_path: Optional[str] = None,
    state_path: Optional[str] = None,
    now: Optional[int] = None,
    timezone_name: Optional[str] = None,
) -> Dict[str, object]:
    current_time = int(time.time()) if now is None else int(now)
    timezone_name = timezone_name or status_timezone_name()
    watchlist = load_watchlist(watchlist_path)
    state = load_state(state_path)
    works_state = state.get("works", {})
    if not isinstance(works_state, Mapping):
        raise ValueError("state.works must be an object")

    default_interval_seconds = default_expected_interval_seconds(
        now=current_time,
        timezone_name=timezone_name,
    )
    enabled_entries = [entry for entry in watchlist["works"] if entry["enabled"]]
    health_counts = {state_name: 0 for state_name in HEALTH_STATES}
    work_reports = []
    latest_success_at = None

    for entry in enabled_entries:
        work_id = str(entry["id"])
        state_entry = works_state.get(work_id)
        if state_entry is None:
            state_entry = {}
        if not isinstance(state_entry, Mapping):
            raise ValueError(f"state entry {work_id} must be an object")

        latest = state_entry.get("latest")
        if latest is None:
            latest = {}
        if not isinstance(latest, Mapping):
            raise ValueError(f"state entry {work_id}.latest must be an object")

        stored_health = state_entry.get("health")
        if stored_health is None:
            stored_health = {}
        if not isinstance(stored_health, Mapping):
            raise ValueError(f"state entry {work_id}.health must be an object")

        policy = health_policy_for_entry(entry, work_id)
        expected_interval_seconds = int(policy.get("expected_interval_seconds") or default_interval_seconds)
        derived_health = derive_health_status(
            stored_health,
            now=current_time,
            expected_interval_seconds=expected_interval_seconds,
        )
        latest_success = derived_health["last_success_at"]
        if latest_success is not None:
            latest_success_at = latest_success if latest_success_at is None else max(latest_success_at, latest_success)

        work_reports.append(
            {
                "id": work_id,
                "source": str(entry["source"]),
                "series_title": series_label(work_id, latest),
                "latest_label": latest_label(latest),
                "url": latest.get("url"),
                "health": derived_health,
            }
        )
        health_counts[derived_health["state"]] += 1

    summary = {
        "configured_work_count": len(watchlist["works"]),
        "monitored_work_count": len(enabled_entries),
        "disabled_work_count": len(watchlist["works"]) - len(enabled_entries),
        "last_run_at": state.get("last_run_at"),
        "last_success_at": latest_success_at,
        "health_counts": health_counts,
        "failing_work_count": health_counts["degraded"] + health_counts["broken"],
        "stale_work_count": health_counts["stale"],
        "default_expected_interval_seconds": default_interval_seconds,
        "stale_tolerance": DEFAULT_STALE_TOLERANCE,
    }
    return {
        "generated_at": current_time,
        "timezone": timezone_name,
        "summary": summary,
        "works": work_reports,
    }


def format_status_report_text(report: Mapping[str, object]) -> str:
    timezone_name = str(report["timezone"])
    summary = report["summary"]
    health_counts = summary["health_counts"]
    works = report["works"]

    lines = [
        f"Monitoring status ({format_timestamp(int(report['generated_at']), timezone_name)})",
        (
            f"- monitored works: {summary['monitored_work_count']}"
            f" / configured: {summary['configured_work_count']}"
            f" / disabled: {summary['disabled_work_count']}"
        ),
        f"- last run: {format_timestamp(summary.get('last_run_at'), timezone_name)}",
        f"- last success: {format_timestamp(summary.get('last_success_at'), timezone_name)}",
        (
            "- health counts: "
            f"healthy={health_counts['healthy']}, "
            f"degraded={health_counts['degraded']}, "
            f"stale={health_counts['stale']}, "
            f"broken={health_counts['broken']}, "
            f"pending={health_counts['pending']}"
        ),
        (
            f"- expected interval: {format_duration(summary['default_expected_interval_seconds'])}"
            f" (stale after {summary['stale_tolerance']}x)"
        ),
    ]

    failing_works = [
        work for work in works if work["health"]["state"] in {"degraded", "broken"}
    ]
    if failing_works:
        lines.append("Failing works:")
        for work in failing_works:
            health = work["health"]
            lines.append(
                (
                    f"- [{health['state']}] {work['series_title']} ({work['id']}) "
                    f"source={work['source']} failures={health['consecutive_failures']} "
                    f"last_success={format_timestamp(health['last_success_at'], timezone_name)}"
                )
            )

    stale_works = [work for work in works if work["health"]["state"] == "stale"]
    if stale_works:
        lines.append("Stale works:")
        for work in stale_works:
            health = work["health"]
            lines.append(
                (
                    f"- [stale] {work['series_title']} ({work['id']}) "
                    f"source={work['source']} "
                    f"last_success={format_timestamp(health['last_success_at'], timezone_name)} "
                    f"stale_after={format_duration(health['stale_after_seconds'])}"
                )
            )

    lines.append("Works:")
    for work in works:
        health = work["health"]
        lines.append(
            (
                f"- [{health['state']}] {work['series_title']} ({work['id']}) "
                f"source={work['source']} latest={work['latest_label']} "
                f"last_checked={format_timestamp(health['last_checked_at'], timezone_name)} "
                f"last_success={format_timestamp(health['last_success_at'], timezone_name)} "
                f"failures={health['consecutive_failures']}"
            )
        )
    return "\n".join(lines)


def render_status_report(report: Mapping[str, object], *, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False)
    if output_format == "text":
        return format_status_report_text(report)
    raise ValueError(f"unsupported output format: {output_format}")
