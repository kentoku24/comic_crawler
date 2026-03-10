#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import unittest
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from manga_watch.discord_fetch import handle_fetch_trigger
from manga_watch.discord_latest import build_latest_query_response, handle_latest_query
from manga_watch.runner import RunCoordinator, RunnerConfig
from manga_watch.notifier import NotifierConfig


TARGETS_MS = {
    "runner_100_works": 30_000,
    "latest_ack": 3_000,
    "fetch_ack": 3_000,
    "latest_full_response": 10_000,
}


def make_watchlist(work_count: int) -> dict[str, object]:
    return {
        "version": 2,
        "works": [
            {
                "id": f"work-{index}",
                "source": "comic-walker",
                "seed_url": f"https://example.com/work-{index}",
                "enabled": True,
                "notification_policy": {"mode": "all", "allowed_update_types": None},
            }
            for index in range(work_count)
        ],
    }


def make_state(work_count: int) -> dict[str, object]:
    return {
        "version": 2,
        "works": {
            f"work-{index}": {
                "latest": {
                    "series_title": f"作品{index}",
                    "episode_title": f"第{index}話",
                    "latest_key": f"episode-{index}",
                    "url": f"https://example.com/episodes/{index}",
                },
                "history": [],
                "health": {
                    "last_checked_at": 1_700_000_000,
                    "last_success_at": 1_700_000_000,
                    "consecutive_failures": 0,
                },
            }
            for index in range(work_count)
        },
        "last_run_at": 1_700_000_000,
        "notification_outbox": [],
        "discord_delivery": {
            "daily_notification": {
                "delivered_latest_keys": {},
                "pending_messages": [],
            }
        },
    }


def build_runner_config() -> RunnerConfig:
    return RunnerConfig(
        timezone_name="Asia/Tokyo",
        watchlist_path="/tmp/watchlist.json",
        crawl_schedule="0 19 * * *",
        crawl_interval=None,
        run_on_startup=True,
        notifier_config=NotifierConfig(backends=("stdout",)),
        discord_outbound_config=None,
    )


def measure_once(func) -> float:
    started = time.perf_counter()
    func()
    return (time.perf_counter() - started) * 1000


def summarize(name: str, samples: list[float]) -> dict[str, object]:
    ordered = sorted(samples)
    p95_index = max(0, int(round((len(ordered) - 1) * 0.95)))
    return {
        "name": name,
        "samples_ms": [round(sample, 3) for sample in samples],
        "average_ms": round(mean(samples), 3),
        "max_ms": round(max(samples), 3),
        "p95_ms": round(ordered[p95_index], 3),
        "target_ms": TARGETS_MS[name],
    }


def benchmark_runner_100_works(sample_count: int) -> dict[str, object]:
    watchlist = make_watchlist(100)
    state = make_state(100)

    def run_once_benchmark() -> None:
        config = build_runner_config()

        def checker(_):
            return {"updates": [], "errors": {"sources": [], "run": []}, "state": state}

        from manga_watch.runner import run_once

        run_once(
            config,
            notifier=None,
            checker=checker,
            state_loader=lambda: state,
            state_saver=lambda payload: payload,
            report_logger=lambda _: None,
            error_logger=lambda _: None,
        )

    return summarize("runner_100_works", [measure_once(run_once_benchmark) for _ in range(sample_count)])


def benchmark_latest_ack(sample_count: int) -> dict[str, object]:
    watchlist = make_watchlist(100)
    state = make_state(100)

    def ack() -> None:
        handle_latest_query(
            "latest",
            watchlist_loader=lambda _: watchlist,
            state_loader=lambda _: state,
            timezone_name="Asia/Tokyo",
        )

    return summarize("latest_ack", [measure_once(ack) for _ in range(sample_count)])


def benchmark_fetch_ack(sample_count: int) -> dict[str, object]:
    def ack() -> None:
        coordinator = RunCoordinator(
            config=build_runner_config(),
            notifier=None,
            checker=lambda _: {"updates": [], "errors": {"sources": [], "run": []}, "state": make_state(1)},
            state_loader=lambda: make_state(1),
            state_saver=lambda payload: payload,
            report_logger=lambda _: None,
            error_logger=lambda _: None,
        )
        handle_fetch_trigger("fetch", coordinator=coordinator)
        while coordinator.is_running():
            time.sleep(0.001)

    return summarize("fetch_ack", [measure_once(ack) for _ in range(sample_count)])


def benchmark_latest_full_response(sample_count: int) -> dict[str, object]:
    watchlist = make_watchlist(100)
    state = make_state(100)
    return summarize(
        "latest_full_response",
        [measure_once(lambda: build_latest_query_response(watchlist, state, timezone_name="Asia/Tokyo")) for _ in range(sample_count)],
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the benchmark harness aligned to issue #96.")
    parser.add_argument("--sample-count", type=int, default=3)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sample_count = max(1, args.sample_count)
    payload = {
        "targets_ms": TARGETS_MS,
        "metrics": [
            benchmark_runner_100_works(sample_count),
            benchmark_latest_ack(sample_count),
            benchmark_fetch_ack(sample_count),
            benchmark_latest_full_response(sample_count),
        ],
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
