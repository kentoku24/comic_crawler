import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from manga_watch.status import build_status_report, format_status_report_text


def write_watchlist(path: Path, works):
    path.write_text(
        json.dumps({"version": 2, "works": works}, ensure_ascii=False),
        encoding="utf-8",
    )


def write_state(path: Path, works, *, last_run_at):
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "works": works,
                "last_run_at": last_run_at,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def watchlist_entry(
    work_id: str,
    *,
    source: str = "fake",
    health_policy=None,
):
    entry = {
        "id": work_id,
        "source": source,
        "seed_url": f"https://example.com/{work_id}",
        "enabled": True,
        "notification_policy": {
            "mode": "all",
            "allowed_update_types": None,
        },
    }
    if health_policy is not None:
        entry["health_policy"] = health_policy
    return entry


def state_entry(
    *,
    series_title: str,
    episode_title: str,
    last_checked_at,
    last_success_at,
    consecutive_failures: int,
):
    return {
        "latest": {
            "source": "fake",
            "work_id": series_title,
            "latest_key": episode_title,
            "series_title": series_title,
            "episode_title": episode_title,
            "url": f"https://example.com/{series_title}/{episode_title}",
        },
        "history": [],
        "health": {
            "last_checked_at": last_checked_at,
            "last_success_at": last_success_at,
            "consecutive_failures": consecutive_failures,
        },
    }


class StatusReportTests(unittest.TestCase):
    maxDiff = None

    def test_build_status_report_classifies_health_states(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            watchlist_path = tmpdir_path / "watchlist.json"
            state_path = tmpdir_path / "state.json"
            write_watchlist(
                watchlist_path,
                [
                    watchlist_entry("healthy-work"),
                    watchlist_entry("degraded-work"),
                    watchlist_entry("broken-work"),
                    watchlist_entry("stale-work"),
                    watchlist_entry("pending-work"),
                ],
            )
            write_state(
                state_path,
                {
                    "healthy-work": state_entry(
                        series_title="Healthy",
                        episode_title="第2話",
                        last_checked_at=9_900,
                        last_success_at=9_900,
                        consecutive_failures=0,
                    ),
                    "degraded-work": state_entry(
                        series_title="Degraded",
                        episode_title="第5話",
                        last_checked_at=9_950,
                        last_success_at=9_600,
                        consecutive_failures=1,
                    ),
                    "broken-work": state_entry(
                        series_title="Broken",
                        episode_title="第8話",
                        last_checked_at=9_980,
                        last_success_at=9_100,
                        consecutive_failures=3,
                    ),
                    "stale-work": state_entry(
                        series_title="Stale",
                        episode_title="第1話",
                        last_checked_at=9_000,
                        last_success_at=2_700,
                        consecutive_failures=0,
                    ),
                    "pending-work": {
                        "latest": {},
                        "history": [],
                        "health": {
                            "last_checked_at": None,
                            "last_success_at": None,
                            "consecutive_failures": 0,
                        },
                    },
                },
                last_run_at=9_980,
            )

            with mock.patch.dict(os.environ, {"CRAWL_INTERVAL": "3600", "TZ": "Asia/Tokyo"}, clear=False):
                report = build_status_report(
                    watchlist_path=str(watchlist_path),
                    state_path=str(state_path),
                    now=10_000,
                )

        self.assertEqual(5, report["summary"]["monitored_work_count"])
        self.assertEqual(
            {
                "healthy": 1,
                "degraded": 1,
                "stale": 1,
                "broken": 1,
                "pending": 1,
            },
            report["summary"]["health_counts"],
        )
        self.assertEqual(2, report["summary"]["failing_work_count"])
        self.assertEqual(1, report["summary"]["stale_work_count"])

        by_id = {work["id"]: work for work in report["works"]}
        self.assertEqual("healthy", by_id["healthy-work"]["health"]["state"])
        self.assertEqual("degraded", by_id["degraded-work"]["health"]["state"])
        self.assertEqual("broken", by_id["broken-work"]["health"]["state"])
        self.assertEqual("stale", by_id["stale-work"]["health"]["state"])
        self.assertEqual("pending", by_id["pending-work"]["health"]["state"])

    def test_build_status_report_uses_expected_interval_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            watchlist_path = tmpdir_path / "watchlist.json"
            state_path = tmpdir_path / "state.json"
            write_watchlist(
                watchlist_path,
                [
                    watchlist_entry("default-window"),
                    watchlist_entry(
                        "narrow-window",
                        health_policy={"expected_interval_seconds": 1800},
                    ),
                ],
            )
            write_state(
                state_path,
                {
                    "default-window": state_entry(
                        series_title="Default Window",
                        episode_title="第3話",
                        last_checked_at=9_000,
                        last_success_at=5_999,
                        consecutive_failures=0,
                    ),
                    "narrow-window": state_entry(
                        series_title="Narrow Window",
                        episode_title="第4話",
                        last_checked_at=9_000,
                        last_success_at=5_999,
                        consecutive_failures=0,
                    ),
                },
                last_run_at=9_000,
            )

            with mock.patch.dict(os.environ, {"CRAWL_INTERVAL": "3600", "TZ": "Asia/Tokyo"}, clear=False):
                report = build_status_report(
                    watchlist_path=str(watchlist_path),
                    state_path=str(state_path),
                    now=10_000,
                )

        by_id = {work["id"]: work for work in report["works"]}
        self.assertEqual("healthy", by_id["default-window"]["health"]["state"])
        self.assertEqual("stale", by_id["narrow-window"]["health"]["state"])
        self.assertEqual(3_600, by_id["narrow-window"]["health"]["stale_after_seconds"])

    def test_format_status_report_text_surfaces_failing_and_stale_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            watchlist_path = tmpdir_path / "watchlist.json"
            state_path = tmpdir_path / "state.json"
            write_watchlist(
                watchlist_path,
                [
                    watchlist_entry("broken-work"),
                    watchlist_entry("stale-work"),
                ],
            )
            write_state(
                state_path,
                {
                    "broken-work": state_entry(
                        series_title="Broken",
                        episode_title="第8話",
                        last_checked_at=9_980,
                        last_success_at=9_100,
                        consecutive_failures=3,
                    ),
                    "stale-work": state_entry(
                        series_title="Stale",
                        episode_title="第1話",
                        last_checked_at=9_000,
                        last_success_at=2_700,
                        consecutive_failures=0,
                    ),
                },
                last_run_at=9_980,
            )

            with mock.patch.dict(os.environ, {"CRAWL_INTERVAL": "3600", "TZ": "Asia/Tokyo"}, clear=False):
                report = build_status_report(
                    watchlist_path=str(watchlist_path),
                    state_path=str(state_path),
                    now=10_000,
                )

        rendered = format_status_report_text(report)
        self.assertIn("Failing works:", rendered)
        self.assertIn("Stale works:", rendered)
        self.assertIn("[broken] Broken", rendered)
        self.assertIn("[stale] Stale", rendered)
        self.assertIn("Works:", rendered)

    def test_check_module_status_json_output(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            watchlist_path = tmpdir_path / "watchlist.json"
            state_path = tmpdir_path / "state.json"
            write_watchlist(watchlist_path, [watchlist_entry("healthy-work")])
            write_state(
                state_path,
                {
                    "healthy-work": state_entry(
                        series_title="Healthy",
                        episode_title="第2話",
                        last_checked_at=9_900,
                        last_success_at=9_900,
                        consecutive_failures=0,
                    ),
                },
                last_run_at=9_980,
            )
            env = os.environ.copy()
            env.update(
                {
                    "CRAWL_INTERVAL": "3600",
                    "TZ": "Asia/Tokyo",
                }
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "manga_watch.check",
                    "--status",
                    "--format",
                    "json",
                    "--watchlist",
                    str(watchlist_path),
                    "--state",
                    str(state_path),
                    "--now",
                    "10000",
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(1, payload["summary"]["monitored_work_count"])
        self.assertEqual("healthy", payload["works"][0]["health"]["state"])
        self.assertEqual("Healthy", payload["works"][0]["series_title"])

    def test_check_module_rejects_status_only_flags_without_status_mode(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            watchlist_path = tmpdir_path / "watchlist.json"
            write_watchlist(watchlist_path, [watchlist_entry("healthy-work")])

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "manga_watch.check",
                    str(watchlist_path),
                    "--format",
                    "json",
                ],
                cwd=repo_root,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(2, result.returncode)
        self.assertIn("require --status", result.stderr)


if __name__ == "__main__":
    unittest.main()
